"""SQLite database setup and connection management."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import os

_data_dir = os.environ.get("DATA_DIR", str(Path(__file__).parent))
DB_PATH = Path(_data_dir) / "reli.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist."""
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS things (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                type_hint TEXT,
                parent_id TEXT,
                checkin_date TIMESTAMP,
                priority INTEGER DEFAULT 3,
                active BOOLEAN DEFAULT 1,
                data JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(parent_id) REFERENCES things(id)
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                applied_changes JSON,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_things_checkin ON things(checkin_date);
            CREATE INDEX IF NOT EXISTS idx_things_active ON things(active);
            CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_history(session_id);

            CREATE TABLE IF NOT EXISTS google_tokens (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                token_uri TEXT NOT NULL,
                client_id TEXT NOT NULL,
                client_secret TEXT NOT NULL,
                expiry TEXT,
                scopes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
