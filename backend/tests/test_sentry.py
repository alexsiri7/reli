"""Tests for Sentry integration."""

from unittest.mock import patch


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
            set_sentry_user("user-123", "test@example.com")
            mock_sdk.set_user.assert_not_called()


def test_set_sentry_user_sets_context():
    """set_sentry_user should set user context on the Sentry scope."""
    with (
        patch("backend.sentry.settings") as mock_settings,
        patch("backend.sentry.sentry_sdk") as mock_sdk,
    ):
        mock_settings.SENTRY_DSN = "https://examplePublicKey@o0.ingest.sentry.io/0"
        from backend.sentry import set_sentry_user

        set_sentry_user("user-123", "test@example.com")
        mock_sdk.set_user.assert_called_once_with({"id": "user-123", "email": "test@example.com"})


def test_set_sentry_user_without_email():
    """set_sentry_user should omit email when not provided."""
    with (
        patch("backend.sentry.settings") as mock_settings,
        patch("backend.sentry.sentry_sdk") as mock_sdk,
    ):
        mock_settings.SENTRY_DSN = "https://examplePublicKey@o0.ingest.sentry.io/0"
        from backend.sentry import set_sentry_user

        set_sentry_user("user-456")
        mock_sdk.set_user.assert_called_once_with({"id": "user-456"})
