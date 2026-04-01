"""Legacy database helpers retained for test compatibility.

Production code uses SQLModel via ``db_engine.py`` and Alembic for migrations.
The ``db()`` context manager and ``DB_PATH`` are kept here because many test
files still use raw ``sqlite3`` connections for test setup and assertions.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import settings

DB_PATH = Path(settings.DATA_DIR) / "reli.db"


def get_connection() -> Any:
    """Return a raw sqlite3 connection (test utility).

    Returns ``sqlite3.Connection`` when STORAGE_BACKEND=sqlite (default),
    or ``supabase.Client`` when STORAGE_BACKEND=supabase.
    """
    if settings.STORAGE_BACKEND == "supabase":
        from .database_supabase import get_client

        return get_client()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db() -> Generator[Any, None, None]:
    """Yield a database handle — sqlite3.Connection or supabase.Client.

    Used by test files for raw SQL setup/assertions.  Production code
    should use ``db_engine.get_session()`` instead.
    """
    if settings.STORAGE_BACKEND == "supabase":
        from .database_supabase import supabase_db

        with supabase_db() as client:
            yield client
        return
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
