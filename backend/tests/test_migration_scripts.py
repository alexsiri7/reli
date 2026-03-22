"""Tests for SQLite-to-Supabase migration scripts.

Tests the export, import, and verify scripts using in-memory SQLite
and mocked Supabase client.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.migrate_export import EXPORT_TABLES, export_table
from scripts.migrate_import import (
    ADD_COLUMNS,
    COLUMN_MAP,
    DROP_COLUMNS,
    IDENTITY_TABLES,
    _transform_row,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sqlite_db(tmp_path):
    """Create an in-memory SQLite DB with minimal schema and seed data."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Create minimal tables
    conn.executescript("""
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            google_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            picture TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE thing_types (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            icon TEXT NOT NULL DEFAULT '📌',
            color TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE things (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            type_hint TEXT,
            parent_id TEXT,
            checkin_date TIMESTAMP,
            priority INTEGER DEFAULT 3,
            active BOOLEAN DEFAULT 1,
            surface BOOLEAN DEFAULT 1,
            data JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_referenced TIMESTAMP,
            open_questions JSON,
            user_id TEXT
        );

        CREATE TABLE thing_relationships (
            id TEXT PRIMARY KEY,
            from_thing_id TEXT NOT NULL,
            to_thing_id TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            metadata JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE chat_history (
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
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id TEXT
        );

        CREATE TABLE chat_message_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_message_id INTEGER NOT NULL,
            stage TEXT,
            model TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0
        );

        CREATE TABLE conversation_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            summary_text TEXT NOT NULL,
            messages_summarized_up_to INTEGER NOT NULL,
            token_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE sweep_findings (
            id TEXT PRIMARY KEY,
            thing_id TEXT,
            finding_type TEXT NOT NULL,
            message TEXT NOT NULL,
            priority INTEGER DEFAULT 2,
            dismissed BOOLEAN DEFAULT 0,
            snoozed_until TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            user_id TEXT
        );

        CREATE TABLE usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id TEXT
        );

        CREATE TABLE connection_suggestions (
            id TEXT PRIMARY KEY,
            from_thing_id TEXT NOT NULL,
            to_thing_id TEXT NOT NULL,
            suggested_relationship_type TEXT NOT NULL,
            reason TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            user_id TEXT
        );

        CREATE TABLE google_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            service TEXT NOT NULL DEFAULT 'calendar',
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

        CREATE TABLE user_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE merge_history (
            id TEXT PRIMARY KEY,
            keep_id TEXT NOT NULL,
            remove_id TEXT NOT NULL,
            keep_title TEXT NOT NULL,
            remove_title TEXT NOT NULL,
            merged_data JSON,
            triggered_by TEXT NOT NULL DEFAULT 'api',
            user_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE sweep_runs (
            id TEXT PRIMARY KEY,
            user_id TEXT,
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
        );

        CREATE TABLE morning_briefings (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            briefing_date TEXT NOT NULL,
            content JSON NOT NULL,
            generated_at TIMESTAMP NOT NULL
        );
    """)

    # Seed data
    conn.execute(
        "INSERT INTO users VALUES ('u1', 'test@example.com', 'g1', 'Test User', NULL, datetime('now'), datetime('now'))"
    )
    conn.execute(
        "INSERT INTO thing_types VALUES ('task', 'task', '📋', NULL, datetime('now'))"
    )
    conn.execute(
        "INSERT INTO things VALUES ('t1', 'My Task', 'task', NULL, NULL, 3, 1, 1, "
        "'{\"notes\": \"hello\"}', datetime('now'), datetime('now'), NULL, NULL, 'u1')"
    )
    conn.execute(
        "INSERT INTO thing_relationships VALUES ('r1', 't1', 't1', 'self_ref', NULL, datetime('now'))"
    )
    conn.execute(
        "INSERT INTO chat_history (session_id, role, content, user_id) "
        "VALUES ('s1', 'user', 'hello', 'u1')"
    )
    conn.execute(
        "INSERT INTO conversation_summaries (user_id, summary_text, messages_summarized_up_to, token_count) "
        "VALUES ('u1', 'A summary', 5, 100)"
    )
    conn.execute(
        "INSERT INTO sweep_findings VALUES ('sf1', 't1', 'stale_task', 'Task is stale', 2, 0, NULL, datetime('now'), NULL, 'u1')"
    )
    conn.commit()
    yield conn, db_path
    conn.close()


@pytest.fixture()
def export_dir(tmp_path, sqlite_db):
    """Export the test database to JSON files."""
    conn, _ = sqlite_db
    out_dir = tmp_path / "export"
    out_dir.mkdir()

    for table in EXPORT_TABLES:
        try:
            rows = export_table(conn, table)
        except Exception:
            rows = []
        (out_dir / f"{table}.json").write_text(json.dumps(rows, default=str))

    # Write a manifest
    manifest = {"tables": {}, "vectors": {"count": 0}}
    for table in EXPORT_TABLES:
        rows = json.loads((out_dir / f"{table}.json").read_text())
        manifest["tables"][table] = len(rows)
    (out_dir / "manifest.json").write_text(json.dumps(manifest))

    # Write a minimal vectors file
    vectors = [
        {
            "id": "t1",
            "embedding": [0.1] * 3072,
            "document": "My Task | My Task | type: task",
            "metadata": {"type_hint": "task", "active": 1, "user_id": "u1"},
        }
    ]
    (out_dir / "vectors.json").write_text(json.dumps(vectors))
    manifest["vectors"]["count"] = 1
    (out_dir / "manifest.json").write_text(json.dumps(manifest))

    return out_dir


