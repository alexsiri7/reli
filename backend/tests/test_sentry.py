"""Tests for Sentry integration."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _clear_sentry_env(monkeypatch):
    """Ensure SENTRY_DSN is unset by default so tests don't send real events."""
    monkeypatch.setenv("SENTRY_DSN", "")


def test_init_sentry_noop_without_dsn():
    """init_sentry should be a no-op when SENTRY_DSN is empty."""
    with patch("backend.sentry.settings") as mock_settings:
        mock_settings.SENTRY_DSN = ""
        from backend.sentry import init_sentry

        # Should not raise
        init_sentry()


def test_init_sentry_calls_sdk_init():
    """init_sentry should call sentry_sdk.init when DSN is set."""
    with (
        patch("backend.sentry.settings") as mock_settings,
        patch("backend.sentry.sentry_sdk") as mock_sdk,
    ):
        mock_settings.SENTRY_DSN = "https://examplePublicKey@o0.ingest.sentry.io/0"
        mock_settings.SENTRY_ENVIRONMENT = "test"
        mock_settings.SENTRY_TRACES_SAMPLE_RATE = 0.1
        from backend.sentry import init_sentry

        init_sentry()
        mock_sdk.init.assert_called_once()
        call_kwargs = mock_sdk.init.call_args[1]
        assert call_kwargs["dsn"] == "https://examplePublicKey@o0.ingest.sentry.io/0"
        assert call_kwargs["environment"] == "test"
        assert call_kwargs["traces_sample_rate"] == 0.1


def test_set_sentry_user_noop_without_dsn():
    """set_sentry_user should be a no-op when SENTRY_DSN is empty."""
    with patch("backend.sentry.settings") as mock_settings:
        mock_settings.SENTRY_DSN = ""
        from backend.sentry import set_sentry_user

        # Should not raise or call sentry_sdk
        with patch("backend.sentry.sentry_sdk") as mock_sdk:
            set_sentry_user("user-123")
            mock_sdk.set_user.assert_not_called()


def test_set_sentry_user_sets_only_id():
    """set_sentry_user should set only opaque user ID — no email PII."""
    with (
        patch("backend.sentry.settings") as mock_settings,
        patch("backend.sentry.sentry_sdk") as mock_sdk,
    ):
        mock_settings.SENTRY_DSN = "https://examplePublicKey@o0.ingest.sentry.io/0"
        from backend.sentry import set_sentry_user

        set_sentry_user("user-123")
        mock_sdk.set_user.assert_called_once_with({"id": "user-123"})


@pytest.mark.parametrize("header_key", ["Cookie", "Set-Cookie", "cookie", "set-cookie"])
def test_strip_cookie_breadcrumb_filters_cookie_header(header_key):
    """_strip_cookie_breadcrumb should redact all cookie header name variants."""
    from backend.sentry import _strip_cookie_breadcrumb

    crumb = {"data": {header_key: "reli_session=supersecretjwt", "X-Other": "value"}}
    result = _strip_cookie_breadcrumb(crumb, None)
    assert result is not None
    assert result["data"][header_key] == "[Filtered]"
    assert result["data"]["X-Other"] == "value"


def test_strip_cookie_breadcrumb_no_data_key():
    """_strip_cookie_breadcrumb should handle breadcrumbs with no 'data' key."""
    from backend.sentry import _strip_cookie_breadcrumb

    crumb = {"type": "http", "category": "fetch"}
    result = _strip_cookie_breadcrumb(crumb, None)
    assert result == crumb


def test_strip_cookie_breadcrumb_data_is_none():
    """_strip_cookie_breadcrumb should handle breadcrumbs where data is None."""
    from backend.sentry import _strip_cookie_breadcrumb

    crumb = {"data": None}
    result = _strip_cookie_breadcrumb(crumb, None)
    assert result == crumb


def test_strip_cookie_breadcrumb_authorization_filtered():
    """_strip_cookie_breadcrumb should redact Authorization headers to prevent token leaks."""
    from backend.sentry import _strip_cookie_breadcrumb

    crumb = {"data": {"Authorization": "Bearer token", "Content-Type": "application/json"}}
    result = _strip_cookie_breadcrumb(crumb, None)
    assert result["data"]["Authorization"] == "[Filtered]"
    assert result["data"]["Content-Type"] == "application/json"


def test_init_sentry_sets_before_breadcrumb():
    """init_sentry should register _strip_cookie_breadcrumb as before_breadcrumb hook."""
    with (
        patch("backend.sentry.settings") as mock_settings,
        patch("backend.sentry.sentry_sdk") as mock_sdk,
    ):
        mock_settings.SENTRY_DSN = "https://examplePublicKey@o0.ingest.sentry.io/0"
        mock_settings.SENTRY_ENVIRONMENT = "test"
        mock_settings.SENTRY_TRACES_SAMPLE_RATE = 0.1
        from backend.sentry import _strip_cookie_breadcrumb, init_sentry

        init_sentry()
        call_kwargs = mock_sdk.init.call_args[1]
        assert call_kwargs.get("before_breadcrumb") is _strip_cookie_breadcrumb
        assert call_kwargs.get("send_default_pii") is False


