"""SQLModel engine and session management.

Provides ``get_session`` for dependency injection in FastAPI routes and a
module-level ``engine`` for direct use (e.g., ``create_all``).

The connection string comes from ``settings.database_url``:
- Empty DATABASE_URL → ``sqlite:///DATA_DIR/reli.db`` (default)
- Explicit DATABASE_URL → used as-is (e.g., Supabase Postgres)
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from .config import settings

_url = settings.database_url

# SQLite needs check_same_thread=False for FastAPI's threaded request handling.
_connect_args: dict = {"check_same_thread": False} if _url.startswith("sqlite") else {}

engine = create_engine(_url, connect_args=_connect_args, echo=False)

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


def init_sqlmodel_tables() -> None:
    """Create all tables registered in SQLModel metadata.

    No-op for tables that already exist (uses CREATE TABLE IF NOT EXISTS).
    """
    SQLModel.metadata.create_all(engine)
