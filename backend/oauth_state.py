"""Persistent state for MCP OAuth flows, backed by SQLite.

Replaces the former in-memory dicts with database-backed stores so that
state survives server restarts and is shared across workers.

Public API (unchanged):
  cleanup_and_store(store, key, value_dict)
  cleanup_and_get(store, key) -> dict | None
  cleanup_and_pop(store, key) -> dict | None
  StoreFullError

Store handles (unchanged names, now opaque _Store objects):
  mcp_oauth_sessions, mcp_auth_codes, mcp_registered_clients,
  mcp_refresh_tokens, gmail_oauth_states

Plain ``dict`` stores are still supported for callers that maintain their
own in-memory state (e.g. ``_pending_flows`` in auth.py).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from . import db_engine as _engine_module
from .db_models import (
    GmailOAuthStateRecord,
    McpAuthCodeRecord,
    McpOAuthSessionRecord,
    McpRefreshTokenRecord,
    McpRegisteredClientRecord,
)

logger = logging.getLogger(__name__)

MAX_ENTRIES_PER_DICT = 10_000

# Fields stored as JSON-encoded strings in the DB that must be deserialized
# back to lists when returning dicts to callers.
_JSON_LIST_FIELDS = frozenset({"redirect_uris", "grant_types", "response_types"})

# Lock protecting in-memory dict stores (legacy callers like _pending_flows).
_state_lock = threading.Lock()


@dataclass(frozen=True)
class _Store:
    """Opaque handle identifying a DB-backed OAuth state table."""

    model: type
    pk_field: str
    json_fields: frozenset[str] = field(default_factory=frozenset)


# Store handles — callers import these by name exactly as before.
mcp_oauth_sessions = _Store(model=McpOAuthSessionRecord, pk_field="server_state")
mcp_auth_codes = _Store(model=McpAuthCodeRecord, pk_field="auth_code")
mcp_registered_clients = _Store(
    model=McpRegisteredClientRecord,
    pk_field="client_id",
    json_fields=_JSON_LIST_FIELDS,
)
mcp_refresh_tokens = _Store(model=McpRefreshTokenRecord, pk_field="refresh_token")
gmail_oauth_states = _Store(model=GmailOAuthStateRecord, pk_field="user_id")


class StoreFullError(Exception):
    """Raised when a bounded store exceeds MAX_ENTRIES_PER_DICT after cleanup."""


# ---------------------------------------------------------------------------
# In-memory helpers (legacy — for plain dict stores like _pending_flows)
# ---------------------------------------------------------------------------


def _is_expired(entry: dict, now_ts: float, now_dt: datetime) -> bool:
    exp = entry.get("expires_at")
    if exp is None:
        return False
    if isinstance(exp, datetime):
        return now_dt > exp
    return now_ts > exp


def _cleanup_expired(store: dict[str, dict]) -> None:
    now_ts = time.time()
    now_dt = datetime.now(timezone.utc)
    expired_keys = [k for k, v in store.items() if _is_expired(v, now_ts, now_dt)]
    for k in expired_keys:
        del store[k]
    if expired_keys:
        logger.debug("oauth_state: purged %d expired entries", len(expired_keys))


def _dict_cleanup_and_store(store: dict[str, dict], key: str, value: dict) -> None:
    with _state_lock:
        _cleanup_expired(store)
        if len(store) >= MAX_ENTRIES_PER_DICT:
            raise StoreFullError(f"OAuth state store is full ({MAX_ENTRIES_PER_DICT} entries)")
        store[key] = value


def _dict_cleanup_and_get(store: dict[str, dict], key: str) -> dict | None:
    with _state_lock:
        _cleanup_expired(store)
        return store.get(key)


def _dict_cleanup_and_pop(store: dict[str, dict], key: str) -> dict | None:
    with _state_lock:
        _cleanup_expired(store)
        return store.pop(key, None)


# ---------------------------------------------------------------------------
# DB-backed helpers
# ---------------------------------------------------------------------------


def _expires_at_to_epoch(value: Any) -> float:
    """Normalize an expires_at value to a float Unix epoch."""
    if isinstance(value, datetime):
        return value.timestamp()
    return float(value)


def _expires_at_to_datetime(epoch: float) -> datetime:
    """Convert a float Unix epoch back to a timezone-aware datetime."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def _purge_expired(session: Session, store: _Store) -> int:
    """Delete expired rows from *store*'s table. Returns count deleted."""
    now = time.time()
    stmt = select(store.model).where(store.model.expires_at <= now)  # type: ignore[attr-defined]
    expired = session.exec(stmt).all()
    for row in expired:
        session.delete(row)
    if expired:
        session.flush()
        logger.debug("oauth_state: purged %d expired entries from %s", len(expired), store.model.__tablename__)
    return len(expired)


