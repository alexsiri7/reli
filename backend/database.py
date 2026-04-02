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

from .config import settings

DB_PATH = Path(settings.DATA_DIR) / "reli.db"


@contextmanager
def db() -> Generator[sqlite3.Connection, None, None]:
    """Yield a raw sqlite3 connection for test setup/assertions.

    Production code should use ``db_engine.get_session()`` instead.
    """
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
