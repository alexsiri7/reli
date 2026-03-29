"""SQLModel engine and session — typed access layer for Phase 2+ migrations.

Provides a SQLAlchemy engine and ``get_session()`` dependency that Phase 2
query conversions will use.  The existing ``database.py`` (sqlite3) code
remains the primary data access path until each table is migrated.

**Table creation is intentionally NOT performed here.**  Tables are still
created and migrated by ``database.init_db()``.  This module only sets up
the SQLAlchemy connection so that Phase 2 can start using typed sessions.

Usage (Phase 2 routers / services):

    from sqlmodel import Session, select
    from backend.database_sqlmodel import get_session
    from backend.db_models import Thing

    def get_thing(thing_id: str, session: Session = Depends(get_session)):
        return session.get(Thing, thing_id)
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlmodel import Session, create_engine

from .config import settings

DB_PATH = Path(settings.DATA_DIR) / "reli.db"

# ``check_same_thread=False`` is required for SQLite when the engine is used
# across threads (e.g. FastAPI request workers).
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a SQLModel Session, commits on success."""
    with Session(engine) as session:
        yield session
