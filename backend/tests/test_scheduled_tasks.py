"""Tests for self-scheduling: scheduled_tasks table, processor, MCP tool, and reasoning agent."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.database import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_user(conn, uid: str = "u1") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
        (uid, f"{uid}@test.com", f"g-{uid}", uid),
    )


def _insert_thing(conn, tid: str = "thing-1", title: str = "Test Thing") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO things (id, title) VALUES (?, ?)",
        (tid, title),
    )


# ---------------------------------------------------------------------------
# Database: create_scheduled_task
# ---------------------------------------------------------------------------


class TestCreateScheduledTask:
    def test_creates_task_in_db(self, patched_db):
        from backend.tools import create_scheduled_task

        result = create_scheduled_task(
            task_type="remind",
            scheduled_at="2026-04-01T09:00:00Z",
            payload={"message": "Check prices"},
        )

        assert result["task_type"] == "remind"
        assert result["scheduled_at"] == "2026-04-01T09:00:00Z"
        assert "id" in result
        assert "created_at" in result

        with db() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?", (result["id"],)
            ).fetchone()
        assert row is not None
        assert row["task_type"] == "remind"
        assert json.loads(row["payload"]) == {"message": "Check prices"}
        assert row["executed_at"] is None

    def test_creates_task_with_thing_id(self, patched_db):
        from backend.tools import create_scheduled_task

        with db() as conn:
            _insert_thing(conn)

        result = create_scheduled_task(
            task_type="sweep_concern",
            scheduled_at="2026-04-01T09:00:00Z",
            thing_id="thing-1",
        )

        with db() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?", (result["id"],)
            ).fetchone()
        assert row["thing_id"] == "thing-1"

    def test_task_without_payload(self, patched_db):
        from backend.tools import create_scheduled_task

        result = create_scheduled_task(
            task_type="custom",
            scheduled_at="2026-05-01T00:00:00Z",
        )

        with db() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?", (result["id"],)
            ).fetchone()
        assert row["payload"] is None


# ---------------------------------------------------------------------------
# Processor: _process_scheduled_tasks
# ---------------------------------------------------------------------------


class TestProcessScheduledTasks:
    @pytest.mark.asyncio
    async def test_picks_up_due_tasks(self, patched_db):
        from backend.sweep_scheduler import _process_scheduled_tasks

        # Insert a past-due task
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with db() as conn:
            conn.execute(
                "INSERT INTO scheduled_tasks (id, task_type, payload, scheduled_at, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("task-1", "remind", json.dumps({"message": "Hello"}), past, past),
            )

        await _process_scheduled_tasks()

        with db() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = 'task-1'"
            ).fetchone()
        assert row["executed_at"] is not None
        result = json.loads(row["result"])
        assert result["status"] == "delivered"

    @pytest.mark.asyncio
    async def test_does_not_reexecute_completed_tasks(self, patched_db):
        from backend.sweep_scheduler import _process_scheduled_tasks

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        already_executed = past
        with db() as conn:
            conn.execute(
                "INSERT INTO scheduled_tasks"
                " (id, task_type, payload, scheduled_at, executed_at, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "task-done",
                    "remind",
                    json.dumps({"message": "already done"}),
                    past,
                    already_executed,
                    past,
                ),
            )

        await _process_scheduled_tasks()

        # executed_at should remain unchanged
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = 'task-done'"
            ).fetchone()
        assert row["executed_at"] == already_executed

    @pytest.mark.asyncio
    async def test_skips_future_tasks(self, patched_db):
        from backend.sweep_scheduler import _process_scheduled_tasks

        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            conn.execute(
                "INSERT INTO scheduled_tasks (id, task_type, payload, scheduled_at, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("task-future", "remind", json.dumps({"message": "not yet"}), future, now),
            )

        await _process_scheduled_tasks()

        with db() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = 'task-future'"
            ).fetchone()
        assert row["executed_at"] is None

    @pytest.mark.asyncio
    async def test_sweep_concern_task_with_no_thing_id(self, patched_db):
        from backend.sweep_scheduler import _process_scheduled_tasks

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with db() as conn:
            conn.execute(
                "INSERT INTO scheduled_tasks (id, task_type, payload, scheduled_at, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("task-sweep", "sweep_concern", None, past, past),
            )

        await _process_scheduled_tasks()

        with db() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = 'task-sweep'"
            ).fetchone()
        assert row["executed_at"] is not None
        result = json.loads(row["result"])
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_custom_task_executes(self, patched_db):
        from backend.sweep_scheduler import _process_scheduled_tasks

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with db() as conn:
            conn.execute(
                "INSERT INTO scheduled_tasks (id, task_type, payload, scheduled_at, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("task-custom", "custom", None, past, past),
            )

        await _process_scheduled_tasks()

        with db() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = 'task-custom'"
            ).fetchone()
        assert row["executed_at"] is not None
        result = json.loads(row["result"])
        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# Reasoning agent: apply_storage_changes processes scheduled_tasks
# ---------------------------------------------------------------------------


class TestApplyStorageChangesScheduledTasks:
    def test_scheduled_task_created_from_storage_changes(self, patched_db):
        import sqlite3

        from backend.agents import apply_storage_changes
        from backend.database import DB_PATH

        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        storage_changes = {
            "scheduled_tasks": [
                {
                    "task_type": "remind",
                    "scheduled_at": "2026-04-01T09:00:00Z",
                    "payload": {"message": "Check flight prices"},
                }
            ]
        }

        applied = apply_storage_changes(storage_changes, conn, user_id="")
        conn.commit()
        conn.close()

        assert len(applied["scheduled_tasks_created"]) == 1
        assert applied["scheduled_tasks_created"][0]["task_type"] == "remind"

        with db() as c:
            rows = c.execute("SELECT * FROM scheduled_tasks").fetchall()
        assert len(rows) == 1
        assert rows[0]["task_type"] == "remind"

    def test_invalid_scheduled_task_skipped(self, patched_db):
        import sqlite3

        from backend.agents import apply_storage_changes
        from backend.database import DB_PATH

        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")

        # Missing scheduled_at
        storage_changes = {
            "scheduled_tasks": [
                {"task_type": "remind", "payload": {"message": "oops"}}
            ]
        }

        applied = apply_storage_changes(storage_changes, conn, user_id="")
        conn.commit()
        conn.close()

        assert applied["scheduled_tasks_created"] == []
