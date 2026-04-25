"""SQLModel engine and session management.

Provides ``get_session`` for dependency injection in FastAPI routes and a
module-level ``engine`` for direct use (e.g., ``create_all``).

The connection string comes from ``settings.database_url``:
- Empty DATABASE_URL → ``sqlite:///DATA_DIR/reli.db`` (default)
- Explicit DATABASE_URL → used as-is (e.g., Supabase Postgres)
"""

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import datetime
from typing import Any

from sqlalchemy import event
from sqlmodel import Session, create_engine, or_

from .config import settings


def _json_default(obj: Any) -> Any:
    """Custom JSON serializer for SQLAlchemy JSON/JSONB columns.

    Converts types that the stdlib ``json`` module cannot handle:
    - ``datetime`` → ISO-8601 string (e.g. "2026-04-25T12:00:00+00:00")
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def json_serializer(value: Any) -> str:
    """Drop-in replacement for ``json.dumps`` used by SQLAlchemy engines."""
    return json.dumps(value, default=_json_default)


# ---------------------------------------------------------------------------
# Pure helpers (no engine dependency) — defined early so they're available even
# if engine creation fails and leaves the module partially initialised in
# sys.modules.  This prevents the ImportError reported in GH #505 / #506.
# ---------------------------------------------------------------------------

def user_filter_clause(user_id_column: Any, user_id: str) -> Any:
    """Return a SQLAlchemy filter clause for user-scoped queries.

    When *user_id* is empty (auth disabled), returns ``True`` (no filtering).
    Otherwise returns ``(column == user_id) | (column IS NULL)``.

    Usage::

        stmt = select(ThingRecord).where(
            ThingRecord.active == True,
            user_filter_clause(ThingRecord.user_id, user_id),
        )
    """
    if not user_id:
        return True  # no filter
    return or_(user_id_column == user_id, user_id_column.is_(None))  # type: ignore[union-attr]


def user_filter_text(user_id: str, table_alias: str = "", param_name: str = "uf_uid") -> tuple[str, dict]:
    """Return a text()-compatible SQL WHERE fragment and params dict for user filtering.

    Uses ``:param`` style placeholders for use with ``session.execute(text(...))``.
    """
    if not user_id:
        return "", {}
    prefix = f"{table_alias}." if table_alias else ""
    return f" AND ({prefix}user_id = :{param_name} OR {prefix}user_id IS NULL)", {param_name: user_id}


# ---------------------------------------------------------------------------
# Engine and session — these touch the database and can fail at import time.
# ---------------------------------------------------------------------------

_url = settings.database_url

# SQLite needs check_same_thread=False for FastAPI's threaded request handling.
_connect_args: dict = {"check_same_thread": False} if _url.startswith("sqlite") else {}

_pool_args: dict = {}
if not _url.startswith("sqlite"):
    # Limit pool size to stay within Supabase free-tier connection limits.
    _pool_args = {"pool_size": 3, "max_overflow": 2, "pool_pre_ping": True}

engine = create_engine(_url, connect_args=_connect_args, echo=False, json_serializer=json_serializer, **_pool_args)

# SQLite-specific PRAGMAs (WAL mode, foreign keys, busy timeout).
if _url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        # Wait up to 5 s when the database is locked instead of failing immediately.
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def get_session() -> Generator[Session, None, None]:
    """Yield a SQLModel session. Use as a FastAPI ``Depends()`` or context manager."""
    with Session(engine) as session:
        yield session

