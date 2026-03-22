"""Database setup and connection management.

Supports two backends controlled by ``settings.STORAGE_BACKEND``:

* ``sqlite`` (default) — local SQLite file at ``DATA_DIR/reli.db``
* ``supabase`` — remote Supabase/Postgres via ``supabase-py``
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
    """Return a database connection.

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
    """Yield a database handle — sqlite3.Connection or supabase.Client."""
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
    """Add surface, last_referenced, and open_questions columns to things if missing."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(things)").fetchall()}
    for col, typedef in [
        ("surface", "BOOLEAN DEFAULT 1"),
        ("last_referenced", "TIMESTAMP"),
        ("open_questions", "JSON"),
    ]:
        if col not in cols:
            conn.execute(f"ALTER TABLE things ADD COLUMN {col} {typedef}")


def _migrate_sweep_findings_snooze(conn: sqlite3.Connection) -> None:
    """Add snoozed_until column to sweep_findings if missing."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sweep_findings)").fetchall()}
    if "snoozed_until" not in cols:
        conn.execute("ALTER TABLE sweep_findings ADD COLUMN snoozed_until TIMESTAMP")


def _migrate_add_users(conn: sqlite3.Connection) -> None:
    """Create users table and add user_id columns to existing tables."""
    # 1. Create users table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            google_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            picture TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 2. Add user_id column to existing tables (migration-safe ALTER TABLE)
    for table in ("things", "chat_history", "sweep_findings", "usage_log"):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "user_id" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT REFERENCES users(id)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_user_id ON {table}(user_id)")

    # 3. Backfill usage_log.user_id from chat_history for pre-migration rows
    conn.execute("""
        UPDATE usage_log SET user_id = (
            SELECT ch.user_id FROM chat_history ch
            WHERE ch.session_id = usage_log.session_id
              AND ch.user_id IS NOT NULL
            LIMIT 1
        ) WHERE usage_log.user_id IS NULL
    """)


def _migrate_google_tokens_multi_user(conn: sqlite3.Connection) -> None:
    """Refactor google_tokens to support multiple users and services.

    Adds user_id and service columns; migrates existing single-user row
    to the new schema. Removes the id=1 constraint by creating a new table.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(google_tokens)").fetchall()}

    if "user_id" in cols:
        return  # Already migrated

    # Preserve existing token data
    existing = conn.execute("SELECT * FROM google_tokens").fetchall()

    # Drop old table and create new schema
    conn.execute("DROP TABLE IF EXISTS google_tokens")
    conn.execute("""
        CREATE TABLE google_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT REFERENCES users(id),
            service TEXT NOT NULL DEFAULT 'calendar',
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            token_uri TEXT NOT NULL,
            client_id TEXT NOT NULL,
            client_secret TEXT NOT NULL,
            expiry TEXT,
            scopes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, service)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_google_tokens_user_id ON google_tokens(user_id)")

    # Re-insert existing tokens (user_id=NULL until user system is wired up)
    for row in existing:
        conn.execute(
            """INSERT INTO google_tokens
               (user_id, service, access_token, refresh_token, token_uri,
                client_id, client_secret, expiry, scopes, created_at, updated_at)
               VALUES (NULL, 'calendar', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["access_token"],
                row["refresh_token"],
                row["token_uri"],
                row["client_id"],
                row["client_secret"],
                row["expiry"],
                row["scopes"],
                row["created_at"],
                row["updated_at"],
            ),
        )


def _migrate_user_settings(conn: sqlite3.Connection) -> None:
    """Create user_settings table for per-user configuration (API keys, models)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL REFERENCES users(id),
            key TEXT NOT NULL,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, key)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_settings_user ON user_settings(user_id)")


