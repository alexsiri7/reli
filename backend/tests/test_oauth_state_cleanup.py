"""Tests for OAuth state DB-backed TTL cleanup and size caps."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.oauth_state import (
    StoreFullError,
    cleanup_and_get,
    cleanup_and_pop,
    cleanup_and_store,
    mcp_oauth_sessions,
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


def test_cleanup_and_store_rejects_when_full(patched_db, monkeypatch):
    _cap = 5
    monkeypatch.setattr("backend.oauth_state.MAX_ENTRIES_PER_DICT", _cap)
    for i in range(_cap):
        cleanup_and_store(
            mcp_oauth_sessions,
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
            mcp_oauth_sessions,
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


def test_cleanup_and_store_allows_insert_after_evicting_expired(patched_db, monkeypatch):
    """Fill to capacity with expired entries; insert should succeed after purge."""
    _cap = 5
    monkeypatch.setattr("backend.oauth_state.MAX_ENTRIES_PER_DICT", _cap)
    for i in range(_cap):
        cleanup_and_store(
            mcp_oauth_sessions,
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
        mcp_oauth_sessions,
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
    result = cleanup_and_get(mcp_oauth_sessions, "fresh")
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
