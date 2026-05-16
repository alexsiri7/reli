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
        call_args = mock_sdk.set_user.call_args[0][0]
        assert "email" not in call_args


def test_strip_cookie_breadcrumb_filters_cookie_header():
    """_strip_cookie_breadcrumb should redact Cookie header values."""
    from backend.sentry import _strip_cookie_breadcrumb

    crumb = {"data": {"Cookie": "reli_session=supersecretjwt", "X-Other": "value"}}
    result = _strip_cookie_breadcrumb(crumb, None)
    assert result is not None
    assert result["data"]["Cookie"] == "[Filtered]"
    assert result["data"]["X-Other"] == "value"


def test_strip_cookie_breadcrumb_no_cookie_passthrough():
    """_strip_cookie_breadcrumb should pass through breadcrumbs without cookie headers."""
    from backend.sentry import _strip_cookie_breadcrumb

    crumb = {"data": {"Authorization": "Bearer token"}}
    result = _strip_cookie_breadcrumb(crumb, None)
    assert result is not None
    assert result["data"]["Authorization"] == "Bearer token"


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
