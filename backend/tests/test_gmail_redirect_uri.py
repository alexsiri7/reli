"""Tests for _gmail_redirect_uri() — SEC-009: config-driven Gmail OAuth callback URL."""

from __future__ import annotations

from unittest.mock import patch


class TestGmailRedirectUri:
    """_gmail_redirect_uri() must derive the callback URL from config, not request headers."""

    def test_uses_reli_base_url_when_set(self):
        with patch("backend.routers.gmail.settings") as mock_settings:
            mock_settings.RELI_BASE_URL = "https://reli.example.com"
            mock_settings.GOOGLE_REDIRECT_URI = "http://localhost:8000/api/calendar/callback"
            from backend.routers.gmail import _gmail_redirect_uri

            assert _gmail_redirect_uri() == "https://reli.example.com/api/gmail/callback"

    def test_strips_trailing_slash_from_reli_base_url(self):
        with patch("backend.routers.gmail.settings") as mock_settings:
            mock_settings.RELI_BASE_URL = "https://reli.example.com/"
            mock_settings.GOOGLE_REDIRECT_URI = "http://localhost:8000/api/calendar/callback"
            from backend.routers.gmail import _gmail_redirect_uri

            assert _gmail_redirect_uri() == "https://reli.example.com/api/gmail/callback"

    def test_falls_back_to_google_redirect_uri_base_when_reli_base_url_empty(self):
        with patch("backend.routers.gmail.settings") as mock_settings:
            mock_settings.RELI_BASE_URL = ""
            mock_settings.GOOGLE_REDIRECT_URI = "http://localhost:8000/api/calendar/callback"
            from backend.routers.gmail import _gmail_redirect_uri

            assert _gmail_redirect_uri() == "http://localhost:8000/api/gmail/callback"

    def test_fallback_does_not_double_path(self):
        """Positional split must not produce a doubled path when GOOGLE_REDIRECT_URI already ends with /api/gmail/callback."""
        with patch("backend.routers.gmail.settings") as mock_settings:
            mock_settings.RELI_BASE_URL = ""
            mock_settings.GOOGLE_REDIRECT_URI = "https://prod.example.com/api/gmail/callback"
            from backend.routers.gmail import _gmail_redirect_uri

            assert _gmail_redirect_uri() == "https://prod.example.com/api/gmail/callback"

    def test_fallback_logs_warning(self, caplog):
        """Fallback path must emit a logger.warning so operators can spot misconfiguration."""
        import logging

        with patch("backend.routers.gmail.settings") as mock_settings:
            mock_settings.RELI_BASE_URL = ""
            mock_settings.GOOGLE_REDIRECT_URI = "http://localhost:8000/api/calendar/callback"
            from backend.routers.gmail import _gmail_redirect_uri

            with caplog.at_level(logging.WARNING, logger="backend.routers.gmail"):
                _gmail_redirect_uri()

        assert any("RELI_BASE_URL not set" in r.message for r in caplog.records)
