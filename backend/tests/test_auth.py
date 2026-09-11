"""The JWTs Reli mints and Google's callback: who gets a code, who is turned away, and what is logged.

The callback is built onto a fresh ``FastAPI()`` with ``auth._session`` bound to the fixture session
and the Basic check applied, so the tests also prove the callback is exempt from it — without the
exemption every request below would be 401. Google is ``httpx.MockTransport`` throughout.
"""

import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import api, auth, google_login
from backend.config import settings
from backend.oauth_state import cleanup_and_get, cleanup_and_store, mcp_auth_codes, mcp_oauth_sessions

SECRET_KEY = "a-test-secret-key-that-is-forty-eight-chars-long"
CLIENT_ID = "client-id.apps.googleusercontent.com"
CLIENT_REDIRECT = "https://client.example.test/callback"


@pytest.fixture()
def sign_in_settings(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET_KEY)
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "Owner@Example.com")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "s3cret-client-secret")
    monkeypatch.setattr(settings, "GOOGLE_AUTH_REDIRECT_URI", "https://reli.example.test/api/auth/google/callback")
    monkeypatch.setattr(settings, "WEB_UI_PASSWORD", "web-password")


@pytest.fixture()
def client(session, monkeypatch, sign_in_settings):
    @contextmanager
    def _fixture_session():
        yield session

    monkeypatch.setattr(auth, "_session", _fixture_session)
    app = FastAPI()
    app.include_router(auth.router)
    api.add_web_view_auth(app)
    return TestClient(app, follow_redirects=False)


@pytest.fixture()
def google(monkeypatch):
    """A Google whose token endpoint answers with the given handler; ``seen`` collects the requests."""
    seen: list[httpx.Request] = []

    def install(handler):
        def recording(request):
            seen.append(request)
            return handler(request)

        monkeypatch.setattr(
            google_login, "_http_client", lambda: httpx.Client(transport=httpx.MockTransport(recording))
        )
        return seen

    return install


def _id_token(email="owner@example.com", subject="1234567890"):
    return jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": CLIENT_ID,
            "sub": subject,
            "email": email,
            "email_verified": True,
            "exp": datetime.now(UTC) + timedelta(seconds=300),
        },
        "unchecked",
        algorithm="HS256",
    )


def _seed_flow(session, state="server-state", client_state="client-state"):
    cleanup_and_store(
        session,
        mcp_oauth_sessions,
        state,
        {
            "client_state": client_state,
            "redirect_uri": CLIENT_REDIRECT,
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "client_id": "client-1",
            "scope": "mcp",
            "google_code_verifier": "verifier",
            "expires_at": datetime.now(UTC) + timedelta(minutes=10),
        },
    )


def _location_query(response):
    location = response.headers["location"]
    assert location.startswith(CLIENT_REDIRECT + "?")
    return {key: values[0] for key, values in parse_qs(urlsplit(location).query).items()}


# --- JWTs ------------------------------------------------------------------


def test_a_token_round_trips_for_its_audience_only(sign_in_settings):
    token = auth.create_jwt("1234567890", "owner@example.com", audience="mcp")

    claims = auth.decode_jwt(token, audience="mcp")
    assert claims["sub"] == "1234567890"
    assert claims["email"] == "owner@example.com"
    assert claims["jti"]

    with pytest.raises(jwt.InvalidTokenError):
        auth.decode_jwt(token, audience="web")


def test_base_url_prefers_the_setting_and_falls_back_to_the_redirect_uris_host(sign_in_settings, monkeypatch):
    assert auth.base_url() == "https://reli.example.test"

    monkeypatch.setattr(settings, "RELI_BASE_URL", "https://other.example.test/")
    assert auth.base_url() == "https://other.example.test"

    monkeypatch.setattr(settings, "RELI_BASE_URL", "")
    monkeypatch.setattr(settings, "GOOGLE_AUTH_REDIRECT_URI", "")
    assert auth.base_url() == ""


