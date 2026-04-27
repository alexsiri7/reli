"""Tests for OAuth state dict TTL cleanup and size caps."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from backend.oauth_state import (
    MAX_ENTRIES_PER_DICT,
    StoreFullError,
    _cleanup_expired,
    cleanup_and_get,
    cleanup_and_pop,
    cleanup_and_store,
)

# ---------------------------------------------------------------------------
# _cleanup_expired
# ---------------------------------------------------------------------------


def test_cleanup_removes_expired_datetime_entries():
    store: dict[str, dict] = {
        "alive": {"expires_at": datetime.now(timezone.utc) + timedelta(hours=1)},
        "dead": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
    }
    _cleanup_expired(store)
    assert "alive" in store
    assert "dead" not in store


def test_cleanup_removes_expired_epoch_entries():
    store: dict[str, dict] = {
        "alive": {"expires_at": time.time() + 3600},
        "dead": {"expires_at": time.time() - 1},
    }
    _cleanup_expired(store)
    assert "alive" in store
    assert "dead" not in store


def test_cleanup_keeps_entries_without_expires_at():
    store: dict[str, dict] = {
        "no_ttl": {"data": "some_value"},
        "dead": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
    }
    _cleanup_expired(store)
    assert "no_ttl" in store
    assert "dead" not in store


def test_cleanup_noop_on_empty_store():
    store: dict[str, dict] = {}
    _cleanup_expired(store)
    assert store == {}


# ---------------------------------------------------------------------------
# cleanup_and_store
# ---------------------------------------------------------------------------


def test_cleanup_and_store_inserts_entry():
    store: dict[str, dict] = {}
    cleanup_and_store(store, "key1", {"value": 1})
    assert store["key1"] == {"value": 1}


def test_cleanup_and_store_purges_expired_before_insert():
    store: dict[str, dict] = {
        "dead": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
    }
    cleanup_and_store(store, "new", {"value": 2})
    assert "dead" not in store
    assert "new" in store


def test_cleanup_and_store_rejects_when_full():
    store: dict[str, dict] = {
        str(i): {"expires_at": datetime.now(timezone.utc) + timedelta(hours=1)} for i in range(MAX_ENTRIES_PER_DICT)
    }
    with pytest.raises(StoreFullError):
        cleanup_and_store(store, "overflow", {"value": "x"})


def test_cleanup_and_store_allows_insert_after_evicting_expired():
    """Fill to capacity with expired entries; insert should succeed after purge."""
    store: dict[str, dict] = {
        str(i): {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)} for i in range(MAX_ENTRIES_PER_DICT)
    }
    cleanup_and_store(store, "fresh", {"value": "ok"})
    assert len(store) == 1
    assert store["fresh"]["value"] == "ok"


# ---------------------------------------------------------------------------
# cleanup_and_get / cleanup_and_pop
# ---------------------------------------------------------------------------


def test_cleanup_and_get_returns_entry():
    store: dict[str, dict] = {"k": {"value": 42}}
    assert cleanup_and_get(store, "k") == {"value": 42}
    assert "k" in store  # not consumed


def test_cleanup_and_get_returns_none_for_missing():
    store: dict[str, dict] = {}
    assert cleanup_and_get(store, "missing") is None


def test_cleanup_and_get_purges_expired():
    store: dict[str, dict] = {
        "dead": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
        "alive": {"value": 1},
    }
    cleanup_and_get(store, "alive")
    assert "dead" not in store


def test_cleanup_and_pop_returns_and_removes():
    store: dict[str, dict] = {"k": {"value": 42}}
    result = cleanup_and_pop(store, "k")
    assert result == {"value": 42}
    assert "k" not in store


def test_cleanup_and_pop_returns_none_for_missing():
    store: dict[str, dict] = {}
    assert cleanup_and_pop(store, "missing") is None


def test_cleanup_and_pop_purges_expired():
    store: dict[str, dict] = {
        "dead": {"expires_at": time.time() - 1},
        "alive": {"value": 1},
    }
    cleanup_and_pop(store, "alive")
    assert "dead" not in store
