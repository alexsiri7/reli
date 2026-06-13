"""Tests for google_calendar _pending_flows TTL and size-cap enforcement (SEC-07)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.oauth_state import MAX_ENTRIES_PER_DICT, StoreFullError, cleanup_and_store


def _make_flow(state: str = "test-state", code_verifier: str = "verifier"):
    flow = MagicMock()
    flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?state=x", state)
    flow.code_verifier = code_verifier
    return flow


def _patched_get_auth_url(flow):
    """Call get_auth_url() with a mocked Flow."""
    with (
        patch("backend.google_calendar.Flow.from_client_config", return_value=flow),
        patch("backend.google_calendar.GOOGLE_REDIRECT_URI", "http://localhost/cb"),
        patch("backend.google_calendar.GOOGLE_CLIENT_ID", "cid"),
        patch("backend.google_calendar.GOOGLE_CLIENT_SECRET", "secret"),
    ):
        from backend.google_calendar import get_auth_url

        return get_auth_url()


def test_get_auth_url_stores_with_ttl():
    """get_auth_url() stores a dict entry with expires_at set."""
    import backend.google_calendar as gcal

    gcal._pending_flows.clear()
    flow = _make_flow(state="s1", code_verifier="cv1")
    _patched_get_auth_url(flow)
    assert "s1" in gcal._pending_flows
    entry = gcal._pending_flows["s1"]
    assert entry["code_verifier"] == "cv1"
    assert "expires_at" in entry
    assert entry["expires_at"] > datetime.now(timezone.utc)
    gcal._pending_flows.clear()


def test_get_auth_url_raises_on_full_store(monkeypatch):
    """get_auth_url() raises ValueError when store is full."""
    import backend.google_calendar as gcal

    monkeypatch.setattr("backend.oauth_state.MAX_ENTRIES_PER_DICT", 0)
    gcal._pending_flows.clear()
    flow = _make_flow(state="overflow")
    with pytest.raises(ValueError, match="capacity"):
        _patched_get_auth_url(flow)
    gcal._pending_flows.clear()


def test_exchange_code_rejects_expired_state():
    """exchange_code() raises ValueError for an expired OAuth state."""
    import backend.google_calendar as gcal

    gcal._pending_flows.clear()
    gcal._pending_flows["dead-state"] = {
        "code_verifier": "cv",
        "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
    }

    with pytest.raises(ValueError, match="Invalid or expired"):
        with (
            patch("backend.google_calendar.Flow.from_client_config", return_value=MagicMock()),
            patch("backend.google_calendar.GOOGLE_REDIRECT_URI", "http://localhost/cb"),
            patch("backend.google_calendar.GOOGLE_CLIENT_ID", "cid"),
            patch("backend.google_calendar.GOOGLE_CLIENT_SECRET", "secret"),
        ):
            from backend.google_calendar import exchange_code

            exchange_code(code="authcode", state="dead-state", user_id="u1")
    gcal._pending_flows.clear()


def test_exchange_code_pops_state():
    """exchange_code() consumes the state so it cannot be replayed."""
    import backend.google_calendar as gcal

    gcal._pending_flows.clear()
    gcal._pending_flows["live-state"] = {
        "code_verifier": "cv",
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
    }

    mock_flow = MagicMock()
    mock_creds = MagicMock()
    mock_creds.expiry = None
    mock_creds.scopes = None
    mock_creds.token = None
    mock_creds.refresh_token = None
    mock_creds.client_secret = None
    mock_flow.credentials = mock_creds

    with (
        patch("backend.google_calendar.Flow.from_client_config", return_value=mock_flow),
        patch("backend.google_calendar.GOOGLE_REDIRECT_URI", "http://localhost/cb"),
        patch("backend.google_calendar.GOOGLE_CLIENT_ID", "cid"),
        patch("backend.google_calendar.GOOGLE_CLIENT_SECRET", "secret"),
        patch("backend.google_calendar._save_credentials"),
    ):
        from backend.google_calendar import exchange_code

        exchange_code(code="authcode", state="live-state", user_id="u1")

    assert "live-state" not in gcal._pending_flows
