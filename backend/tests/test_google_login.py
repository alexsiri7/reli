"""The Google sign-in seam: the URL it sends the browser to, and what it makes of the code that comes back.

Every request goes through ``httpx.MockTransport`` on ``google_login._http_client``, so nothing
here opens a socket.
"""

import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest

from backend import google_login
from backend.config import settings
from backend.google_login import (
    TOKEN_URL,
    GoogleSignInFailed,
    authorization_url,
    exchange_code,
    s256_challenge,
)

CLIENT_ID = "client-id.apps.googleusercontent.com"
CLIENT_SECRET = "s3cret-client-secret"
REDIRECT_URI = "https://reli.example.test/api/auth/google/callback"


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setattr(settings, "GOOGLE_AUTH_REDIRECT_URI", REDIRECT_URI)


@pytest.fixture()
def transport(monkeypatch):
    """Install a handler and collect every request it saw."""
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


def _id_token(**claims):
    """A Google-shaped id token. The signature is never checked, so any key will do."""
    payload = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": "Owner@Example.com",
        "email_verified": True,
        "exp": datetime.now(UTC) + timedelta(seconds=300),
        **claims,
    }
    return jwt.encode(payload, "any-key-signature-is-not-checked", algorithm="HS256")


def _token_response(**claims):
    return httpx.Response(200, json={"access_token": "never-read", "id_token": _id_token(**claims)})


def test_the_authorization_url_carries_the_challenge_the_scopes_and_the_state():
    url = authorization_url("server-state", "verifier-value")

    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == google_login.AUTHORIZATION_URL
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == REDIRECT_URI
    assert query["response_type"] == "code"
    assert query["scope"] == "openid email profile"
    assert query["state"] == "server-state"
    assert query["code_challenge"] == s256_challenge("verifier-value")
    assert query["code_challenge_method"] == "S256"
    assert query["prompt"] == "select_account"
    assert "access_type" not in query


def test_a_good_exchange_returns_the_identity_with_the_email_lower_cased(transport):
    seen = transport(lambda request: _token_response())

    identity = exchange_code("the-code", "the-verifier")

    assert identity.subject == "1234567890"
    assert identity.email == "owner@example.com"
    [request] = seen
    assert str(request.url) == TOKEN_URL
    form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "the-code"
    assert form["code_verifier"] == "the-verifier"
    assert form["redirect_uri"] == REDIRECT_URI


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "someone-else.apps.googleusercontent.com"},
        {"iss": "https://accounts.example.com"},
        {"exp": datetime.now(UTC) - timedelta(seconds=1)},
        {"email_verified": False},
    ],
    ids=["wrong-audience", "wrong-issuer", "expired", "unverified-email"],
)
def test_an_id_token_whose_claims_do_not_hold_is_refused(transport, claims):
    transport(lambda request: _token_response(**claims))

    with pytest.raises(GoogleSignInFailed):
        exchange_code("the-code", "the-verifier")


def test_a_response_without_an_id_token_is_refused(transport):
    transport(lambda request: httpx.Response(200, json={"access_token": "only"}))

    with pytest.raises(GoogleSignInFailed, match="id_token"):
        exchange_code("the-code", "the-verifier")


def test_a_redirect_uri_mismatch_names_the_console_and_the_uri(transport):
    transport(lambda request: httpx.Response(400, json={"error": "redirect_uri_mismatch"}))

    with pytest.raises(GoogleSignInFailed) as raised:
        exchange_code("the-code", "the-verifier")

    message = str(raised.value)
    assert "Google Cloud console" in message
    assert REDIRECT_URI in message


def test_an_invalid_grant_says_to_start_again_and_names_the_client_settings(transport):
    transport(lambda request: httpx.Response(400, json={"error": "invalid_grant"}))

    with pytest.raises(GoogleSignInFailed) as raised:
        exchange_code("the-code", "the-verifier")

    message = str(raised.value)
    assert "start the sign-in again" in message
    assert "GOOGLE_CLIENT_SECRET" in message


def test_the_client_secret_never_appears_in_a_message_or_a_log(transport, caplog):
    transport(lambda request: httpx.Response(401, json={"error": "invalid_client"}))

    with caplog.at_level(logging.DEBUG), pytest.raises(GoogleSignInFailed) as raised:
        exchange_code("the-code", "the-verifier")

    assert CLIENT_SECRET not in str(raised.value)
    assert CLIENT_SECRET not in caplog.text