def test_missing_sign_in_settings_names_each_empty_one(sign_in_settings, monkeypatch):
    assert auth.missing_sign_in_settings() == []

    monkeypatch.setattr(settings, "SECRET_KEY", "")
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "")
    assert auth.missing_sign_in_settings() == ["SECRET_KEY", "ALLOWED_EMAILS"]


# --- The callback ------------------------------------------------------------


def test_a_good_sign_in_sends_the_client_a_code_bound_to_the_identity(client, session, google, caplog):
    _seed_flow(session)
    google(lambda request: httpx.Response(200, json={"access_token": "never-read", "id_token": _id_token()}))

    with caplog.at_level(logging.DEBUG):
        response = client.get("/api/auth/google/callback", params={"code": "google-code", "state": "server-state"})

    assert response.status_code == 302
    query = _location_query(response)
    assert query["state"] == "client-state"
    stored = cleanup_and_get(session, mcp_auth_codes, query["code"])
    assert stored is not None
    assert stored["subject"] == "1234567890"
    assert stored["email"] == "owner@example.com"
    assert stored["client_id"] == "client-1"
    assert query["code"] not in caplog.text
    assert cleanup_and_get(session, mcp_oauth_sessions, "server-state") is None


def test_an_unknown_state_is_400_and_the_callback_is_exempt_from_the_basic_check(client, google):
    seen = google(lambda request: httpx.Response(500))

    response = client.get("/api/auth/google/callback", params={"code": "google-code", "state": "nope"})

    assert response.status_code == 400
    assert "start the sign-in again" in response.json()["detail"]
    assert seen == []


def test_an_account_outside_the_allowlist_is_sent_back_to_the_client_as_access_denied(client, session, google, caplog):
    _seed_flow(session)
    google(
        lambda request: httpx.Response(
            200, json={"access_token": "never-read", "id_token": _id_token(email="intruder@example.com")}
        )
    )

    with caplog.at_level(logging.DEBUG):
        response = client.get("/api/auth/google/callback", params={"code": "google-code", "state": "server-state"})

    assert response.status_code == 302
    query = _location_query(response)
    assert query["error"] == "access_denied"
    assert "ALLOWED_EMAILS" in query["error_description"]
    assert query["state"] == "client-state"
    assert "intruder@example.com" not in caplog.text


def test_a_cancelled_sign_in_is_relayed_to_the_client_without_an_exchange(client, session, google):
    _seed_flow(session)
    seen = google(lambda request: httpx.Response(500))

    response = client.get("/api/auth/google/callback", params={"error": "access_denied", "state": "server-state"})

    assert response.status_code == 302
    query = _location_query(response)
    assert query["error"] == "access_denied"
    assert "cancelled" in query["error_description"]
    assert seen == []


def test_a_google_refusal_is_502_naming_the_remedy(client, session, google):
    _seed_flow(session)
    google(lambda request: httpx.Response(400, json={"error": "redirect_uri_mismatch"}))

    response = client.get("/api/auth/google/callback", params={"code": "google-code", "state": "server-state"})

    assert response.status_code == 502
    assert "Google Cloud console" in response.json()["detail"]


def test_the_code_is_appended_to_a_redirect_uri_that_already_has_a_query(client, session, google, monkeypatch):
    cleanup_and_store(
        session,
        mcp_oauth_sessions,
        "server-state",
        {
            "client_state": "",
            "redirect_uri": CLIENT_REDIRECT + "?app=claude",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "client_id": "client-1",
            "scope": "mcp",
            "google_code_verifier": "verifier",
            "expires_at": datetime.now(UTC) + timedelta(minutes=10),
        },
    )
    google(lambda request: httpx.Response(200, json={"access_token": "never-read", "id_token": _id_token()}))

    response = client.get("/api/auth/google/callback", params={"code": "google-code", "state": "server-state"})

    location = response.headers["location"]
    assert location.startswith(CLIENT_REDIRECT + "?app=claude&code=")
    assert "state=" not in location
