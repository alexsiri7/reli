"""The authorization server at /oauth/* and /.well-known/*: discovery, registration, PKCE, tokens.

Built onto a fresh ``FastAPI()`` with ``auth.router`` and ``mcp_oauth.router``, ``auth._session``
(the one session both routers run in) bound to the fixture session, and the Basic check applied — so
every request below also proves the exemption. Google is ``httpx.MockTransport`` throughout; nothing opens a socket.

The two racing tests use ``racing_client`` instead, which leaves ``auth._session`` opening one
session per request: a single connection cannot race itself.
"""

import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlmodel import Session, select

from backend import api, auth, google_login, mcp_oauth
from backend.config import settings
from backend.db_engine import get_engine
from backend.google_login import s256_challenge
from backend.oauth_state import (
    McpRefreshTokenRecord,
    cleanup_and_get,
    cleanup_and_store,
    mcp_auth_codes,
    mcp_oauth_sessions,
    mcp_refresh_tokens,
)

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
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(mcp_oauth.router)
    api.add_web_view_auth(app)
    return TestClient(app, follow_redirects=False)


@pytest.fixture()
def racing_client(session, sign_in_settings):
    """The same app on the production ``auth._session``, so two requests run on two connections."""
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(mcp_oauth.router)
    api.add_web_view_auth(app)
    return TestClient(app, follow_redirects=False)


def _racing_peek(monkeypatch, store):
    """Hold both racing requests after they have peeked *store*, so both reach the consume together.

    Only the peek of *store* waits: ``_validate_client_secret`` peeks the client store on the same
    path, and an unconditional barrier would fire twice per request. Returns the function that
    puts the real peek back, for a request after the race.
    """
    barrier = threading.Barrier(2, timeout=5)
    real_peek = mcp_oauth.cleanup_and_get

    def peek_then_wait(session, peeked, key):
        found = real_peek(session, peeked, key)
        if peeked is store:
            barrier.wait()
        return found

    monkeypatch.setattr(mcp_oauth, "cleanup_and_get", peek_then_wait)
    return lambda: monkeypatch.setattr(mcp_oauth, "cleanup_and_get", real_peek)


def _race(client, requests):
    with ThreadPoolExecutor(len(requests)) as pool:
        return list(pool.map(lambda send: send(client), requests))


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
    assert server["token_endpoint_auth_methods_supported"] == ["none", "client_secret_post"]


def test_the_metadata_documents_use_reli_base_url_when_set(client, monkeypatch):
    monkeypatch.setattr(settings, "RELI_BASE_URL", "https://other.example.test/")

    assert client.get("/.well-known/oauth-authorization-server").json()["issuer"] == "https://other.example.test"


def test_discovery_and_registration_answer_without_any_credential(session, monkeypatch, sign_in_settings):
    """The exemption from the Basic check, on a client that carries no header at all."""

    @contextmanager
    def _fixture_session():
        yield session

    monkeypatch.setattr(auth, "_session", _fixture_session)
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


@pytest.mark.parametrize("auth_method", ["none", "client_secret_post"])
def test_register_echoes_an_auth_method_the_token_endpoint_implements(client, auth_method):
    body = _register(client, auth_method=auth_method)

    assert body["token_endpoint_auth_method"] == auth_method


def test_register_refuses_an_auth_method_the_token_endpoint_does_not_implement(client):
    """A client told to authenticate with HTTP Basic would fail every exchange; refuse it up front."""
    response = client.post(
        "/oauth/register",
        json={"redirect_uris": [CLIENT_REDIRECT], "token_endpoint_auth_method": "client_secret_basic"},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "token_endpoint_auth_method" in detail
    assert "client_secret_basic" in detail
    assert "client_secret_post" in detail


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


def test_a_code_is_bound_to_the_redirect_uri_it_was_authorised_with(client, session):
    registered = _register(client, redirect_uris=(CLIENT_REDIRECT, "https://client.example.test/other"))
    code = _seed_code(session, registered["client_id"], "verifier", redirect_uri=CLIENT_REDIRECT)

    response = _token(
        client,
        code=code,
        client_id=registered["client_id"],
        code_verifier="verifier",
        redirect_uri="https://client.example.test/other",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"
    assert "redirect_uri" in response.json()["error_description"]


def test_a_wrong_secret_does_not_consume_the_code(client, session):
    """The client is authenticated before its code is consumed: a typo costs one attempt, not a sign-in."""
    registered = _register(client, auth_method="client_secret_post")
    code = _seed_code(session, registered["client_id"], "verifier")

    wrong = _token(client, code=code, client_id=registered["client_id"], code_verifier="verifier", client_secret="no")
    assert wrong.status_code == 401
    assert wrong.json()["error"] == "invalid_client"

    right = _token(
        client,
        code=code,
        client_id=registered["client_id"],
        code_verifier="verifier",
        client_secret=registered["client_secret"],
    )
    assert right.status_code == 200, right.text


def test_a_wrong_secret_does_not_consume_the_refresh_token(client, session):
    registered = _register(client, auth_method="client_secret_post")
    code = _seed_code(session, registered["client_id"], "verifier")
    issued = _token(
        client,
        code=code,
        client_id=registered["client_id"],
        code_verifier="verifier",
        client_secret=registered["client_secret"],
    ).json()

    wrong = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": issued["refresh_token"],
            "client_id": registered["client_id"],
            "client_secret": "no",
        },
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"] == "invalid_client"

    right = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": issued["refresh_token"],
            "client_id": registered["client_id"],
            "client_secret": registered["client_secret"],
        },
    )
    assert right.status_code == 200, right.text
    assert right.json()["refresh_token"] != issued["refresh_token"]


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


