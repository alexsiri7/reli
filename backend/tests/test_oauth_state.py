"""Tests for oauth_state: expiry, capacity, and replay prevention."""

import time

import pytest

from backend.oauth_state import (
    MAX_ENTRIES_PER_DICT,
    StoreFullError,
    cleanup_and_get,
    cleanup_and_pop,
    cleanup_and_store,
)


class TestDictStoreExpiry:
    def test_expired_entry_not_retrievable(self):
        """An entry whose expires_at is in the past should be cleaned up and not returned."""
        store: dict[str, dict] = {}
        cleanup_and_store(store, "k1", {"value": "secret", "expires_at": time.time() - 10})
        result = cleanup_and_get(store, "k1")
        assert result is None

    def test_cleanup_removes_only_expired(self):
        """Cleanup removes expired entries but leaves valid ones intact."""
        store: dict[str, dict] = {}
        cleanup_and_store(store, "expired", {"expires_at": time.time() - 10})
        cleanup_and_store(store, "valid", {"expires_at": time.time() + 3600})
        result = cleanup_and_get(store, "valid")
        assert result is not None
        assert result["expires_at"] == pytest.approx(time.time() + 3600, abs=5)


class TestDictStorePopReplay:
    def test_pop_consumes_entry_exactly_once(self):
        """Pop returns the entry on first call, None on second (replay prevention)."""
        store: dict[str, dict] = {}
        cleanup_and_store(store, "token", {"data": "auth_code_123"})
        first = cleanup_and_pop(store, "token")
        assert first is not None
        assert first["data"] == "auth_code_123"
        second = cleanup_and_pop(store, "token")
        assert second is None


class TestDictStoreCapacity:
    def test_store_full_raises(self):
        """Exceeding MAX_ENTRIES_PER_DICT raises StoreFullError."""
        store: dict[str, dict] = {}
        # Fill to capacity
        for i in range(MAX_ENTRIES_PER_DICT):
            store[f"k{i}"] = {"expires_at": time.time() + 3600}
        with pytest.raises(StoreFullError):
            cleanup_and_store(store, "overflow", {"expires_at": time.time() + 3600})


def _session_entry(expires_at: float) -> dict:
    """Build a complete MCP OAuth session entry with all required fields."""
    return {
        "client_state": "cs",
        "redirect_uri": "http://x",
        "code_challenge": "cc",
        "code_challenge_method": "S256",
        "client_id": "cid",
        "scope": "openid",
        "google_code_verifier": "gcv",
        "expires_at": expires_at,
    }


class TestDbStoreExpiry:
    def test_expired_entry_not_retrievable(self, patched_db):
        """A DB-backed entry whose expires_at is in the past should not be returned."""
        from backend.oauth_state import mcp_oauth_sessions

        cleanup_and_store(mcp_oauth_sessions, "expired-state", _session_entry(time.time() - 10))
        result = cleanup_and_get(mcp_oauth_sessions, "expired-state")
        assert result is None

    def test_pop_consumes_entry_exactly_once(self, patched_db):
        """A DB-backed pop returns the entry once, then None."""
        from backend.oauth_state import mcp_oauth_sessions

        cleanup_and_store(mcp_oauth_sessions, "once-state", _session_entry(time.time() + 3600))
        first = cleanup_and_pop(mcp_oauth_sessions, "once-state")
        assert first is not None
        second = cleanup_and_pop(mcp_oauth_sessions, "once-state")
        assert second is None
