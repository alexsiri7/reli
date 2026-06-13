"""Tests for OAuth state DB-backed TTL cleanup and size caps."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.oauth_state import (
    StoreFullError,
    cleanup_and_get,
    cleanup_and_pop,
    cleanup_and_store,
    gmail_oauth_states,
    mcp_auth_codes,
    mcp_oauth_sessions,
    mcp_refresh_tokens,
    mcp_registered_clients,
)

# ---------------------------------------------------------------------------
# cleanup_and_store
# ---------------------------------------------------------------------------


def test_cleanup_and_store_inserts_entry(patched_db):
    cleanup_and_store(
        mcp_oauth_sessions,
        "key1",
        {
            "client_state": "cs",
            "redirect_uri": "http://x",
            "code_challenge": "cc",
            "code_challenge_method": "S256",
            "client_id": "cid",
            "scope": "mcp",
            "google_code_verifier": "gv",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        },
    )
    result = cleanup_and_get(mcp_oauth_sessions, "key1")
    assert result is not None
    assert result["client_state"] == "cs"


def test_cleanup_and_store_purges_expired_before_insert(patched_db):
    cleanup_and_store(
        mcp_oauth_sessions,
        "dead",
        {
            "client_state": "cs",
            "redirect_uri": "http://x",
            "code_challenge": "cc",
            "code_challenge_method": "S256",
            "client_id": "cid",
            "scope": "mcp",
            "google_code_verifier": "gv",
            "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
    )
    cleanup_and_store(
        mcp_oauth_sessions,
        "new",
        {
            "client_state": "cs2",
            "redirect_uri": "http://y",
            "code_challenge": "cc2",
            "code_challenge_method": "S256",
            "client_id": "cid2",
            "scope": "mcp",
            "google_code_verifier": "gv2",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        },
    )
    assert cleanup_and_get(mcp_oauth_sessions, "dead") is None
    assert cleanup_and_get(mcp_oauth_sessions, "new") is not None


def test_cleanup_and_store_rejects_when_full(patched_db):
    from backend.db_models import McpOAuthSessionRecord
    from backend.oauth_state import _Store

    _cap = 5
    small_store = _Store(model=McpOAuthSessionRecord, pk_field="server_state", max_entries=_cap)
    for i in range(_cap):
        cleanup_and_store(
            small_store,
            str(i),
            {
                "client_state": "cs",
                "redirect_uri": "http://x",
                "code_challenge": "cc",
                "code_challenge_method": "S256",
                "client_id": "cid",
                "scope": "mcp",
                "google_code_verifier": "gv",
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            },
        )
    with pytest.raises(StoreFullError):
        cleanup_and_store(
            small_store,
            "overflow",
            {
                "client_state": "cs",
                "redirect_uri": "http://x",
                "code_challenge": "cc",
                "code_challenge_method": "S256",
                "client_id": "cid",
                "scope": "mcp",
                "google_code_verifier": "gv",
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            },
        )


def test_cleanup_and_store_allows_insert_after_evicting_expired(patched_db):
    """Fill to capacity with expired entries; insert should succeed after purge."""
    from backend.db_models import McpOAuthSessionRecord
    from backend.oauth_state import _Store

    _cap = 5
    small_store = _Store(model=McpOAuthSessionRecord, pk_field="server_state", max_entries=_cap)
    for i in range(_cap):
        cleanup_and_store(
            small_store,
            str(i),
            {
                "client_state": "cs",
                "redirect_uri": "http://x",
                "code_challenge": "cc",
                "code_challenge_method": "S256",
                "client_id": "cid",
                "scope": "mcp",
                "google_code_verifier": "gv",
                "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
            },
        )
    cleanup_and_store(
        small_store,
        "fresh",
        {
            "client_state": "ok",
            "redirect_uri": "http://fresh",
            "code_challenge": "cc",
            "code_challenge_method": "S256",
            "client_id": "cid",
            "scope": "mcp",
            "google_code_verifier": "gv",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        },
    )
    result = cleanup_and_get(small_store, "fresh")
    assert result is not None
    assert result["client_state"] == "ok"


# ---------------------------------------------------------------------------
# cleanup_and_get / cleanup_and_pop
# ---------------------------------------------------------------------------


def test_cleanup_and_get_returns_entry(patched_db):
    cleanup_and_store(
        mcp_oauth_sessions,
        "k",
        {
            "client_state": "cs",
            "redirect_uri": "http://x",
            "code_challenge": "cc",
            "code_challenge_method": "S256",
            "client_id": "cid",
            "scope": "mcp",
            "google_code_verifier": "gv",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        },
    )
    result = cleanup_and_get(mcp_oauth_sessions, "k")
    assert result is not None
    assert result["client_state"] == "cs"
    # Not consumed
    assert cleanup_and_get(mcp_oauth_sessions, "k") is not None


def test_cleanup_and_get_returns_none_for_missing(patched_db):
    assert cleanup_and_get(mcp_oauth_sessions, "missing") is None


def test_cleanup_and_get_purges_expired(patched_db):
    cleanup_and_store(
        mcp_oauth_sessions,
        "dead",
        {
            "client_state": "cs",
            "redirect_uri": "http://x",
            "code_challenge": "cc",
            "code_challenge_method": "S256",
            "client_id": "cid",
            "scope": "mcp",
            "google_code_verifier": "gv",
            "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
    )
    cleanup_and_store(
        mcp_oauth_sessions,
        "alive",
        {
            "client_state": "cs2",
            "redirect_uri": "http://y",
            "code_challenge": "cc2",
            "code_challenge_method": "S256",
            "client_id": "cid2",
            "scope": "mcp",
            "google_code_verifier": "gv2",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        },
    )
    cleanup_and_get(mcp_oauth_sessions, "alive")
    assert cleanup_and_get(mcp_oauth_sessions, "dead") is None


def test_cleanup_and_pop_returns_and_removes(patched_db):
    cleanup_and_store(
        mcp_oauth_sessions,
        "k",
        {
            "client_state": "cs",
            "redirect_uri": "http://x",
            "code_challenge": "cc",
            "code_challenge_method": "S256",
            "client_id": "cid",
            "scope": "mcp",
            "google_code_verifier": "gv",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        },
    )
    result = cleanup_and_pop(mcp_oauth_sessions, "k")
    assert result is not None
    assert result["client_state"] == "cs"
    assert cleanup_and_get(mcp_oauth_sessions, "k") is None


def test_cleanup_and_pop_returns_none_for_missing(patched_db):
    assert cleanup_and_pop(mcp_oauth_sessions, "missing") is None


def test_cleanup_and_pop_purges_expired(patched_db):
    cleanup_and_store(
        mcp_oauth_sessions,
        "dead",
        {
            "client_state": "cs",
            "redirect_uri": "http://x",
            "code_challenge": "cc",
            "code_challenge_method": "S256",
            "client_id": "cid",
            "scope": "mcp",
            "google_code_verifier": "gv",
            "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
    )
    cleanup_and_store(
        mcp_oauth_sessions,
        "alive",
        {
            "client_state": "cs2",
            "redirect_uri": "http://y",
            "code_challenge": "cc2",
            "code_challenge_method": "S256",
            "client_id": "cid2",
            "scope": "mcp",
            "google_code_verifier": "gv2",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        },
    )
    cleanup_and_pop(mcp_oauth_sessions, "alive")
    assert cleanup_and_get(mcp_oauth_sessions, "dead") is None


# ---------------------------------------------------------------------------
# Registered client TTL
# ---------------------------------------------------------------------------


def test_registered_client_with_expires_at_is_evicted_when_expired(patched_db):
    """Clients with an expires_at in the past are cleaned up."""
    cleanup_and_store(
        mcp_registered_clients,
        "client_fresh",
        {
            "client_secret": "s1",
            "redirect_uris": [],
            "client_name": "fresh",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
            "scope": "mcp",
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
        },
    )
    cleanup_and_store(
        mcp_registered_clients,
        "client_expired",
        {
            "client_secret": "s2",
            "redirect_uris": [],
            "client_name": "expired",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
            "scope": "mcp",
            "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
    )
    assert cleanup_and_get(mcp_registered_clients, "client_fresh") is not None
    assert cleanup_and_get(mcp_registered_clients, "client_expired") is None


def test_registered_client_json_fields_roundtrip(patched_db):
    """Lists survive JSON serialization/deserialization roundtrip."""
    cleanup_and_store(
        mcp_registered_clients,
        "client_json",
        {
            "client_secret": "s",
            "redirect_uris": ["http://a", "http://b"],
            "client_name": "test",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
            "scope": "mcp",
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
        },
    )
    result = cleanup_and_get(mcp_registered_clients, "client_json")
    assert result is not None
    assert result["redirect_uris"] == ["http://a", "http://b"]
    assert result["grant_types"] == ["authorization_code"]
    assert result["response_types"] == ["code"]


def test_expires_at_returned_as_datetime(patched_db):
    """expires_at should be returned as a timezone-aware datetime for backward compat."""
    cleanup_and_store(
        mcp_oauth_sessions,
        "dt_check",
        {
            "client_state": "cs",
            "redirect_uri": "http://x",
            "code_challenge": "cc",
            "code_challenge_method": "S256",
            "client_id": "cid",
            "scope": "mcp",
            "google_code_verifier": "gv",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        },
    )
    result = cleanup_and_get(mcp_oauth_sessions, "dt_check")
    assert result is not None
    assert isinstance(result["expires_at"], datetime)
    assert result["expires_at"].tzinfo is not None


def test_oauth_register_sets_expires_at(patched_db):
    """oauth_register() stores expires_at on the client dict (SEC-017 regression guard)."""
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as client:
        before = datetime.now(timezone.utc)
        response = client.post("/oauth/register", json={"client_name": "test-sec017"})
        after = datetime.now(timezone.utc)

    assert response.status_code == 201
    data = response.json()
    client_id = data["client_id"]

    # Verify expires_at is stored
    stored = cleanup_and_get(mcp_registered_clients, client_id)
    assert stored is not None, "client was not stored in mcp_registered_clients"
    exp = stored.get("expires_at")
    assert isinstance(exp, datetime), f"expires_at should be datetime, got {type(exp)}"
    assert exp.tzinfo is not None, "expires_at must be timezone-aware"
    # TTL is 30 days; allow 5-second tolerance
    assert before + timedelta(days=30) <= exp <= after + timedelta(days=30, seconds=5)

    # Verify client_secret_expires_at is returned in the response (RFC 7591 §3.2.1)
    assert "client_secret_expires_at" in data, "client_secret_expires_at must be in registration response"
    assert isinstance(data["client_secret_expires_at"], int), "client_secret_expires_at must be a Unix epoch integer"
    expected_epoch = int(exp.timestamp())
    assert data["client_secret_expires_at"] == expected_epoch


# ---------------------------------------------------------------------------
# mcp_auth_codes store
# ---------------------------------------------------------------------------


def test_auth_code_client_id_roundtrip(patched_db):
    """client_id must survive the DB roundtrip — prevents code injection."""
    cleanup_and_store(
        mcp_auth_codes,
        "code-abc",
        {
            "user_id": "user-1",
            "email": "user@example.com",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "redirect_uri": "http://localhost/cb",
            "client_id": "client-xyz",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
    )
    result = cleanup_and_get(mcp_auth_codes, "code-abc")
    assert result is not None
    assert result["client_id"] == "client-xyz"
    assert result["user_id"] == "user-1"
    assert result["email"] == "user@example.com"
    assert isinstance(result["expires_at"], datetime)


def test_auth_code_pop_removes_and_returns(patched_db):
    """cleanup_and_pop consumes the auth code (one-time use)."""
    cleanup_and_store(
        mcp_auth_codes,
        "code-once",
        {
            "user_id": "u",
            "email": "e@e.com",
            "code_challenge": "cc",
            "code_challenge_method": "S256",
            "redirect_uri": "http://cb",
            "client_id": "client-xyz",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
    )
    result = cleanup_and_pop(mcp_auth_codes, "code-once")
    assert result is not None
    assert result["client_id"] == "client-xyz"
    assert cleanup_and_pop(mcp_auth_codes, "code-once") is None


def test_auth_code_evicted_when_expired(patched_db):
    """Expired auth codes are purged on access."""
    cleanup_and_store(
        mcp_auth_codes,
        "code-dead",
        {
            "user_id": "u",
            "email": "e@e.com",
            "code_challenge": "cc",
            "code_challenge_method": "S256",
            "redirect_uri": "http://cb",
            "client_id": "client-xyz",
            "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
    )
    assert cleanup_and_get(mcp_auth_codes, "code-dead") is None


# ---------------------------------------------------------------------------
# mcp_refresh_tokens store
# ---------------------------------------------------------------------------


def test_refresh_token_roundtrip(patched_db):
    """Refresh token fields must survive DB roundtrip."""
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    cleanup_and_store(
        mcp_refresh_tokens,
        "rt-secret",
        {
            "user_id": "user-1",
            "email": "user@example.com",
            "client_id": "client-xyz",
            "scope": "mcp",
            "expires_at": expires,
        },
    )
    result = cleanup_and_pop(mcp_refresh_tokens, "rt-secret")
    assert result is not None
    assert result["user_id"] == "user-1"
    assert result["client_id"] == "client-xyz"
    assert result["scope"] == "mcp"
    assert isinstance(result["expires_at"], datetime)
    assert result["expires_at"].tzinfo is not None
    assert cleanup_and_pop(mcp_refresh_tokens, "rt-secret") is None


def test_refresh_token_evicted_when_expired(patched_db):
    """Expired refresh tokens are purged on access."""
    cleanup_and_store(
        mcp_refresh_tokens,
        "rt-dead",
        {
            "user_id": "user-1",
            "email": "user@example.com",
            "client_id": "client-xyz",
            "scope": "mcp",
            "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
    )
    assert cleanup_and_get(mcp_refresh_tokens, "rt-dead") is None


# ---------------------------------------------------------------------------
# gmail_oauth_states store
# ---------------------------------------------------------------------------


def test_gmail_oauth_state_roundtrip(patched_db):
    """Gmail OAuth state fields survive the DB roundtrip."""
    cleanup_and_store(
        gmail_oauth_states,
        "user-123",
        {
            "state": "oauth-state-value",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
    )
    result = cleanup_and_get(gmail_oauth_states, "user-123")
    assert result is not None
    assert result["state"] == "oauth-state-value"
    assert isinstance(result["expires_at"], datetime)


def test_gmail_oauth_state_upsert_replaces(patched_db):
    """Storing a second state for the same user_id replaces the first (upsert path)."""
    cleanup_and_store(
        gmail_oauth_states,
        "user-123",
        {
            "state": "old-state",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
    )
    cleanup_and_store(
        gmail_oauth_states,
        "user-123",
        {
            "state": "new-state",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
    )
    result = cleanup_and_get(gmail_oauth_states, "user-123")
    assert result is not None
    assert result["state"] == "new-state"


def test_gmail_oauth_state_pop_removes(patched_db):
    """cleanup_and_pop removes the entry after returning it."""
    cleanup_and_store(
        gmail_oauth_states,
        "user-456",
        {
            "state": "state-val",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
    )
    result = cleanup_and_pop(gmail_oauth_states, "user-456")
    assert result is not None
    assert result["state"] == "state-val"
    assert cleanup_and_get(gmail_oauth_states, "user-456") is None


def test_gmail_oauth_state_evicted_when_expired(patched_db):
    """Expired Gmail OAuth states are purged on access."""
    cleanup_and_store(
        gmail_oauth_states,
        "user-789",
        {
            "state": "dead-state",
            "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
    )
    assert cleanup_and_get(gmail_oauth_states, "user-789") is None


# ---------------------------------------------------------------------------
# Explicit TTL, atomic pop, and capacity gate tests
# ---------------------------------------------------------------------------


def test_expired_entry_returns_none_and_is_deleted(patched_db):
    """An entry stored with an already-expired TTL returns None on get."""
    cleanup_and_store(
        mcp_oauth_sessions,
        "ttl-expired",
        {
            "client_state": "cs",
            "redirect_uri": "http://x",
            "code_challenge": "cc",
            "code_challenge_method": "S256",
            "client_id": "cid",
            "scope": "mcp",
            "google_code_verifier": "gv",
            "expires_at": datetime.now(timezone.utc) - timedelta(seconds=10),
        },
    )
    result = cleanup_and_get(mcp_oauth_sessions, "ttl-expired")
    assert result is None
    # Confirm a second access also returns None (row was actually deleted)
    assert cleanup_and_get(mcp_oauth_sessions, "ttl-expired") is None


def test_pop_is_atomic_double_pop_returns_none(patched_db):
    """cleanup_and_pop is one-time-use: second pop of same key returns None."""
    cleanup_and_store(
        mcp_oauth_sessions,
        "atomic-key",
        {
            "client_state": "cs",
            "redirect_uri": "http://x",
            "code_challenge": "cc",
            "code_challenge_method": "S256",
            "client_id": "cid",
            "scope": "mcp",
            "google_code_verifier": "gv",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        },
    )
    first = cleanup_and_pop(mcp_oauth_sessions, "atomic-key")
    assert first is not None
    assert first["client_state"] == "cs"

    second = cleanup_and_pop(mcp_oauth_sessions, "atomic-key")
    assert second is None


def test_registered_clients_store_has_reduced_cap(patched_db):
    """mcp_registered_clients max_entries is 100, not the global 10_000."""
    assert mcp_registered_clients.max_entries == 100


def test_store_max_entries_override(patched_db):
    """A _Store with max_entries=2 raises StoreFullError on the 3rd insert."""
    from backend.oauth_state import McpOAuthSessionRecord, _Store

    small_store = _Store(
        model=McpOAuthSessionRecord,
        pk_field="server_state",
        max_entries=2,
    )
    base = {
        "client_state": "cs",
        "redirect_uri": "http://x",
        "code_challenge": "cc",
        "code_challenge_method": "S256",
        "client_id": "cid",
        "scope": "mcp",
        "google_code_verifier": "gv",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    cleanup_and_store(small_store, "k1", base)
    cleanup_and_store(small_store, "k2", base)
    with pytest.raises(StoreFullError):
        cleanup_and_store(small_store, "k3", base)


def test_store_full_raises_at_cap_two(patched_db):
    """StoreFullError fires when cap is set to 2 and a 3rd entry is stored."""
    from backend.db_models import McpOAuthSessionRecord
    from backend.oauth_state import _Store

    small_store = _Store(model=McpOAuthSessionRecord, pk_field="server_state", max_entries=2)
    for i in range(2):
        cleanup_and_store(
            small_store,
            f"cap2-{i}",
            {
                "client_state": "cs",
                "redirect_uri": "http://x",
                "code_challenge": "cc",
                "code_challenge_method": "S256",
                "client_id": "cid",
                "scope": "mcp",
                "google_code_verifier": "gv",
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            },
        )
    with pytest.raises(StoreFullError):
        cleanup_and_store(
            small_store,
            "cap2-overflow",
            {
                "client_state": "cs",
                "redirect_uri": "http://x",
                "code_challenge": "cc",
                "code_challenge_method": "S256",
                "client_id": "cid",
                "scope": "mcp",
                "google_code_verifier": "gv",
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            },
        )