# ---------------------------------------------------------------------------
# Export Tests
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_users(self, sqlite_db):
        conn, _ = sqlite_db
        rows = export_table(conn, "users")
        assert len(rows) == 1
        assert rows[0]["email"] == "test@example.com"
        assert rows[0]["name"] == "Test User"

    def test_export_things(self, sqlite_db):
        conn, _ = sqlite_db
        rows = export_table(conn, "things")
        assert len(rows) == 1
        assert rows[0]["id"] == "t1"
        assert rows[0]["title"] == "My Task"

    def test_export_things_data_is_string(self, sqlite_db):
        conn, _ = sqlite_db
        rows = export_table(conn, "things")
        # SQLite stores JSON as text
        assert isinstance(rows[0]["data"], str)
        assert json.loads(rows[0]["data"]) == {"notes": "hello"}

    def test_export_conversation_summaries(self, sqlite_db):
        conn, _ = sqlite_db
        rows = export_table(conn, "conversation_summaries")
        assert len(rows) == 1
        assert rows[0]["summary_text"] == "A summary"
        assert rows[0]["messages_summarized_up_to"] == 5
        assert rows[0]["token_count"] == 100

    def test_export_all_tables(self, sqlite_db):
        conn, _ = sqlite_db
        for table in EXPORT_TABLES:
            rows = export_table(conn, table)
            assert isinstance(rows, list)

    def test_export_empty_table(self, sqlite_db):
        conn, _ = sqlite_db
        rows = export_table(conn, "morning_briefings")
        assert rows == []


# ---------------------------------------------------------------------------
# Transform Tests
# ---------------------------------------------------------------------------


class TestTransformRow:
    def test_conversation_summaries_column_mapping(self):
        row = {
            "id": 1,
            "user_id": "u1",
            "summary_text": "A summary",
            "messages_summarized_up_to": 5,
            "token_count": 100,
            "created_at": "2026-01-01",
        }
        result = _transform_row("conversation_summaries", row, {})
        # summary_text → summary
        assert "summary" in result
        assert result["summary"] == "A summary"
        assert "summary_text" not in result
        # messages_summarized_up_to → message_count
        assert "message_count" in result
        assert result["message_count"] == 5
        assert "messages_summarized_up_to" not in result
        # token_count dropped
        assert "token_count" not in result
        # session_id added
        assert "session_id" in result

    def test_identity_table_strips_id(self):
        row = {"id": 42, "session_id": "s1", "role": "user", "content": "hi", "user_id": "u1"}
        result = _transform_row("chat_history", row, {})
        assert "id" not in result

    def test_things_boolean_conversion(self):
        row = {
            "id": "t1",
            "title": "Test",
            "active": 1,
            "surface": 0,
            "data": '{"key": "val"}',
        }
        result = _transform_row("things", row, {})
        assert result["active"] is True
        assert result["surface"] is False

    def test_json_string_parsed(self):
        row = {
            "id": "t1",
            "title": "Test",
            "data": '{"notes": "hello"}',
            "open_questions": '["q1", "q2"]',
        }
        result = _transform_row("things", row, {})
        assert result["data"] == {"notes": "hello"}
        assert result["open_questions"] == ["q1", "q2"]

    def test_chat_message_usage_fk_remap(self):
        id_maps = {"chat_history": {1: 999}}
        row = {"id": 10, "chat_message_id": 1, "stage": "reasoning", "model": "gpt-4"}
        result = _transform_row("chat_message_usage", row, id_maps)
        assert result["chat_message_id"] == 999
        assert "id" not in result  # identity table

    def test_chat_message_usage_missing_fk_skipped(self):
        id_maps = {"chat_history": {1: 999}}
        row = {"id": 10, "chat_message_id": 42, "stage": "reasoning", "model": "gpt-4"}
        result = _transform_row("chat_message_usage", row, id_maps)
        assert result is None

    def test_sweep_findings_dismissed_bool(self):
        row = {
            "id": "sf1",
            "thing_id": "t1",
            "finding_type": "stale",
            "message": "msg",
            "dismissed": 1,
            "user_id": "u1",
        }
        result = _transform_row("sweep_findings", row, {})
        assert result["dismissed"] is True

    def test_regular_table_keeps_id(self):
        row = {"id": "t1", "title": "Test", "user_id": "u1"}
        result = _transform_row("things", row, {})
        assert result["id"] == "t1"


# ---------------------------------------------------------------------------
# Export File Generation Tests
# ---------------------------------------------------------------------------


class TestExportFiles:
    def test_export_dir_has_all_tables(self, export_dir):
        for table in EXPORT_TABLES:
            assert (export_dir / f"{table}.json").exists()

    def test_export_dir_has_vectors(self, export_dir):
        assert (export_dir / "vectors.json").exists()
        vectors = json.loads((export_dir / "vectors.json").read_text())
        assert len(vectors) == 1
        assert len(vectors[0]["embedding"]) == 3072

    def test_manifest_matches_files(self, export_dir):
        manifest = json.loads((export_dir / "manifest.json").read_text())
        for table, count in manifest["tables"].items():
            rows = json.loads((export_dir / f"{table}.json").read_text())
            assert len(rows) == count

    def test_users_export_content(self, export_dir):
        users = json.loads((export_dir / "users.json").read_text())
        assert len(users) == 1
        assert users[0]["id"] == "u1"

    def test_things_export_content(self, export_dir):
        things = json.loads((export_dir / "things.json").read_text())
        assert len(things) == 1
        assert things[0]["title"] == "My Task"
