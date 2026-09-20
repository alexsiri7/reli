"""Flow state for the OAuth 2.1 authorization server in :mod:`backend.mcp_oauth` and the web view's sign-in.

Five tables, each a bounded store of short-lived rows keyed by an opaque string: the clients that
registered themselves, the MCP sign-ins in flight, the authorization codes waiting to be exchanged,
the refresh tokens issued — consumed ones kept until they expire, so a replay is recognised — and
the web view's sign-ins in flight. None of it is a Thing and nothing here touches the graph, so
nothing here is journalled — the journal records mutations of Things and relationships, and these
rows are the authorization server's bookkeeping (docs/auth-recovery.md §6.1).

Every access purges expired rows first, so a store never holds anything past its ``expires_at``,
and no store grows past its cap. At the cap the stores part ways: the three a caller without any
credential can write to — registrations, MCP sign-ins in flight, web sign-ins in flight — evict the
row nearest expiry to make room, so a flood can displace other unfinished flows but never lock the
owner out for longer than it lasts; the two only a signed-in account can write to — authorization
codes and refresh tokens — refuse with :class:`StoreFullError`, because evicting there would revoke a
live session to admit a new one. A registration lives an hour until a token is minted for it, then
as long as the refresh family it serves. Only ``mcp_refresh_tokens`` keeps rows that are no longer
redeemable: a consumed token stays until it expires, and counts against the cap until then.

Authorization codes and refresh tokens are stored as the SHA-256 digest of the value handed to the
client and looked up by the digest of the value presented (#1530), so a reader of the database or a
backup holds nothing redeemable, and the plaintext is never read back. Client secrets are stored in
plaintext, as they were before the v4 rebuild: registration is single-tenant and a secret is
useless without an authorization code or refresh token bound to it, which the same reader cannot
present.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Text, delete, func, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Session, SQLModel, select

logger = logging.getLogger(__name__)

MAX_ENTRIES = 10_000


def credential_digest(value: str) -> str:
    """What a store that ``hashes_keys`` stores *value* under; the hashing revision computes the same in SQL."""
    return hashlib.sha256(value.encode()).hexdigest()


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
    """An authorization code minted after a Google sign-in, waiting for ``POST /oauth/token``.

    Keyed by the code's digest, not the code.
    """

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
    from the same authorization-code exchange, which all share ``family_id``. Keyed by the token's
    digest, not the token.
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
    """One of the five tables, with the most live rows it may hold and what happens at that cap.

    An evicting store deletes the row nearest its ``expires_at`` to make room; one that does not
    evict raises :class:`StoreFullError`. For the session stores every row gets the same TTL at
    insert, so nearest expiry is oldest. For the registered clients it is what makes eviction safe:
    an unused registration has at most an hour left and a used one up to thirty days, so eviction
    reaches every unused one first — except a used client in its final hour, which a flood may
    displace up to an hour early; its connector re-authorises, the remedy it was about to need.

    A store that hashes keys stores each row under :func:`credential_digest` of its key and is read
    by the digest of the presented value, so the row holds nothing redeemable.
    """

    model: type[SQLModel]
    max_entries: int
    evicts: bool = False
    hashes_keys: bool = False

    @property
    def primary_key(self) -> str:
        return str(self.model.__table__.primary_key.columns.keys()[0])  # type: ignore[attr-defined]


# Whether a store evicts follows from who can write to it. Registrations, MCP sign-ins and web
# sign-ins are written by callers holding no credential, so a full store must make room rather
# than refuse — a refusal would let a flood lock the owner out for as long as the rows live. An
# authorization code exists only after the Google sign-in passed ALLOWED_EMAILS, and a refresh
# token only after that allowlist is re-checked at issuance, so nobody unauthenticated can fill
# those two; evicting from them would revoke a live session to admit a new one, and refusing the
# new one is the lesser harm. One hundred registrations is far more than one owner's connectors
# will ever hold at once.
#
# Whether a store hashes its keys follows from what the key redeems. An authorization code or a
# refresh token is the credential itself, so the row holds its digest. A client_id is public, and
# the two sign-in states are the OAuth ``state`` parameter: they travel in URLs and redeem nothing
# on their own, so those three stay keyed by the value.
mcp_registered_clients = Store(McpRegisteredClientRecord, max_entries=100, evicts=True)
mcp_oauth_sessions = Store(McpOAuthSessionRecord, max_entries=MAX_ENTRIES, evicts=True)
mcp_auth_codes = Store(McpAuthCodeRecord, max_entries=MAX_ENTRIES, hashes_keys=True)
mcp_refresh_tokens = Store(McpRefreshTokenRecord, max_entries=MAX_ENTRIES, hashes_keys=True)
web_oauth_sessions = Store(WebOAuthSessionRecord, max_entries=MAX_ENTRIES, evicts=True)


class StoreFullError(Exception):
    """The store is at its cap even after purging expired rows."""


def _purge_expired(session: Session, store: Store) -> None:
    session.execute(delete(store.model).where(store.model.expires_at <= datetime.now(UTC)))  # type: ignore[attr-defined]


def _stored_key(store: Store, key: str) -> str:
    return credential_digest(key) if store.hashes_keys else key


def cleanup_and_store(session: Session, store: Store, key: str, values: dict[str, Any]) -> None:
    """Insert *values* under *key*, replacing any row already there.

    The cap counts the rows other than *key*: replacing a row in a full store neither refuses nor
    evicts, and an eviction never removes the row about to be replaced.

    Raises:
        StoreFullError: The store holds ``max_entries`` live rows and does not evict.
    """
    key = _stored_key(store, key)
    _purge_expired(session, store)
    table = store.model.__table__  # type: ignore[attr-defined]
    pk = table.c[store.primary_key]
    others = session.exec(select(func.count()).select_from(store.model).where(pk != key)).one()
    if others >= store.max_entries:
        if not store.evicts:
            session.commit()
            raise StoreFullError(f"{table.name} is full ({store.max_entries} entries)")
        nearest_expiry = select(pk).where(pk != key).order_by(table.c.expires_at).limit(others - store.max_entries + 1)
        evicted = session.execute(
            delete(store.model).where(pk.in_(nearest_expiry)).returning(pk).execution_options(synchronize_session=False)
        ).all()
        logger.warning(
            "%s is full (%d entries): evicted %d row(s) nearest expiry", table.name, store.max_entries, len(evicted)
        )

    existing = session.get(store.model, key)
    if existing is not None:
        session.delete(existing)
        session.flush()
    session.add(store.model(**{store.primary_key: key, **values}))
    session.commit()


def cleanup_and_get(session: Session, store: Store, key: str) -> dict[str, Any] | None:
    """The live row under *key* as a dict, or ``None``."""
    key = _stored_key(store, key)
    _purge_expired(session, store)
    session.commit()
    record = session.get(store.model, key)
    return None if record is None else record.model_dump()


def cleanup_and_pop(session: Session, store: Store, key: str) -> dict[str, Any] | None:
    """The live row under *key* as a dict, deleted in the same statement.

    Read and delete are one ``DELETE … RETURNING``, so of any number of concurrent callers exactly
    one gets the row and every other answers ``None``.
    """
    key = _stored_key(store, key)
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


def extend_expiry(session: Session, store: Store, key: str, expires_at: datetime) -> None:
    """Move the row under *key* to expire at *expires_at* if that is later than it already does.

    Only ever later: a client the owner authorised twice serves two refresh families with different
    deadlines, and a rotation of the older one must not pull the client back below the newer. A
    missing *key* is a no-op.
    """
    key = _stored_key(store, key)
    table = store.model.__table__  # type: ignore[attr-defined]
    session.execute(
        update(store.model)
        .where(table.c[store.primary_key] == key)
        .values(expires_at=func.greatest(table.c.expires_at, expires_at, type_=DateTime(timezone=True)))
    )
    session.commit()


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
    refresh_token = _stored_key(mcp_refresh_tokens, refresh_token)
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
