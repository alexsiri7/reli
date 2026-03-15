"""SQLite database setup and connection management."""

import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

_data_dir = os.environ.get("DATA_DIR", str(Path(__file__).parent))
DB_PATH = Path(_data_dir) / "reli.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_chat_history_usage(conn: sqlite3.Connection) -> None:
    """Add usage tracking columns to chat_history if missing."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_history)").fetchall()}
    for col, typedef in [
        ("prompt_tokens", "INTEGER DEFAULT 0"),
        ("completion_tokens", "INTEGER DEFAULT 0"),
        ("cost_usd", "REAL DEFAULT 0.0"),
        ("api_calls", "INTEGER DEFAULT 0"),
        ("model", "TEXT"),
    ]:
        if col not in cols:
            conn.execute(f"ALTER TABLE chat_history ADD COLUMN {col} {typedef}")


_DEFAULT_THING_TYPES = [
    ("task", "📋", None),
    ("note", "📝", None),
    ("project", "📁", None),
    ("idea", "💡", None),
    ("goal", "🎯", None),
    ("journal", "📓", None),
    ("person", "👤", None),
    ("place", "📍", None),
    ("event", "📅", None),
    ("concept", "🧠", None),
    ("reference", "🔗", None),
]


def _seed_thing_types(conn: sqlite3.Connection) -> None:
    """Seed default thing types if the table is empty."""
    count = conn.execute("SELECT COUNT(*) FROM thing_types").fetchone()[0]
    if count == 0:
        conn.executemany(
            "INSERT OR IGNORE INTO thing_types (id, name, icon, color) VALUES (?, ?, ?, ?)",
            [(name, name, icon, color) for name, icon, color in _DEFAULT_THING_TYPES],
        )


def _migrate_things_graph(conn: sqlite3.Connection) -> None:
    """Add surface and last_referenced columns to things if missing."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(things)").fetchall()}
    for col, typedef in [
        ("surface", "BOOLEAN DEFAULT 1"),
        ("last_referenced", "TIMESTAMP"),
    ]:
        if col not in cols:
            conn.execute(f"ALTER TABLE things ADD COLUMN {col} {typedef}")


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
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                api_calls INTEGER DEFAULT 0,
                model TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS thing_relationships (
                id TEXT PRIMARY KEY,
                from_thing_id TEXT NOT NULL,
                to_thing_id TEXT NOT NULL,
                relationship_type TEXT NOT NULL,
                metadata JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(from_thing_id) REFERENCES things(id) ON DELETE CASCADE,
                FOREIGN KEY(to_thing_id) REFERENCES things(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_things_checkin ON things(checkin_date);
            CREATE INDEX IF NOT EXISTS idx_things_active ON things(active);
            CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_history(session_id);
            CREATE INDEX IF NOT EXISTS idx_rel_from ON thing_relationships(from_thing_id);
            CREATE INDEX IF NOT EXISTS idx_rel_to ON thing_relationships(to_thing_id);
            CREATE INDEX IF NOT EXISTS idx_rel_type ON thing_relationships(relationship_type);

            CREATE TABLE IF NOT EXISTS thing_types (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                icon TEXT NOT NULL DEFAULT '📌',
                color TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

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
        _migrate_chat_history_usage(conn)
        _migrate_things_graph(conn)
        _seed_thing_types(conn)