def test_init_sentry_never_attaches_request_bodies_or_locals():
    """init_sentry must switch off body capture and frame locals: both can carry auth-flow secrets."""
    with (
        patch("backend.sentry.settings") as mock_settings,
        patch("backend.sentry.sentry_sdk") as mock_sdk,
    ):
        mock_settings.SENTRY_DSN = "https://examplePublicKey@o0.ingest.sentry.io/0"
        mock_settings.SENTRY_ENVIRONMENT = "test"
        mock_settings.SENTRY_TRACES_SAMPLE_RATE = 0.1
        from backend.sentry import init_sentry

        init_sentry()
        call_kwargs = mock_sdk.init.call_args[1]
        assert call_kwargs["max_request_body_size"] == "never"
        assert call_kwargs["include_local_variables"] is False


def test_init_sentry_sets_before_send_hooks():
    """init_sentry should scrub both error events and sampled transactions with the same hook."""
    with (
        patch("backend.sentry.settings") as mock_settings,
        patch("backend.sentry.sentry_sdk") as mock_sdk,
    ):
        mock_settings.SENTRY_DSN = "https://examplePublicKey@o0.ingest.sentry.io/0"
        mock_settings.SENTRY_ENVIRONMENT = "test"
        mock_settings.SENTRY_TRACES_SAMPLE_RATE = 0.1
        from backend.sentry import _strip_auth_flow_request, init_sentry

        init_sentry()
        call_kwargs = mock_sdk.init.call_args[1]
        assert call_kwargs.get("before_send") is _strip_auth_flow_request
        assert call_kwargs.get("before_send_transaction") is _strip_auth_flow_request


def _oauth_token_event(url: str) -> dict:
    return {
        "level": "error",
        "request": {
            "url": url,
            "method": "POST",
            "query_string": "trace=1",
            "headers": {"Host": "reli.example.com", "Content-Type": "application/x-www-form-urlencoded"},
            "cookies": {"reli_session": "supersecretjwt"},
            "data": {
                "grant_type": "refresh_token",
                "client_id": "client-1",
                "client_secret": "s3cr3t",
                "refresh_token": "rt-1",
                "code_verifier": "verifier",
            },
        },
    }


@pytest.mark.parametrize(
    "url",
    ["https://reli.example.com/oauth/token", "http://127.0.0.1:8000/oauth/token", "/oauth/token"],
)
def test_strip_auth_flow_request_drops_oauth_token_body(url):
    """A 5xx on /oauth/token keeps reporting, without the form body, query or cookies.

    The SDK records ``request.url`` as a full URL whenever a Host header is present and as a bare
    path otherwise, so the hook has to match the path in every shape.
    """
    from backend.sentry import _strip_auth_flow_request

    event = _oauth_token_event(url)
    result = _strip_auth_flow_request(event, None)
    assert result is event
    assert "data" not in result["request"]
    assert "query_string" not in result["request"]
    assert "cookies" not in result["request"]
    assert result["request"]["url"] == url
    assert result["request"]["method"] == "POST"
    assert result["level"] == "error"


def test_strip_auth_flow_request_drops_google_callback_query():
    """The Google callback's code and state travel in the query string, so it goes too."""
    from backend.sentry import _strip_auth_flow_request

    event = {
        "type": "transaction",
        "transaction": "/api/auth/google/callback",
        "request": {
            "url": "https://reli.example.com/api/auth/google/callback",
            "method": "GET",
            "query_string": "code=4/0AbCdEf&state=opaque-state",
        },
    }
    result = _strip_auth_flow_request(event, None)
    assert result is not None
    assert "query_string" not in result["request"]
    assert result["transaction"] == "/api/auth/google/callback"


@pytest.mark.parametrize(
    "url",
    [
        "https://reli.example.com/api/things?tag=%23Project",
        "https://reli.example.com/mcp",
        "https://reli.example.com/oauth-lookalike/token",
    ],
)
def test_strip_auth_flow_request_leaves_other_routes_alone(url):
    """Routes outside /oauth/ and /api/auth/ keep whatever the SDK attached."""
    from backend.sentry import _strip_auth_flow_request

    request = {"url": url, "method": "GET", "query_string": "tag=#Project", "data": {"title": "x"}}
    event = {"request": dict(request)}
    result = _strip_auth_flow_request(event, None)
    assert result["request"] == request


@pytest.mark.parametrize("event", [{"message": "boot"}, {"request": None}, {"request": {"method": "POST"}}])
def test_strip_auth_flow_request_without_request_url(event):
    """Events with no request, or one without a URL, pass through unchanged."""
    from backend.sentry import _strip_auth_flow_request

    original = {k: (dict(v) if isinstance(v, dict) else v) for k, v in event.items()}
    assert _strip_auth_flow_request(event, None) == original
