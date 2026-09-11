"""The five bounded stores behind the authorization server: what they keep, purge, consume and refuse."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from backend.db_engine import get_engine
from backend.oauth_state import (
    McpRegisteredClientRecord,
    Store,
    StoreFullError,
    cleanup_and_get,
    cleanup_and_pop,
    cleanup_and_store,
    consume_refresh_token,
    mcp_auth_codes,
    mcp_refresh_tokens,
    mcp_registered_clients,
    revoke_refresh_token_family,
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


def _auth_code(**overrides):
    return {
        "subject": "google-sub",
        "email": "owner@example.com",
        "code_challenge": "challenge",
        "code_challenge_method": "S256",
        "redirect_uri": "https://client.example.test/callback",
        "client_id": "client-1",
        "scope": "mcp",
        "expires_at": datetime.now(UTC) + timedelta(seconds=60),
        **overrides,
    }


def _refresh_token(family_id="fam-1", expires_in=timedelta(days=30), **overrides):
    return {
        "subject": "google-sub",
        "email": "owner@example.com",
        "client_id": "client-1",
        "scope": "mcp",
        "family_id": family_id,
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
    cleanup_and_store(session, mcp_auth_codes, "code-1", _auth_code())

    popped = cleanup_and_pop(session, mcp_auth_codes, "code-1")

    assert popped is not None
    assert popped["subject"] == "google-sub"
    assert popped["expires_at"].tzinfo is not None
    assert cleanup_and_pop(session, mcp_auth_codes, "code-1") is None
    assert cleanup_and_get(session, mcp_auth_codes, "code-1") is None


def test_pop_does_not_return_an_expired_entry(session):
    cleanup_and_store(
        session, mcp_auth_codes, "code-1", _auth_code(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )

    assert cleanup_and_pop(session, mcp_auth_codes, "code-1") is None


def test_pop_hands_the_entry_to_exactly_one_of_concurrent_callers(session):
    """Each caller has its own connection: the fixture session is one, and one cannot race itself."""
    cleanup_and_store(session, mcp_auth_codes, "code-1", _auth_code())

    def pop(_):
        with Session(get_engine()) as own:
            return cleanup_and_pop(own, mcp_auth_codes, "code-1")

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(pop, range(4)))

    assert sum(result is not None for result in results) == 1


def test_consume_refresh_token_marks_the_row_and_answers_once(session):
    cleanup_and_store(session, mcp_refresh_tokens, "token-1", _refresh_token())

    consumed = consume_refresh_token(session, "token-1")
    session.commit()

    assert consumed is not None
    assert consumed["family_id"] == "fam-1"
    assert consumed["consumed_at"] is not None
    assert consume_refresh_token(session, "token-1") is None
    kept = cleanup_and_get(session, mcp_refresh_tokens, "token-1")
    assert kept is not None
    assert kept["consumed_at"] == consumed["consumed_at"]


def test_consume_refresh_token_ignores_an_expired_token(session):
    cleanup_and_store(session, mcp_refresh_tokens, "token-1", _refresh_token(expires_in=timedelta(seconds=-1)))

    assert consume_refresh_token(session, "token-1") is None


def test_revoke_refresh_token_family_deletes_the_family_and_nothing_else(session):
    cleanup_and_store(session, mcp_refresh_tokens, "token-1", _refresh_token("fam-1"))
    cleanup_and_store(session, mcp_refresh_tokens, "token-2", _refresh_token("fam-1"))
    cleanup_and_store(session, mcp_refresh_tokens, "token-3", _refresh_token("fam-2"))
    assert consume_refresh_token(session, "token-1") is not None

    assert revoke_refresh_token_family(session, "fam-1") == 2

    assert cleanup_and_get(session, mcp_refresh_tokens, "token-1") is None
    assert cleanup_and_get(session, mcp_refresh_tokens, "token-2") is None
    assert cleanup_and_get(session, mcp_refresh_tokens, "token-3") is not None


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
