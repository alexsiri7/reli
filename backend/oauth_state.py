"""Shared in-memory state for MCP OAuth flows.

Two stores are needed across two modules (routers/auth.py and routers/mcp_oauth.py):
  _mcp_oauth_sessions — maps server-generated Google state -> MCP client OAuth params
  _mcp_auth_codes     — maps short-lived auth codes -> user info + PKCE challenge

All mutable dicts are bounded: expired entries are lazily purged on every
store/retrieve, and each dict is hard-capped at MAX_ENTRIES_PER_DICT.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MAX_ENTRIES_PER_DICT = 10_000

# Lock protecting all mutable state dicts below against concurrent access
# from threadpool-dispatched sync endpoints.
_state_lock = threading.Lock()

# server_state -> {
#   client_state, redirect_uri, code_challenge, code_challenge_method,
#   client_id, scope, google_code_verifier, expires_at
# }
mcp_oauth_sessions: dict[str, dict] = {}

# auth_code -> {
#   user_id, email, code_challenge, code_challenge_method, redirect_uri, expires_at
# }
mcp_auth_codes: dict[str, dict] = {}

# client_id -> {
#   client_id, client_secret, redirect_uris, client_name, grant_types,
#   response_types, token_endpoint_auth_method, created_at
# }
mcp_registered_clients: dict[str, dict] = {}

# refresh_token -> {
#   user_id, email, client_id, scope, expires_at
# }
mcp_refresh_tokens: dict[str, dict] = {}


def _cleanup_expired(store: dict[str, dict]) -> None:
    """Remove entries whose ``expires_at`` is in the past.

    Entries may store ``expires_at`` as either a :class:`datetime` (timezone-aware)
    or a :class:`float` (Unix epoch).  Entries without ``expires_at`` (e.g.
    registered clients) are never evicted by this function.
    """
    now_ts = time.time()
    now_dt = datetime.now(timezone.utc)
    expired_keys = [k for k, v in store.items() if _is_expired(v, now_ts, now_dt)]
    for k in expired_keys:
        del store[k]
    if expired_keys:
        logger.debug("oauth_state: purged %d expired entries", len(expired_keys))


def _is_expired(entry: dict, now_ts: float, now_dt: datetime) -> bool:
    exp = entry.get("expires_at")
    if exp is None:
        return False
    if isinstance(exp, datetime):
        return now_dt > exp
    # numeric (epoch seconds)
    return now_ts > exp


class StoreFullError(Exception):
    """Raised when a bounded dict exceeds MAX_ENTRIES_PER_DICT after cleanup."""


def cleanup_and_store(store: dict[str, dict], key: str, value: dict) -> None:
    """Purge expired entries, enforce size cap, then insert *key*: *value*.

    Raises :class:`StoreFullError` if the store is still at capacity after
    purging expired entries.
    """
    with _state_lock:
        _cleanup_expired(store)
        if len(store) >= MAX_ENTRIES_PER_DICT:
            raise StoreFullError(f"OAuth state store is full ({MAX_ENTRIES_PER_DICT} entries)")
        store[key] = value


def cleanup_and_get(store: dict[str, dict], key: str) -> dict | None:
    """Purge expired entries, then return the entry for *key* (or ``None``)."""
    with _state_lock:
        _cleanup_expired(store)
        return store.get(key)


def cleanup_and_pop(store: dict[str, dict], key: str) -> dict | None:
    """Purge expired entries, then pop and return the entry for *key* (or ``None``)."""
    with _state_lock:
        _cleanup_expired(store)
        return store.pop(key, None)
