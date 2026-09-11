"""The JWTs Reli mints, Google's callback and the web session: who gets in, who is turned away, what is logged.

The router is built onto a fresh ``FastAPI()`` with ``auth._session`` bound to the fixture session
and the web view's check applied, so the tests also prove ``/api/auth/`` is exempt from it — without
the exemption every request below would be 401. Google is ``httpx.MockTransport`` throughout.
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
from backend.oauth_state import (
    cleanup_and_get,
    cleanup_and_store,
    mcp_auth_codes,
    mcp_oauth_sessions,
    web_oauth_sessions,
)

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
        "a-google-key-whose-signature-is-never-checked",
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


def _seed_web_flow(session, state="web-state"):
    cleanup_and_store(
        session,
        web_oauth_sessions,
        state,
        {"google_code_verifier": "verifier", "expires_at": datetime.now(UTC) + timedelta(minutes=10)},
    )


def _location_query(response, base=CLIENT_REDIRECT):
    location = response.headers["location"]
    assert location.startswith(base + "?")
    return {key: values[0] for key, values in parse_qs(urlsplit(location).query).items()}


def _session_cookie(response):
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(auth.SESSION_COOKIE + "=")
    return cookie


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


def test_an_unknown_state_is_400_and_the_callback_is_exempt_from_the_web_view_check(client, google):
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


# --- The web view's sign-in ---------------------------------------------------


def test_starting_a_web_sign_in_remembers_the_verifier_and_points_at_google(client, session):
    response = client.get("/api/auth/google")

    assert response.status_code == 200
    auth_url = response.json()["auth_url"]
    assert auth_url.startswith(google_login.AUTHORIZATION_URL + "?")
    query = {key: values[0] for key, values in parse_qs(urlsplit(auth_url).query).items()}
    assert query["code_challenge_method"] == "S256"
    stored = cleanup_and_get(session, web_oauth_sessions, query["state"])
    assert stored is not None
    assert google_login.s256_challenge(stored["google_code_verifier"]) == query["code_challenge"]


def test_starting_a_web_sign_in_refuses_up_front_naming_each_missing_setting(client, monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "")

    response = client.get("/api/auth/google")

    assert response.status_code == 501
    assert "GOOGLE_CLIENT_SECRET, ALLOWED_EMAILS" in response.json()["detail"]
    assert "CLAUDE.md" in response.json()["detail"]


def test_a_good_web_sign_in_sets_the_session_cookie_and_lands_on_the_view(client, session, google, caplog):
    _seed_web_flow(session)
    google(lambda request: httpx.Response(200, json={"access_token": "never-read", "id_token": _id_token()}))

    with caplog.at_level(logging.DEBUG):
        response = client.get("/api/auth/google/callback", params={"code": "google-code", "state": "web-state"})

    assert response.status_code == 302
    assert response.headers["location"] == "/"
    cookie = _session_cookie(response)
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
    assert f"Max-Age={auth.JWT_EXPIRY_SECONDS}" in cookie
    token = cookie.split(";")[0].split("=", 1)[1]
    claims = auth.decode_jwt(token, audience=auth.WEB_AUDIENCE)
    assert claims["email"] == "owner@example.com"
    assert token not in caplog.text
    assert cleanup_and_get(session, web_oauth_sessions, "web-state") is None


def test_the_cookie_is_not_marked_secure_for_a_plain_http_deploy(client, session, google, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_AUTH_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")
    _seed_web_flow(session)
    google(lambda request: httpx.Response(200, json={"access_token": "never-read", "id_token": _id_token()}))

    response = client.get("/api/auth/google/callback", params={"code": "google-code", "state": "web-state"})

    assert "Secure" not in _session_cookie(response)


def test_a_web_account_outside_the_allowlist_is_sent_to_the_view_as_invite_only(client, session, google, caplog):
    _seed_web_flow(session)
    google(
        lambda request: httpx.Response(
            200, json={"access_token": "never-read", "id_token": _id_token(email="intruder@example.com")}
        )
    )

    with caplog.at_level(logging.DEBUG):
        response = client.get("/api/auth/google/callback", params={"code": "google-code", "state": "web-state"})

    assert response.status_code == 302
    assert response.headers["location"] == "/?error=invite_only"
    assert "set-cookie" not in response.headers
    assert "intruder@example.com" not in caplog.text


def test_a_cancelled_web_sign_in_is_sent_to_the_view_without_an_exchange(client, session, google):
    _seed_web_flow(session)
    seen = google(lambda request: httpx.Response(500))

    response = client.get("/api/auth/google/callback", params={"error": "access_denied", "state": "web-state"})

    assert response.status_code == 302
    assert response.headers["location"] == "/?error=cancelled"
    assert seen == []


def test_a_google_refusal_of_a_web_sign_in_is_502_naming_the_remedy(client, session, google):
    _seed_web_flow(session)
    google(lambda request: httpx.Response(400, json={"error": "invalid_grant"}))

    response = client.get("/api/auth/google/callback", params={"code": "google-code", "state": "web-state"})

    assert response.status_code == 502
    assert "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET" in response.json()["detail"]


def test_me_answers_the_cookie_and_401_with_the_remedy_without_one(client):
    token = auth.create_jwt("1234567890", "owner@example.com", audience=auth.WEB_AUDIENCE)

    assert client.get("/api/auth/me", headers={"Cookie": f"{auth.SESSION_COOKIE}={token}"}).json() == {
        "email": "owner@example.com"
    }

    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not signed in: sign in with Google at /."


def test_me_refuses_an_mcp_token_as_a_web_session(client):
    token = auth.create_jwt("1234567890", "owner@example.com", audience=auth.MCP_AUDIENCE)

    response = client.get("/api/auth/me", headers={"Cookie": f"{auth.SESSION_COOKIE}={token}"})

    assert response.status_code == 401
    assert "sign in with Google" in response.json()["detail"]


def test_logout_deletes_the_cookie(client):
    response = client.post("/api/auth/logout")

    assert response.status_code == 204
    cookie = _session_cookie(response)
    assert 'reli_session=""' in cookie
    assert "Max-Age=0" in cookie
