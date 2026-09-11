"""Flow state for the OAuth 2.1 authorization server in :mod:`backend.mcp_oauth` and the web view's sign-in.

Five tables, each a bounded store of short-lived rows keyed by an opaque string: the clients that
registered themselves, the MCP sign-ins in flight, the authorization codes waiting to be exchanged,
the refresh tokens issued — consumed ones kept until they expire, so a replay is recognised — and
the web view's sign-ins in flight. None of it is a Thing and nothing here touches the graph, so
nothing here is journalled — the journal records mutations of Things and relationships, and these
rows are the authorization server's bookkeeping (docs/auth-recovery.md §6.1).

Every access purges expired rows first, so a store never holds anything past its ``expires_at``,
and a store at its cap refuses with :class:`StoreFullError` rather than growing. Only
``mcp_refresh_tokens`` keeps rows that are no longer redeemable: a consumed token stays until it
expires, and counts against the cap until then. Client secrets are stored in plaintext, as they
were before the v4 rebuild: registration is single-tenant and a secret is useless without an
authorization code bound to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Text, delete, func, update
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
    """A refresh token issued by ``POST /oauth/token``.

    Live until one ``grant_type=refresh_token`` exchange consumes it, then kept until it expires so
    that presenting it again is recognised as a replay and revokes its family — every token rotated
    from the same authorization-code exchange, which all share ``family_id``.
    """

    __tablename__ = "mcp_refresh_tokens"

    refresh_token: str = _text(primary_key=True)
    subject: str = _text()
    email: str = _text()
    client_id: str = _text()
    scope: str = _text()
    family_id: str = _text()
    consumed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
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
    """The live row under *key* as a dict, deleted in the same statement.

    Read and delete are one ``DELETE … RETURNING``, so of any number of concurrent callers exactly
    one gets the row and every other answers ``None``.
    """
    _purge_expired(session, store)
    table = store.model.__table__  # type: ignore[attr-defined]
    row = (
        session.execute(
            delete(store.model)
            .where(table.c[store.primary_key] == key, table.c["expires_at"] > datetime.now(UTC))
            .returning(*table.c)
        )
        .mappings()
        .one_or_none()
    )
    session.commit()
    return None if row is None else dict(row)


def consume_refresh_token(session: Session, refresh_token: str) -> dict[str, Any] | None:
    """The live refresh token under *refresh_token* as a dict, marked consumed in the same statement.

    ``None`` when it is gone, expired, or already consumed — a replay, or a concurrent exchange
    that won. The row is kept, so :func:`cleanup_and_get` still finds it with ``consumed_at`` set.

    This is the one store function that does not commit: the rotation commits together with its
    replacement in :func:`cleanup_and_store`, and nothing may commit in between. A concurrent
    exchange of the same token blocks on this row's lock until that commit, then finds the token
    consumed, and its :func:`revoke_refresh_token_family` sees the replacement too. A commit
    between the two would leave the replacement alive after the revocation.
    """
    _purge_expired(session, mcp_refresh_tokens)
    table = McpRefreshTokenRecord.__table__  # type: ignore[attr-defined]
    now = datetime.now(UTC)
    row = (
        session.execute(
            update(McpRefreshTokenRecord)
            .where(table.c.refresh_token == refresh_token, table.c.consumed_at.is_(None), table.c.expires_at > now)
            .values(consumed_at=now)
            .returning(*table.c)
        )
        .mappings()
        .one_or_none()
    )
    session.flush()
    return None if row is None else dict(row)


def revoke_refresh_token_family(session: Session, family_id: str) -> int:
    """Delete every refresh token descended from one sign-in, consumed or live; the count deleted."""
    table = McpRefreshTokenRecord.__table__  # type: ignore[attr-defined]
    revoked = session.execute(
        delete(McpRefreshTokenRecord).where(table.c.family_id == family_id).returning(table.c.refresh_token)
    ).all()
    session.commit()
    return len(revoked)
