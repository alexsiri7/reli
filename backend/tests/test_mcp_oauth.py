"""The authorization server at /oauth/* and /.well-known/*: discovery, registration, PKCE, tokens.

Built onto a fresh ``FastAPI()`` with ``auth.router`` and ``mcp_oauth.router``, both sessions bound
to the fixture session, and the Basic check applied — so every request below also proves the
exemption. Google is ``httpx.MockTransport`` throughout; nothing opens a socket.
"""

import secrets
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import api, auth, google_login, mcp_oauth
from backend.config import settings
from backend.google_login import s256_challenge
from backend.oauth_state import cleanup_and_get, cleanup_and_store, mcp_auth_codes, mcp_oauth_sessions

SECRET_KEY = "a-test-secret-key-that-is-forty-eight-chars-long"
CLIENT_ID = "client-id.apps.googleusercontent.com"
BASE_URL = "https://reli.example.test"
CLIENT_REDIRECT = "https://client.example.test/callback"


@pytest.fixture()
def sign_in_settings(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET_KEY)
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "owner@example.com")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "s3cret-client-secret")
    monkeypatch.setattr(settings, "GOOGLE_AUTH_REDIRECT_URI", f"{BASE_URL}/api/auth/google/callback")
    monkeypatch.setattr(settings, "RELI_BASE_URL", "")
    monkeypatch.setattr(settings, "WEB_UI_PASSWORD", "web-password")


@pytest.fixture()
def client(session, monkeypatch, sign_in_settings):
    @contextmanager
    def _fixture_session():
        yield session

    monkeypatch.setattr(auth, "_session", _fixture_session)
    monkeypatch.setattr(mcp_oauth, "_session", _fixture_session)
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(mcp_oauth.router)
    api.add_web_view_auth(app)
    return TestClient(app, follow_redirects=False)


def _register(client, auth_method="none", redirect_uris=(CLIENT_REDIRECT,)):
    response = client.post(
        "/oauth/register",
        json={"redirect_uris": list(redirect_uris), "client_name": "Claude", "token_endpoint_auth_method": auth_method},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _seed_code(session, client_id, verifier, code="auth-code", redirect_uri=CLIENT_REDIRECT):
    cleanup_and_store(
        session,
        mcp_auth_codes,
        code,
        {
            "subject": "1234567890",
            "email": "owner@example.com",
            "code_challenge": s256_challenge(verifier),
            "code_challenge_method": "S256",
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "scope": "mcp",
            "expires_at": datetime.now(UTC) + timedelta(seconds=60),
        },
    )
    return code


def _token(client, **form):
    form = {"grant_type": "authorization_code", "redirect_uri": CLIENT_REDIRECT, **form}
    return client.post("/oauth/token", data=form)


def _refresh(client, refresh_token, client_id):
    return client.post(
        "/oauth/token", data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id}
    )


def _query(url):
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


# --- Discovery ---------------------------------------------------------------


def test_the_metadata_documents_derive_the_base_from_the_redirect_uri(client):
    resource = client.get("/.well-known/oauth-protected-resource").json()
    server = client.get("/.well-known/oauth-authorization-server").json()

    assert resource == {
        "resource": f"{BASE_URL}/mcp/",
        "authorization_servers": [BASE_URL],
        "scopes_supported": ["mcp"],
    }
    assert server["issuer"] == BASE_URL
    assert server["authorization_endpoint"] == f"{BASE_URL}/oauth/authorize"
    assert server["token_endpoint"] == f"{BASE_URL}/oauth/token"
    assert server["registration_endpoint"] == f"{BASE_URL}/oauth/register"
    assert server["code_challenge_methods_supported"] == ["S256"]
    assert server["grant_types_supported"] == ["authorization_code", "refresh_token"]


def test_the_metadata_documents_use_reli_base_url_when_set(client, monkeypatch):
    monkeypatch.setattr(settings, "RELI_BASE_URL", "https://other.example.test/")

    assert client.get("/.well-known/oauth-authorization-server").json()["issuer"] == "https://other.example.test"


def test_discovery_and_registration_answer_without_any_credential(session, monkeypatch, sign_in_settings):
    """The exemption from the Basic check, on a client that carries no header at all."""

    @contextmanager
    def _fixture_session():
        yield session

    monkeypatch.setattr(mcp_oauth, "_session", _fixture_session)
    app = FastAPI()
    app.include_router(mcp_oauth.router)
    api.add_web_view_auth(app)
    anonymous = TestClient(app)

    assert anonymous.get("/.well-known/oauth-authorization-server").status_code == 200
    assert anonymous.post("/oauth/register", json={"redirect_uris": [CLIENT_REDIRECT]}).status_code == 201


