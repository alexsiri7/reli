"""SQLModel engine and session management.

Provides ``get_session`` for dependency injection in FastAPI routes and a
module-level ``engine`` for direct use (e.g., ``create_all``).

The connection string comes from ``settings.database_url``:
- Empty DATABASE_URL → ``sqlite:///DATA_DIR/reli.db`` (default)
- Explicit DATABASE_URL → used as-is (e.g., Supabase Postgres)
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlmodel import Session, SQLModel, create_engine, or_

from .config import settings


# ---------------------------------------------------------------------------
# Pure helpers (no engine dependency) — defined early so they're available even
# if engine creation fails and leaves the module partially initialised in
# sys.modules.  This prevents the ImportError reported in GH #505 / #506.
# ---------------------------------------------------------------------------

def user_filter_clause(user_id_column: Any, user_id: str) -> Any:
    """Return a SQLAlchemy filter clause equivalent to the legacy ``user_filter()`` helper.

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

    Like ``auth.user_filter()`` but uses ``:param`` style placeholders for
    use with ``session.execute(text(...))``.
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

engine = create_engine(_url, connect_args=_connect_args, echo=False, **_pool_args)

# SQLite-specific PRAGMAs (WAL mode, foreign keys).
if _url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_session() -> Generator[Session, None, None]:
    """Yield a SQLModel session. Use as a FastAPI ``Depends()`` or context manager."""
    with Session(engine) as session:
        yield session


def _exec(session: "Session", sql: Any, params: Any = ()) -> Any:
    """Execute raw SQL via a SQLModel session, converting positional ``?`` params
    to SQLAlchemy ``:param`` style.

    This is a migration helper so legacy code using ``conn.execute(sql, params)``
    can be mechanically converted to ``_exec(session, sql, params)`` with
    minimal diff churn.  New code should use ``session.execute(text(...), {...})``
    directly.
    """
    from sqlalchemy import text as _text

    if params:
        # Convert ? placeholders to :p0, :p1, ... and build dict
        parts = sql.split("?")
        if len(parts) - 1 != len(params):
            raise ValueError(
                f"Parameter count mismatch: {len(parts) - 1} placeholders vs {len(params)} params"
            )
        named_sql = parts[0]
        param_dict: dict[str, Any] = {}
        for i, part in enumerate(parts[1:]):
            key = f"_p{i}"
            named_sql += f":{key}{part}"
            param_dict[key] = params[i]
        return session.execute(_text(named_sql), param_dict)
    return session.execute(_text(sql))


def init_sqlmodel_tables() -> None:
    """Deprecated: schema is now managed by Alembic migrations.

    Run ``alembic upgrade head`` instead.  This function is kept as a
    no-op so existing call sites don't break during the transition.
    """
    import logging
    import warnings

    msg = (
        "init_sqlmodel_tables() is deprecated — schema is managed by Alembic. "
        "Run 'alembic upgrade head' instead."
    )
    warnings.warn(msg, DeprecationWarning, stacklevel=2)
    logging.getLogger(__name__).warning(msg)
