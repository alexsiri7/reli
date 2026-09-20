"""The five bounded stores behind the authorization server: what they keep, purge, consume, refuse or evict.

The last test walks a fresh database through the ``v4_hashed_credential_keys`` revision itself,
since ``migrated_db`` only ever runs it over empty tables.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlmodel import Session, select

from backend.db_engine import get_engine
from backend.oauth_state import (
    McpAuthCodeRecord,
    McpRefreshTokenRecord,
    McpRegisteredClientRecord,
    Store,
    StoreFullError,
    cleanup_and_get,
    cleanup_and_pop,
    cleanup_and_store,
    consume_refresh_token,
    credential_digest,
    extend_expiry,
    mcp_auth_codes,
    mcp_oauth_sessions,
    mcp_refresh_tokens,
    mcp_registered_clients,
    revoke_refresh_token_family,
    web_oauth_sessions,
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


def test_a_refusal_does_not_commit_a_flushed_refresh_token_consume(session):
    """The rotation's consume is only flushed until its replacement commits; a refusal must not commit it."""
    tiny = Store(McpRefreshTokenRecord, max_entries=1, hashes_keys=True)
    cleanup_and_store(session, tiny, "token-1", _refresh_token())
    assert consume_refresh_token(session, "token-1") is not None

    with pytest.raises(StoreFullError):
        cleanup_and_store(session, tiny, "token-2", _refresh_token())

    with Session(get_engine()) as own:
        kept = cleanup_and_get(own, mcp_refresh_tokens, "token-1")
    assert kept is not None
    assert kept["consumed_at"] is None


def test_an_evicting_store_at_its_cap_drops_the_row_nearest_expiry(session, caplog):
    tiny = Store(McpRegisteredClientRecord, max_entries=2, evicts=True)
    cleanup_and_store(session, tiny, "client-1", _client(expires_in=timedelta(hours=1)))
    cleanup_and_store(session, tiny, "client-2", _client(expires_in=timedelta(days=30)))

    with caplog.at_level("WARNING", logger="backend.oauth_state"):
        cleanup_and_store(session, tiny, "client-3", _client(expires_in=timedelta(hours=1)))

    assert cleanup_and_get(session, tiny, "client-1") is None
    assert cleanup_and_get(session, tiny, "client-2") is not None
    assert cleanup_and_get(session, tiny, "client-3") is not None
    assert any(
        "mcp_registered_clients" in record.message and "evicted 1" in record.message for record in caplog.records
    )


def test_replacing_a_key_in_a_full_store_neither_refuses_nor_evicts(session):
    tiny = Store(McpRegisteredClientRecord, max_entries=1)
    cleanup_and_store(session, tiny, "client-1", _client(client_name="first"))

    cleanup_and_store(session, tiny, "client-1", _client(client_name="second"))

    found = cleanup_and_get(session, tiny, "client-1")
    assert found is not None
    assert found["client_name"] == "second"


def test_extend_expiry_only_ever_moves_a_row_later(session):
    cleanup_and_store(session, mcp_registered_clients, "client-1", _client(expires_in=timedelta(hours=1)))
    later = datetime.now(UTC) + timedelta(days=30)

    extend_expiry(session, mcp_registered_clients, "client-1", later)
    assert cleanup_and_get(session, mcp_registered_clients, "client-1")["expires_at"] == later

    extend_expiry(session, mcp_registered_clients, "client-1", datetime.now(UTC) + timedelta(days=2))
    assert cleanup_and_get(session, mcp_registered_clients, "client-1")["expires_at"] == later

    extend_expiry(session, mcp_registered_clients, "no-such-client", later)
    assert cleanup_and_get(session, mcp_registered_clients, "no-such-client") is None


def test_only_the_stores_an_unauthenticated_caller_can_write_to_evict():
    """The routes writing to an evicting store no longer catch StoreFullError: flip a flag and they 500."""
    assert (mcp_registered_clients.evicts, mcp_oauth_sessions.evicts, web_oauth_sessions.evicts) == (True, True, True)
    assert (mcp_auth_codes.evicts, mcp_refresh_tokens.evicts) == (False, False)


def test_only_the_two_credential_stores_hash_their_keys():
    assert (mcp_auth_codes.hashes_keys, mcp_refresh_tokens.hashes_keys) == (True, True)
    assert (mcp_registered_clients.hashes_keys, mcp_oauth_sessions.hashes_keys, web_oauth_sessions.hashes_keys) == (
        False,
        False,
        False,
    )