def _migrate_backfill_null_user_ids(conn: sqlite3.Connection) -> None:
    """Backfill NULL user_id in things/chat_history/sweep_findings to the first user.

    Things created before multi-user auth have user_id=NULL, which causes
    user_filter queries to miss them (404 on context thing links).
    """
    first_user = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    if not first_user:
        return  # No users yet — nothing to backfill
    uid = first_user["id"]
    for table in ("things", "chat_history", "sweep_findings"):
        conn.execute(f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL", (uid,))


def _migrate_sweep_runs(conn: sqlite3.Connection) -> None:
    """Create sweep_runs table for logging sweep execution history."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sweep_runs (
            id TEXT PRIMARY KEY,
            user_id TEXT REFERENCES users(id),
            status TEXT NOT NULL DEFAULT 'running',
            candidates_found INTEGER DEFAULT 0,
            findings_created INTEGER DEFAULT 0,
            model TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0,
            error TEXT,
            started_at TIMESTAMP NOT NULL,
            completed_at TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sweep_runs_user ON sweep_runs(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sweep_runs_started ON sweep_runs(started_at)")


def _migrate_morning_briefings(conn: sqlite3.Connection) -> None:
    """Create morning_briefings table for pre-generated briefing storage."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS morning_briefings (
            id TEXT PRIMARY KEY,
            user_id TEXT REFERENCES users(id),
            briefing_date TEXT NOT NULL,
            content JSON NOT NULL,
            generated_at TIMESTAMP NOT NULL,
            UNIQUE(user_id, briefing_date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_morning_briefings_user ON morning_briefings(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_morning_briefings_date ON morning_briefings(briefing_date)")


def _migrate_merge_history(conn: sqlite3.Connection) -> None:
    """Create merge_history table to track Thing merges."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS merge_history (
            id TEXT PRIMARY KEY,
            keep_id TEXT NOT NULL,
            remove_id TEXT NOT NULL,
            keep_title TEXT NOT NULL,
            remove_title TEXT NOT NULL,
            merged_data JSON,
            triggered_by TEXT NOT NULL DEFAULT 'api',
            user_id TEXT REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_merge_history_keep ON merge_history(keep_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_merge_history_created ON merge_history(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_merge_history_user ON merge_history(user_id)")


def _migrate_conversation_summaries(conn: sqlite3.Connection) -> None:
    """Create conversation_summaries table for compressed conversation history."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL REFERENCES users(id),
            summary_text TEXT NOT NULL,
            messages_summarized_up_to INTEGER NOT NULL,
            token_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_summaries_user ON conversation_summaries(user_id)")


def get_latest_summary(user_id: str) -> dict[str, Any] | None:
    """Get the most recent conversation summary for a user.

    Returns a dict with id, summary_text, messages_summarized_up_to, token_count,
    created_at, or None if no summary exists.
    """
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM conversation_summaries WHERE user_id = ? ORDER BY messages_summarized_up_to DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def create_summary(
    user_id: str,
    summary_text: str,
    messages_summarized_up_to: int,
    token_count: int = 0,
) -> int:
    """Create a new conversation summary. Returns the new row ID."""
    with db() as conn:
        cursor = conn.execute(
            "INSERT INTO conversation_summaries"
            " (user_id, summary_text, messages_summarized_up_to, token_count)"
            " VALUES (?, ?, ?, ?)",
            (user_id, summary_text, messages_summarized_up_to, token_count),
        )
        row_id: int | None = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("INSERT into conversation_summaries failed to return lastrowid")
        return row_id


def get_messages_since_summary(user_id: str) -> list[dict[str, Any]]:
    """Get chat messages for a user since their last summary.

    Returns messages ordered chronologically. If no summary exists,
    returns all messages for the user.
    """
    latest = get_latest_summary(user_id)
    with db() as conn:
        if latest:
            rows = conn.execute(
                "SELECT id, session_id, role, content, timestamp FROM chat_history"
                " WHERE user_id = ? AND id > ?"
                " ORDER BY id ASC",
                (user_id, latest["messages_summarized_up_to"]),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, session_id, role, content, timestamp FROM chat_history WHERE user_id = ? ORDER BY id ASC",
                (user_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_message_count_since_summary(user_id: str) -> int:
    """Count messages since the last summary for a user."""
    latest = get_latest_summary(user_id)
    with db() as conn:
        if latest:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM chat_history WHERE user_id = ? AND id > ?",
                (user_id, latest["messages_summarized_up_to"]),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM chat_history WHERE user_id = ?",
                (user_id,),
            ).fetchone()
    return row["cnt"] if row else 0


def _migrate_connection_suggestions(conn: sqlite3.Connection) -> None:
    """Create connection_suggestions table for auto-connect feature."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS connection_suggestions (
            id TEXT PRIMARY KEY,
            from_thing_id TEXT NOT NULL,
            to_thing_id TEXT NOT NULL,
            suggested_relationship_type TEXT NOT NULL,
            reason TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            user_id TEXT REFERENCES users(id),
            FOREIGN KEY(from_thing_id) REFERENCES things(id) ON DELETE CASCADE,
            FOREIGN KEY(to_thing_id) REFERENCES things(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conn_sugg_status ON connection_suggestions(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conn_sugg_from ON connection_suggestions(from_thing_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conn_sugg_to ON connection_suggestions(to_thing_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conn_sugg_user ON connection_suggestions(user_id)")


def clean_orphan_relationships() -> tuple[int, list[str]]:
    """Delete relationships where from_thing_id or to_thing_id doesn't exist.

    Returns (deleted_count, list_of_deleted_ids).
    """
    if settings.STORAGE_BACKEND == "supabase":
        from .database_supabase import clean_orphan_relationships_supabase

        return clean_orphan_relationships_supabase()

    import logging

    logger = logging.getLogger(__name__)
    with db() as conn:
        orphan_rows = conn.execute(
            "SELECT r.id FROM thing_relationships r"
            " WHERE r.from_thing_id NOT IN (SELECT id FROM things)"
            "    OR r.to_thing_id NOT IN (SELECT id FROM things)"
        ).fetchall()
        orphan_ids = [row["id"] for row in orphan_rows]
        if orphan_ids:
            placeholders = ",".join("?" * len(orphan_ids))
            conn.execute(f"DELETE FROM thing_relationships WHERE id IN ({placeholders})", orphan_ids)
            logger.info("Cleaned %d orphan relationship(s): %s", len(orphan_ids), orphan_ids)
    return len(orphan_ids), orphan_ids


def init_db() -> None:
    """Create tables if they don't exist."""
    if settings.STORAGE_BACKEND == "supabase":
        from .database_supabase import init_db_supabase

        init_db_supabase()
        return
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

            CREATE TABLE IF NOT EXISTS sweep_findings (
                id TEXT PRIMARY KEY,
                thing_id TEXT,
                finding_type TEXT NOT NULL,
                message TEXT NOT NULL,
                priority INTEGER DEFAULT 2,
                dismissed BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                FOREIGN KEY(thing_id) REFERENCES things(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_sweep_active ON sweep_findings(dismissed, expires_at);
            CREATE INDEX IF NOT EXISTS idx_sweep_thing ON sweep_findings(thing_id);

            CREATE TABLE IF NOT EXISTS usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_usage_log_timestamp ON usage_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_usage_log_session ON usage_log(session_id);

            CREATE TABLE IF NOT EXISTS chat_message_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_message_id INTEGER NOT NULL,
                stage TEXT,
                model TEXT NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                FOREIGN KEY(chat_message_id) REFERENCES chat_history(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_chat_msg_usage_msg ON chat_message_usage(chat_message_id);

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                google_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                picture TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS google_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT REFERENCES users(id),
                service TEXT NOT NULL DEFAULT 'calendar',
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                token_uri TEXT NOT NULL,
                client_id TEXT NOT NULL,
                client_secret TEXT NOT NULL,
                expiry TEXT,
                scopes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, service)
            );
        """)
        _migrate_chat_history_usage(conn)
        _migrate_things_graph(conn)
        _migrate_sweep_findings_snooze(conn)
        _migrate_add_users(conn)
        _migrate_google_tokens_multi_user(conn)
        _migrate_backfill_null_user_ids(conn)
        _migrate_user_settings(conn)
        _migrate_merge_history(conn)
        _migrate_sweep_runs(conn)
        _migrate_connection_suggestions(conn)
        _migrate_morning_briefings(conn)
        _migrate_conversation_summaries(conn)
        _seed_thing_types(conn)