def test_a_refresh_token_family_starts_at_the_code_exchange_and_survives_rotation(client, session):
    registered = _register(client)
    code = _seed_code(session, registered["client_id"], "verifier")
    first = _token(client, code=code, client_id=registered["client_id"], code_verifier="verifier").json()
    second = _refresh(client, first["refresh_token"], registered["client_id"]).json()

    consumed = cleanup_and_get(session, mcp_refresh_tokens, first["refresh_token"])
    live = cleanup_and_get(session, mcp_refresh_tokens, second["refresh_token"])

    assert consumed is not None and live is not None
    assert consumed["family_id"] == live["family_id"]
    assert consumed["consumed_at"] is not None
    assert live["consumed_at"] is None

    other_code = _seed_code(session, registered["client_id"], "verifier", code="other-code")
    other = _token(client, code=other_code, client_id=registered["client_id"], code_verifier="verifier").json()
    other_row = cleanup_and_get(session, mcp_refresh_tokens, other["refresh_token"])
    assert other_row is not None
    assert other_row["family_id"] != live["family_id"]


def test_a_replayed_refresh_token_revokes_its_whole_family(client, session):
    """OAuth 2.1 §4.3.1: a rotated-away token presented again means it leaked, and the live one may have too."""
    registered = _register(client)
    code = _seed_code(session, registered["client_id"], "verifier")
    first = _token(client, code=code, client_id=registered["client_id"], code_verifier="verifier").json()
    second = _refresh(client, first["refresh_token"], registered["client_id"]).json()
    third = _refresh(client, second["refresh_token"], registered["client_id"]).json()

    replay = _refresh(client, first["refresh_token"], registered["client_id"])

    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"
    assert "re-authorise" in replay.json()["error_description"]
    live = _refresh(client, third["refresh_token"], registered["client_id"])
    assert live.status_code == 400
    assert live.json()["error"] == "invalid_grant"
    for issued in (first, second, third):
        assert cleanup_and_get(session, mcp_refresh_tokens, issued["refresh_token"]) is None
    with Session(get_engine()) as own:
        assert own.exec(select(func.count()).select_from(McpRefreshTokenRecord)).one() == 0


def test_two_concurrent_redeems_of_one_code_yield_exactly_one_token(racing_client, session, monkeypatch):
    registered = _register(racing_client)
    code = _seed_code(session, registered["client_id"], "verifier")
    _racing_peek(monkeypatch, mcp_auth_codes)

    def redeem(client):
        return _token(client, code=code, client_id=registered["client_id"], code_verifier="verifier")

    responses = _race(racing_client, [redeem, redeem])

    assert sorted(response.status_code for response in responses) == [200, 400]
    lost = next(response for response in responses if response.status_code == 400)
    assert lost.json()["error"] == "invalid_grant"


def test_two_concurrent_redeems_of_one_refresh_token_yield_one_token_and_revoke_the_family(
    racing_client, session, monkeypatch
):
    """The loser's revocation must reach the winner's replacement, which the one-transaction rotation guarantees."""
    registered = _register(racing_client)
    code = _seed_code(session, registered["client_id"], "verifier")
    first = _token(racing_client, code=code, client_id=registered["client_id"], code_verifier="verifier").json()
    stop_racing = _racing_peek(monkeypatch, mcp_refresh_tokens)

    def rotate(client):
        return _refresh(client, first["refresh_token"], registered["client_id"])

    responses = _race(racing_client, [rotate, rotate])

    assert sorted(response.status_code for response in responses) == [200, 400]
    won = next(response for response in responses if response.status_code == 200)
    stop_racing()
    revoked = _refresh(racing_client, won.json()["refresh_token"], registered["client_id"])
    assert revoked.status_code == 400
    assert revoked.json()["error"] == "invalid_grant"


def test_a_refresh_token_is_bound_to_the_client_it_was_issued_to(client, session):
    owner = _register(client)
    other = _register(client)
    code = _seed_code(session, owner["client_id"], "verifier")
    issued = _token(client, code=code, client_id=owner["client_id"], code_verifier="verifier").json()

    response = _refresh(client, issued["refresh_token"], other["client_id"])

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"
    assert "client_id" in response.json()["error_description"]
    # The refused attempt did not consume it: the owner still holds a live refresh token.
    assert _refresh(client, issued["refresh_token"], owner["client_id"]).status_code == 200


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