# --- Registration ------------------------------------------------------------


@pytest.mark.parametrize(
    "redirect_uris",
    [[CLIENT_REDIRECT], ["http://localhost:3000/cb"], ["http://127.0.0.1:3000/cb"], [], None],
    ids=["https", "localhost", "loopback", "empty", "null"],
)
def test_register_accepts_https_and_loopback_redirects(client, redirect_uris):
    response = client.post("/oauth/register", json={"redirect_uris": redirect_uris, "client_name": "Claude"})

    assert response.status_code == 201
    body = response.json()
    assert body["redirect_uris"] == (redirect_uris or [])
    assert body["client_name"] == "Claude"
    assert body["client_secret"]
    assert body["token_endpoint_auth_method"] == "client_secret_post"
    assert body["client_secret_expires_at"] > datetime.now(UTC).timestamp()


@pytest.mark.parametrize(
    "redirect_uris",
    [["http://evil.com/cb"], ["javascript:alert(1)"], ["not-a-url"], [CLIENT_REDIRECT, "http://evil.com/cb"]],
    ids=["http-remote", "javascript", "schemeless", "mixed"],
)
def test_register_refuses_an_unsafe_redirect_whatever_its_position(client, redirect_uris):
    response = client.post("/oauth/register", json={"redirect_uris": redirect_uris})

    assert response.status_code == 400
    assert "redirect_uri must use https" in response.json()["detail"]


# --- Authorization -----------------------------------------------------------


def test_authorize_refuses_up_front_naming_each_missing_setting(client, monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "")
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "")

    response = client.get("/oauth/authorize", params={"client_id": "x", "redirect_uri": CLIENT_REDIRECT})

    assert response.status_code == 501
    detail = response.json()["detail"]
    assert "SECRET_KEY" in detail
    assert "ALLOWED_EMAILS" in detail
    assert "GOOGLE_CLIENT_ID" not in detail


def test_authorize_sends_the_browser_to_google_and_remembers_the_request(client, session):
    registered = _register(client)

    response = client.get(
        "/oauth/authorize",
        params={
            "client_id": registered["client_id"],
            "redirect_uri": CLIENT_REDIRECT,
            "state": "client-state",
            "code_challenge": "client-challenge",
            "code_challenge_method": "S256",
        },
    )

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(google_login.AUTHORIZATION_URL)
    query = _query(location)
    flow = cleanup_and_get(session, mcp_oauth_sessions, query["state"])
    assert flow is not None
    assert flow["client_state"] == "client-state"
    assert flow["client_id"] == registered["client_id"]
    assert flow["code_challenge"] == "client-challenge"
    assert query["code_challenge"] == s256_challenge(flow["google_code_verifier"])
    assert query["redirect_uri"] == settings.GOOGLE_AUTH_REDIRECT_URI


def test_authorize_refuses_an_unregistered_client(client):
    response = client.get(
        "/oauth/authorize", params={"client_id": "nobody", "redirect_uri": CLIENT_REDIRECT, "code_challenge": "c"}
    )

    assert response.status_code == 400
    assert "register first" in response.json()["detail"]


def test_authorize_refuses_a_redirect_uri_the_client_did_not_register(client):
    registered = _register(client)

    response = client.get(
        "/oauth/authorize",
        params={
            "client_id": registered["client_id"],
            "redirect_uri": "https://elsewhere.example.test/cb",
            "code_challenge": "c",
        },
    )

    assert response.status_code == 400
    assert "not registered" in response.json()["detail"]


@pytest.mark.parametrize(
    "override",
    [{"response_type": "token"}, {"code_challenge_method": "plain"}, {"code_challenge": ""}, {"redirect_uri": ""}],
    ids=["response-type", "plain-pkce", "no-challenge", "no-redirect"],
)
def test_authorize_insists_on_code_and_s256(client, override):
    registered = _register(client)
    params = {"client_id": registered["client_id"], "redirect_uri": CLIENT_REDIRECT, "code_challenge": "c", **override}

    assert client.get("/oauth/authorize", params=params).status_code == 400


# --- Tokens ------------------------------------------------------------------


def test_a_code_exchanges_for_a_jwt_the_mcp_endpoint_accepts(client, session):
    registered = _register(client)
    verifier = secrets.token_urlsafe(64)
    code = _seed_code(session, registered["client_id"], verifier)

    response = _token(client, code=code, client_id=registered["client_id"], code_verifier=verifier)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 604800
    assert body["refresh_token"]
    claims = auth.decode_jwt(body["access_token"], audience="mcp")
    assert claims["sub"] == "1234567890"
    assert claims["email"] == "owner@example.com"


