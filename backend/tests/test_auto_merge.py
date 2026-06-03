"""Tests for auto_merge_duplicates() sweep phase."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, select

import backend.db_engine as _engine_mod
from backend.db_models import SweepActionRecord, SweepFindingRecord
from backend.sweep import auto_merge_duplicates
from backend.tools import get_thing


def _insert_project(conn, proj_id: str, proj_title: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO things (id, title, type_hint, importance, active, surface, created_at, updated_at) "
        "VALUES (?, ?, 'project', 2, 1, 1, ?, ?)",
        (proj_id, proj_title, now, now),
    )


def _insert_task_under_project(
    conn, task_id: str, task_title: str, proj_id: str, created_at: str | None = None
) -> None:
    now = created_at or datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO things (id, title, type_hint, importance, active, surface, created_at, updated_at) "
        "VALUES (?, ?, 'task', 2, 1, 1, ?, ?)",
        (task_id, task_title, now, now),
    )
    conn.execute(
        "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type) VALUES (?, ?, ?, 'parent-of')",
        (str(uuid.uuid4()), proj_id, task_id),
    )


class TestAutoMergeDuplicates:
    def test_exact_duplicate_across_projects_is_merged(self, db):
        """Tasks with identical titles in different projects get auto-merged."""
        with db() as conn:
            _insert_project(conn, "proj-a", "Project Alpha")
            _insert_project(conn, "proj-b", "Project Beta")
            older_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
            _insert_task_under_project(conn, "task-old", "Deploy pipeline", "proj-a", created_at=older_ts)
            _insert_task_under_project(conn, "task-new", "Deploy pipeline", "proj-b")

        result = asyncio.run(auto_merge_duplicates(user_id=""))

        assert result.merges_executed >= 1
        # One of the tasks should be gone
        assert "error" in get_thing("task-new") or "error" in get_thing("task-old")

    def test_older_thing_is_kept(self, db):
        """The older Thing is kept; the newer duplicate is removed."""
        with db() as conn:
            _insert_project(conn, "proj-a", "Project Alpha")
            _insert_project(conn, "proj-b", "Project Beta")
            older_ts = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
            _insert_task_under_project(conn, "task-old", "Review docs", "proj-a", created_at=older_ts)
            _insert_task_under_project(conn, "task-new", "Review docs", "proj-b")

        asyncio.run(auto_merge_duplicates(user_id=""))

        # Older thing should still exist
        assert "error" not in get_thing("task-old")
        # Newer duplicate should be gone
        assert "error" in get_thing("task-new")

    def test_auto_merge_creates_sweep_finding(self, db):
        """Auto-merge creates a duplicate_auto_merged SweepFindingRecord."""
        with db() as conn:
            _insert_project(conn, "proj-a", "Project Alpha")
            _insert_project(conn, "proj-b", "Project Beta")
            _insert_task_under_project(conn, "task-a", "Write tests", "proj-a")
            _insert_task_under_project(conn, "task-b", "Write tests", "proj-b")

        asyncio.run(auto_merge_duplicates(user_id=""))

        with Session(_engine_mod.engine) as session:
            findings = session.exec(
                select(SweepFindingRecord).where(
                    SweepFindingRecord.finding_type == "duplicate_auto_merged"
                )
            ).all()
        assert len(findings) >= 1
        assert findings[0].confidence == pytest.approx(0.95)

    def test_auto_merge_creates_sweep_action(self, db):
        """Auto-merge records a SweepActionRecord with action_type='merge'."""
        with db() as conn:
            _insert_project(conn, "proj-a", "Project Alpha")
            _insert_project(conn, "proj-b", "Project Beta")
            _insert_task_under_project(conn, "task-a", "Update config", "proj-a")
            _insert_task_under_project(conn, "task-b", "Update config", "proj-b")

        asyncio.run(auto_merge_duplicates(user_id=""))

        with Session(_engine_mod.engine) as session:
            actions = session.exec(
                select(SweepActionRecord).where(SweepActionRecord.action_type == "merge")
            ).all()
        assert len(actions) >= 1

    def test_no_duplicates_returns_zero(self, db):
        """When no exact duplicates exist, returns merges_executed=0."""
        with db() as conn:
            _insert_project(conn, "proj-a", "Project Alpha")
            _insert_project(conn, "proj-b", "Project Beta")
            _insert_task_under_project(conn, "task-a", "Unique Task A", "proj-a")
            _insert_task_under_project(conn, "task-b", "Different Task B", "proj-b")

        result = asyncio.run(auto_merge_duplicates(user_id=""))
        assert result.merges_executed == 0

    def test_same_project_duplicates_not_merged(self, db):
        """Tasks with identical titles in the SAME project are not auto-merged."""
        with db() as conn:
            _insert_project(conn, "proj-a", "Project Alpha")
            _insert_task_under_project(conn, "task-a", "Same title", "proj-a")
            _insert_task_under_project(conn, "task-b", "Same title", "proj-a")

        result = asyncio.run(auto_merge_duplicates(user_id=""))
        assert result.merges_executed == 0

    def test_disabled_config_skips_merge(self, db, monkeypatch):
        """When SWEEP_AUTO_MERGE_ENABLED=false, no merges are executed."""
        with db() as conn:
            _insert_project(conn, "proj-a", "Project Alpha")
            _insert_project(conn, "proj-b", "Project Beta")
            _insert_task_under_project(conn, "task-a", "Shared work", "proj-a")
            _insert_task_under_project(conn, "task-b", "Shared work", "proj-b")

        from backend import config as _config
        monkeypatch.setattr(_config.settings, "SWEEP_AUTO_MERGE_ENABLED", "false")

        result = asyncio.run(auto_merge_duplicates(user_id=""))
        assert result.merges_executed == 0