def _record_to_dict(record: Any, store: _Store) -> dict:
    """Convert a SQLModel record to a plain dict, deserializing JSON fields."""
    d: dict[str, Any] = {}
    for col in record.__table__.columns:
        val = getattr(record, col.key)
        if col.key in store.json_fields:
            val = json.loads(val)
        d[col.key] = val
    # Convert expires_at back to datetime for backward compatibility with
    # callers that compare datetime.now(timezone.utc) > entry["expires_at"].
    if "expires_at" in d:
        d["expires_at"] = _expires_at_to_datetime(d["expires_at"])
    return d


def _dict_to_kwargs(store: _Store, key: str, value: dict) -> dict:
    """Build keyword arguments for creating a SQLModel record from a value dict."""
    kwargs: dict[str, Any] = {}
    columns = {col.key for col in store.model.__table__.columns}  # type: ignore[attr-defined]
    for col_name in columns:
        if col_name == store.pk_field:
            kwargs[col_name] = key
        elif col_name in value:
            val = value[col_name]
            if col_name in store.json_fields and isinstance(val, list):
                val = json.dumps(val)
            elif col_name == "expires_at":
                val = _expires_at_to_epoch(val)
            kwargs[col_name] = val
    return kwargs


def _db_cleanup_and_store(store: _Store, key: str, value: dict) -> None:
    with Session(_engine_module.engine) as session:
        _purge_expired(session, store)
        count_stmt = select(store.model)  # type: ignore[arg-type]
        live_count = len(session.exec(count_stmt).all())
        if live_count >= MAX_ENTRIES_PER_DICT:
            raise StoreFullError(f"OAuth state store is full ({MAX_ENTRIES_PER_DICT} entries)")

        kwargs = _dict_to_kwargs(store, key, value)
        existing = session.get(store.model, key)
        if existing:
            session.delete(existing)
            session.flush()
        record = store.model(**kwargs)
        session.add(record)
        session.commit()


def _db_cleanup_and_get(store: _Store, key: str) -> dict | None:
    with Session(_engine_module.engine) as session:
        _purge_expired(session, store)
        session.commit()
        record = session.get(store.model, key)
        if record is None:
            return None
        return _record_to_dict(record, store)


def _db_cleanup_and_pop(store: _Store, key: str) -> dict | None:
    with Session(_engine_module.engine) as session:
        _purge_expired(session, store)
        record = session.get(store.model, key)
        if record is None:
            session.commit()
            return None
        result = _record_to_dict(record, store)
        session.delete(record)
        session.commit()
        return result


# ---------------------------------------------------------------------------
# Public API — dispatches to DB or in-memory based on store type
# ---------------------------------------------------------------------------


def cleanup_and_store(store: _Store | dict[str, dict], key: str, value: dict) -> None:
    """Purge expired entries, enforce size cap, then insert *key*: *value*.

    Raises :class:`StoreFullError` if the store is still at capacity after
    purging expired entries.
    """
    if isinstance(store, dict):
        _dict_cleanup_and_store(store, key, value)
    else:
        _db_cleanup_and_store(store, key, value)


def cleanup_and_get(store: _Store | dict[str, dict], key: str) -> dict | None:
    """Purge expired entries, then return the entry for *key* (or ``None``)."""
    if isinstance(store, dict):
        return _dict_cleanup_and_get(store, key)
    return _db_cleanup_and_get(store, key)


def cleanup_and_pop(store: _Store | dict[str, dict], key: str) -> dict | None:
    """Purge expired entries, then pop and return the entry for *key* (or ``None``)."""
    if isinstance(store, dict):
        return _dict_cleanup_and_pop(store, key)
    return _db_cleanup_and_pop(store, key)
