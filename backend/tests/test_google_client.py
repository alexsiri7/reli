"""The Google credential seam: what it refreshes, what it retries, and what it never leaks.

Every request goes through ``httpx.MockTransport``, so nothing here opens a socket. The client is
built fresh per call by ``google_client._http_client``, which is what the ``transport`` fixture
replaces.
"""

import httpx
import pytest

from backend import google_client
from backend.config import settings
from backend.google_client import (
    TOKEN_URL,
    GoogleApiError,
    GoogleAuthFailed,
    GoogleNotConfigured,
    get_json,
)

API_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"

CLIENT_SECRET = "s3cret-client-secret"
REFRESH_TOKEN = "s3cret-refresh-token"


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setattr(settings, "GOOGLE_REFRESH_TOKEN", REFRESH_TOKEN)


@pytest.fixture(autouse=True)
def clean_token_cache():
    google_client.reset_token_cache()
    yield
    google_client.reset_token_cache()


@pytest.fixture()
def transport(monkeypatch):
    """Install a handler and collect every request it saw."""
    seen: list[httpx.Request] = []

    def install(handler):
        def recording(request):
            seen.append(request)
            return handler(request)

        monkeypatch.setattr(
            google_client, "_http_client", lambda: httpx.Client(transport=httpx.MockTransport(recording))
        )
        return seen

    return install


def _token_response(access_token="access-token-1", expires_in=3600):
    return httpx.Response(200, json={"access_token": access_token, "expires_in": expires_in, "token_type": "Bearer"})


def _token_requests(seen):
    return [request for request in seen if str(request.url) == TOKEN_URL]


def test_an_unconfigured_reli_names_all_three_settings(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "")
    monkeypatch.setattr(settings, "GOOGLE_REFRESH_TOKEN", "")

    with pytest.raises(GoogleNotConfigured) as raised:
        get_json(API_URL, {})

    message = str(raised.value)
    assert "GOOGLE_CLIENT_ID" in message
    assert "GOOGLE_CLIENT_SECRET" in message
    assert "GOOGLE_REFRESH_TOKEN" in message
    assert "scripts/google_oauth_grant.py" in message


def test_a_partial_credential_is_not_configured(configured, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_REFRESH_TOKEN", "")

    assert google_client.is_configured() is False
    with pytest.raises(GoogleNotConfigured):
        get_json(API_URL, {})


def test_the_first_read_refreshes_and_carries_the_bearer_token(configured, transport):
    def handler(request):
        if str(request.url) == TOKEN_URL:
            return _token_response()
        return httpx.Response(200, json={"messages": []})

    seen = transport(handler)

    assert get_json(API_URL, {"q": "invoice"}) == {"messages": []}
    assert len(_token_requests(seen)) == 1
    assert seen[-1].headers["Authorization"] == "Bearer access-token-1"


def test_a_cached_token_is_reused_for_the_next_read(configured, transport):
    def handler(request):
        if str(request.url) == TOKEN_URL:
            return _token_response()
        return httpx.Response(200, json={"ok": True})

    seen = transport(handler)

    get_json(API_URL, {})
    get_json(API_URL, {})

    assert len(_token_requests(seen)) == 1


def test_a_token_inside_the_skew_margin_is_refreshed(configured, transport):
    """30 seconds of life left is not enough: the read would race the expiry."""

    def handler(request):
        if str(request.url) == TOKEN_URL:
            return _token_response(expires_in=30)
        return httpx.Response(200, json={"ok": True})

    seen = transport(handler)

    get_json(API_URL, {})
    get_json(API_URL, {})

    assert len(_token_requests(seen)) == 2


def test_a_token_outside_the_skew_margin_is_kept(configured, transport):
    def handler(request):
        if str(request.url) == TOKEN_URL:
            return _token_response(expires_in=600)
        return httpx.Response(200, json={"ok": True})

    seen = transport(handler)

    get_json(API_URL, {})
    get_json(API_URL, {})

    assert len(_token_requests(seen)) == 1


def test_a_401_costs_one_refresh_and_one_retry(configured, transport):
    tokens = iter(["stale-token", "fresh-token"])

    def handler(request):
        if str(request.url) == TOKEN_URL:
            return _token_response(access_token=next(tokens))
        if request.headers["Authorization"] == "Bearer stale-token":
            return httpx.Response(401, json={"error": "unauthorized"})
        return httpx.Response(200, json={"ok": True})

    seen = transport(handler)

    assert get_json(API_URL, {}) == {"ok": True}
    assert len(_token_requests(seen)) == 2
    assert seen[-1].headers["Authorization"] == "Bearer fresh-token"


def test_two_consecutive_401s_raise(configured, transport):
    def handler(request):
        if str(request.url) == TOKEN_URL:
            return _token_response()
        return httpx.Response(401, json={"error": "unauthorized"})

    seen = transport(handler)

    with pytest.raises(GoogleAuthFailed):
        get_json(API_URL, {})

    assert len(_token_requests(seen)) == 2


def test_an_invalid_grant_names_the_command_a_human_must_run(configured, transport):
    def handler(request):
        return httpx.Response(400, json={"error": "invalid_grant"})

    transport(handler)

    with pytest.raises(GoogleAuthFailed) as raised:
        get_json(API_URL, {})

    assert "scripts/google_oauth_grant.py" in str(raised.value)
    assert "GOOGLE_REFRESH_TOKEN" in str(raised.value)


def test_an_api_error_leaks_neither_the_access_token_nor_the_client_secret(configured, transport):
    def handler(request):
        if str(request.url) == TOKEN_URL:
            return _token_response(access_token="super-secret-access-token")
        return httpx.Response(500, json={"error": {"message": "backend error"}})

    transport(handler)

    with pytest.raises(GoogleApiError) as raised:
        get_json(API_URL, {"q": "invoice"})

    message = str(raised.value)
    assert "500" in message
    assert "super-secret-access-token" not in message
    assert CLIENT_SECRET not in message


def test_a_refused_refresh_leaks_neither_the_client_secret_nor_the_refresh_token(configured, transport):
    """The refresh POST is the one request that carries both secrets, and its generic failure
    branch echoes Google's answer — so it must echo `error` and nothing else Google sent back."""

    def handler(request):
        return httpx.Response(
            400,
            json={
                "error": "unauthorized_client",
                "error_description": f"client_secret={CLIENT_SECRET} refresh_token={REFRESH_TOKEN}",
            },
        )

    transport(handler)

    with pytest.raises(GoogleAuthFailed) as raised:
        get_json(API_URL, {"q": "invoice"})

    message = str(raised.value)
    assert "400" in message
    assert "unauthorized_client" in message
    assert "invalid_grant" not in message
    assert CLIENT_SECRET not in message
    assert REFRESH_TOKEN not in message
