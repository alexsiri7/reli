"""The four bounded stores behind the authorization server: what they keep, purge and refuse."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.oauth_state import (
    McpRegisteredClientRecord,
    Store,
    StoreFullError,
    cleanup_and_get,
    cleanup_and_pop,
    cleanup_and_store,
    mcp_auth_codes,
    mcp_registered_clients,
)


def _client(expires_in=timedelta(days=30), **overrides):
    return {
        "client_secret": "secret",
        "redirect_uris": ["https://client.example.test/callback"],
        "client_name": "Claude",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": "mcp",
        "expires_at": datetime.now(UTC) + expires_in,
        **overrides,
    }


def test_a_stored_entry_comes_back_with_its_list_fields_and_an_aware_expiry(session):
    cleanup_and_store(session, mcp_registered_clients, "client-1", _client())

    found = cleanup_and_get(session, mcp_registered_clients, "client-1")

    assert found is not None
    assert found["client_id"] == "client-1"
    assert found["redirect_uris"] == ["https://client.example.test/callback"]
    assert found["grant_types"] == ["authorization_code", "refresh_token"]
    assert found["expires_at"].tzinfo is not None


def test_an_expired_entry_is_gone_on_the_next_access(session):
    cleanup_and_store(session, mcp_registered_clients, "client-1", _client(expires_in=timedelta(seconds=-1)))

    assert cleanup_and_get(session, mcp_registered_clients, "client-1") is None


def test_pop_returns_the_entry_once(session):
    values = {
        "subject": "google-sub",
        "email": "owner@example.com",
        "code_challenge": "challenge",
        "code_challenge_method": "S256",
        "redirect_uri": "https://client.example.test/callback",
        "client_id": "client-1",
        "scope": "mcp",
        "expires_at": datetime.now(UTC) + timedelta(seconds=60),
    }
    cleanup_and_store(session, mcp_auth_codes, "code-1", values)

    popped = cleanup_and_pop(session, mcp_auth_codes, "code-1")

    assert popped is not None
    assert popped["subject"] == "google-sub"
    assert cleanup_and_pop(session, mcp_auth_codes, "code-1") is None


def test_a_store_at_its_cap_refuses_rather_than_growing(session):
    tiny = Store(McpRegisteredClientRecord, max_entries=1)
    cleanup_and_store(session, tiny, "client-1", _client())

    with pytest.raises(StoreFullError):
        cleanup_and_store(session, tiny, "client-2", _client())

    assert cleanup_and_get(session, tiny, "client-2") is None


def test_storing_under_an_existing_key_replaces_the_entry(session):
    cleanup_and_store(session, mcp_registered_clients, "client-1", _client(client_name="first"))
    cleanup_and_store(session, mcp_registered_clients, "client-1", _client(client_name="second"))

    found = cleanup_and_get(session, mcp_registered_clients, "client-1")

    assert found is not None
    assert found["client_name"] == "second"