def test_storing_under_an_existing_key_replaces_the_entry(session):
    cleanup_and_store(session, mcp_registered_clients, "client-1", _client(client_name="first"))
    cleanup_and_store(session, mcp_registered_clients, "client-1", _client(client_name="second"))

    found = cleanup_and_get(session, mcp_registered_clients, "client-1")

    assert found is not None
    assert found["client_name"] == "second"


# --- What a reader of the database holds ------------------------------------


def test_a_hashing_store_holds_only_the_digest_of_its_key(session):
    cleanup_and_store(session, mcp_refresh_tokens, "token-1", _refresh_token())

    assert session.exec(select(McpRefreshTokenRecord.refresh_token)).all() == [credential_digest("token-1")]
    assert cleanup_and_get(session, mcp_refresh_tokens, "token-1") is not None
    assert cleanup_and_get(session, mcp_refresh_tokens, credential_digest("token-1")) is None
    assert consume_refresh_token(session, credential_digest("token-1")) is None


def test_an_authorization_code_is_stored_as_its_digest_and_popped_by_the_code(session):
    cleanup_and_store(session, mcp_auth_codes, "code-1", _auth_code())

    assert session.exec(select(McpAuthCodeRecord.auth_code)).all() == [credential_digest("code-1")]
    assert cleanup_and_pop(session, mcp_auth_codes, credential_digest("code-1")) is None
    assert cleanup_and_pop(session, mcp_auth_codes, "code-1") is not None


# --- The hashing revision ---------------------------------------------------


def _insert_refresh_token(session, refresh_token, family_id):
    session.execute(
        text(
            "INSERT INTO mcp_refresh_tokens"
            " (refresh_token, subject, email, client_id, scope, family_id, expires_at)"
            " VALUES (:token, 'google-sub', 'owner@example.com', 'client-1', 'mcp', :family, :expires_at)"
        ),
        {"token": refresh_token, "family": family_id, "expires_at": datetime.now(UTC) + timedelta(days=30)},
    )


def test_the_hashing_revision_keeps_every_live_credential_redeemable(fresh_database):
    """Rows the older code stored by the credential are rewritten from their own value, so the
    connector still holding that credential is found by the new lookup and nobody re-authorises.
    This is also the proof that the digest computed in SQL is the one ``credential_digest`` computes."""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config = AlembicConfig(os.path.join(repo_root, "alembic.ini"))
    alembic_command.upgrade(config, "v4_backfill_checkin_dates")
    tokens = ("plain-token", "rotated-token", "uuid-family-token")

    with Session(get_engine()) as session:
        _insert_refresh_token(session, "plain-token", family_id="plain-token")
        _insert_refresh_token(session, "rotated-token", family_id="plain-token")
        _insert_refresh_token(session, "uuid-family-token", family_id="fam-uuid")
        session.execute(
            text(
                "INSERT INTO mcp_auth_codes (auth_code, subject, email, code_challenge, code_challenge_method,"
                " redirect_uri, client_id, scope, expires_at)"
                " VALUES ('plain-code', 'google-sub', 'owner@example.com', 'challenge', 'S256',"
                " 'https://client.example.test/callback', 'client-1', 'mcp', :expires_at)"
            ),
            {"expires_at": datetime.now(UTC) + timedelta(seconds=60)},
        )
        session.commit()

    alembic_command.upgrade(config, "head")

    with Session(get_engine()) as session:
        rows = session.exec(select(McpRefreshTokenRecord.refresh_token, McpRefreshTokenRecord.family_id)).all()
        assert {row.refresh_token for row in rows} == {credential_digest(token) for token in tokens}
        assert {row.family_id for row in rows} == {credential_digest("plain-token"), "fam-uuid"}
        assert sum(row.family_id == credential_digest("plain-token") for row in rows) == 2
        assert session.exec(select(McpAuthCodeRecord.auth_code)).all() == [credential_digest("plain-code")]
        assert not {row.refresh_token for row in rows} & set(tokens)
        assert not {row.family_id for row in rows} & set(tokens)

        assert cleanup_and_get(session, mcp_refresh_tokens, "plain-token") is not None
        assert consume_refresh_token(session, "rotated-token") is not None
        assert cleanup_and_pop(session, mcp_auth_codes, "plain-code") is not None