def test_a_code_exchanges_once(client, session):
    registered = _register(client)
    verifier = secrets.token_urlsafe(64)
    code = _seed_code(session, registered["client_id"], verifier)
    assert _token(client, code=code, client_id=registered["client_id"], code_verifier=verifier).status_code == 200

    response = _token(client, code=code, client_id=registered["client_id"], code_verifier=verifier)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"
    assert "re-authorise" in response.json()["error_description"]


def test_a_wrong_verifier_fails_pkce(client, session):
    registered = _register(client)
    code = _seed_code(session, registered["client_id"], "the-right-verifier")

    response = _token(client, code=code, client_id=registered["client_id"], code_verifier="the-wrong-verifier")

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"
    assert "PKCE" in response.json()["error_description"]


def test_a_code_is_bound_to_the_client_it_was_minted_for(client, session):
    owner = _register(client)
    other = _register(client)
    code = _seed_code(session, owner["client_id"], "verifier")

    response = _token(client, code=code, client_id=other["client_id"], code_verifier="verifier")

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_an_unsupported_grant_type_is_named(client):
    response = client.post("/oauth/token", data={"grant_type": "password"})

    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"


def test_a_confidential_client_must_present_its_secret(client, session):
    registered = _register(client, auth_method="client_secret_post")
    code = _seed_code(session, registered["client_id"], "verifier")

    wrong = _token(client, code=code, client_id=registered["client_id"], code_verifier="verifier", client_secret="no")
    assert wrong.status_code == 401
    assert wrong.json()["error"] == "invalid_client"

    code = _seed_code(session, registered["client_id"], "verifier", code="second-code")
    right = _token(
        client,
        code=code,
        client_id=registered["client_id"],
        code_verifier="verifier",
        client_secret=registered["client_secret"],
    )
    assert right.status_code == 200


def test_a_refresh_token_rotates(client, session):
    registered = _register(client)
    code = _seed_code(session, registered["client_id"], "verifier")
    first = _token(client, code=code, client_id=registered["client_id"], code_verifier="verifier").json()

    response = _refresh(client, first["refresh_token"], registered["client_id"])

    assert response.status_code == 200
    second = response.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert auth.decode_jwt(second["access_token"], audience="mcp")["sub"] == "1234567890"

    replay = _refresh(client, first["refresh_token"], registered["client_id"])
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"


# --- The bare /mcp path ------------------------------------------------------


def test_bare_mcp_redirects_to_the_slash_path_from_the_configured_base(client, monkeypatch):
    monkeypatch.setattr(settings, "RELI_BASE_URL", "")
    monkeypatch.setattr(settings, "GOOGLE_AUTH_REDIRECT_URI", "")
    unconfigured = client.post("/mcp")
    assert unconfigured.status_code == 307
    assert unconfigured.headers["location"] == "/mcp/"

    monkeypatch.setattr(settings, "RELI_BASE_URL", BASE_URL)
    configured = client.post("/mcp")
    assert configured.headers["location"] == f"{BASE_URL}/mcp/"


# --- End to end --------------------------------------------------------------


def _google_token_response(request):
    id_token = jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": CLIENT_ID,
            "sub": "1234567890",
            "email": "Owner@Example.com",
            "email_verified": True,
            "exp": datetime.now(UTC) + timedelta(seconds=300),
        },
        "a-google-key-whose-signature-is-never-checked",
        algorithm="HS256",
    )
    return httpx.Response(200, json={"access_token": "never-read", "id_token": id_token})


def test_register_authorize_callback_and_token_end_to_end(client, monkeypatch):
    monkeypatch.setattr(
        google_login, "_http_client", lambda: httpx.Client(transport=httpx.MockTransport(_google_token_response))
    )
    registered = _register(client)
    verifier = secrets.token_urlsafe(64)

    to_google = client.get(
        "/oauth/authorize",
        params={
            "client_id": registered["client_id"],
            "redirect_uri": CLIENT_REDIRECT,
            "state": "client-state",
            "code_challenge": s256_challenge(verifier),
            "code_challenge_method": "S256",
        },
    )
    server_state = _query(to_google.headers["location"])["state"]

    back_from_google = client.get("/api/auth/google/callback", params={"code": "google-code", "state": server_state})
    assert back_from_google.status_code == 302
    to_client = _query(back_from_google.headers["location"])
    assert to_client["state"] == "client-state"

    tokens = _token(client, code=to_client["code"], client_id=registered["client_id"], code_verifier=verifier)

    assert tokens.status_code == 200, tokens.text
    claims = auth.decode_jwt(tokens.json()["access_token"], audience="mcp")
    assert claims["email"] == "owner@example.com"
    assert claims["aud"] == "mcp"
