"""Flow state for the OAuth 2.1 authorization server in :mod:`backend.mcp_oauth` and the web view's sign-in.

Five tables, each a bounded store of short-lived rows keyed by an opaque string: the clients that
registered themselves, the MCP sign-ins in flight, the authorization codes waiting to be exchanged,
the refresh tokens still valid, and the web view's sign-ins in flight. None of it is a Thing and
nothing here touches the graph, so nothing here is journalled — the journal records mutations of
Things and relationships, and these rows are the authorization server's bookkeeping
(docs/auth-recovery.md §6.1).

Every access purges expired rows first, so a store can only ever hold what is still live, and a
store at its cap refuses with :class:`StoreFullError` rather than growing. Client secrets are
stored in plaintext, as they were before the v4 rebuild: registration is single-tenant and a
secret is useless without an authorization code bound to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Text, delete, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Session, SQLModel, select

MAX_ENTRIES = 10_000


def _text(primary_key: bool = False) -> Any:
    return Field(sa_column=Column(Text, primary_key=primary_key, nullable=False))


def _json_list() -> Any:
    return Field(default_factory=list, sa_column=Column(JSONB, nullable=False))


def _expires_at() -> Any:
    return Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class McpRegisteredClientRecord(SQLModel, table=True):
    """A client that registered itself through ``POST /oauth/register`` (RFC 7591)."""

    __tablename__ = "mcp_registered_clients"

    client_id: str = _text(primary_key=True)
    client_secret: str = _text()
    redirect_uris: list[str] = _json_list()
    client_name: str = _text()
    grant_types: list[str] = _json_list()
    response_types: list[str] = _json_list()
    token_endpoint_auth_method: str = _text()
    scope: str = _text()
    expires_at: datetime = _expires_at()


class McpOAuthSessionRecord(SQLModel, table=True):
    """A sign-in in flight: what the client asked for, keyed by the state sent to Google."""

    __tablename__ = "mcp_oauth_sessions"

    server_state: str = _text(primary_key=True)
    client_state: str = _text()
    redirect_uri: str = _text()
    code_challenge: str = _text()
    code_challenge_method: str = _text()
    client_id: str = _text()
    scope: str = _text()
    google_code_verifier: str = _text()
    expires_at: datetime = _expires_at()


class McpAuthCodeRecord(SQLModel, table=True):
    """An authorization code minted after a Google sign-in, waiting for ``POST /oauth/token``."""

    __tablename__ = "mcp_auth_codes"

    auth_code: str = _text(primary_key=True)
    subject: str = _text()
    email: str = _text()
    code_challenge: str = _text()
    code_challenge_method: str = _text()
    redirect_uri: str = _text()
    client_id: str = _text()
    scope: str = _text()
    expires_at: datetime = _expires_at()


class McpRefreshTokenRecord(SQLModel, table=True):
    """A refresh token still valid for one ``grant_type=refresh_token`` exchange."""

    __tablename__ = "mcp_refresh_tokens"

    refresh_token: str = _text(primary_key=True)
    subject: str = _text()
    email: str = _text()
    client_id: str = _text()
    scope: str = _text()
    expires_at: datetime = _expires_at()


class WebOAuthSessionRecord(SQLModel, table=True):
    """A web-view sign-in in flight: the PKCE verifier, keyed by the state sent to Google."""

    __tablename__ = "web_oauth_sessions"

    state: str = _text(primary_key=True)
    google_code_verifier: str = _text()
    expires_at: datetime = _expires_at()


@dataclass(frozen=True)
class Store:
    """One of the five tables, with the most live rows it may hold."""

    model: type[SQLModel]
    max_entries: int

    @property
    def primary_key(self) -> str:
        return str(self.model.__table__.primary_key.columns.keys()[0])  # type: ignore[attr-defined]


# A client without a live refresh token is useless after thirty days, so one hundred is far more
# than one owner's connectors will ever register in that window — and a low cap bounds what an
# unauthenticated registration can cost.
mcp_registered_clients = Store(McpRegisteredClientRecord, max_entries=100)
mcp_oauth_sessions = Store(McpOAuthSessionRecord, max_entries=MAX_ENTRIES)
mcp_auth_codes = Store(McpAuthCodeRecord, max_entries=MAX_ENTRIES)
mcp_refresh_tokens = Store(McpRefreshTokenRecord, max_entries=MAX_ENTRIES)
web_oauth_sessions = Store(WebOAuthSessionRecord, max_entries=MAX_ENTRIES)


class StoreFullError(Exception):
    """The store is at its cap even after purging expired rows."""


def _purge_expired(session: Session, store: Store) -> None:
    session.execute(delete(store.model).where(store.model.expires_at <= datetime.now(UTC)))  # type: ignore[attr-defined]


def cleanup_and_store(session: Session, store: Store, key: str, values: dict[str, Any]) -> None:
    """Insert *values* under *key*, replacing any row already there.

    Raises:
        StoreFullError: The store holds ``max_entries`` live rows.
    """
    _purge_expired(session, store)
    live = session.exec(select(func.count()).select_from(store.model)).one()
    if live >= store.max_entries:
        session.commit()
        raise StoreFullError(f"{store.model.__tablename__} is full ({store.max_entries} entries)")  # type: ignore[attr-defined]

    existing = session.get(store.model, key)
    if existing is not None:
        session.delete(existing)
        session.flush()
    session.add(store.model(**{store.primary_key: key, **values}))
    session.commit()


def cleanup_and_get(session: Session, store: Store, key: str) -> dict[str, Any] | None:
    """The live row under *key* as a dict, or ``None``."""
    _purge_expired(session, store)
    session.commit()
    record = session.get(store.model, key)
    return None if record is None else record.model_dump()


def cleanup_and_pop(session: Session, store: Store, key: str) -> dict[str, Any] | None:
    """The live row under *key* as a dict, deleted so a second call answers ``None``."""
    _purge_expired(session, store)
    record = session.get(store.model, key)
    if record is None:
        session.commit()
        return None
    values = record.model_dump()
    session.delete(record)
    session.commit()
    return values
