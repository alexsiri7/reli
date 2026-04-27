"""Tests for the scheduled tasks feature."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from backend.db_models import ScheduledTaskRecord, SweepFindingRecord
from backend.tools import create_scheduled_task, get_due_scheduled_tasks


class TestCreateScheduledTask:
    def test_creates_record(self, patched_db):
        result = create_scheduled_task(
            scheduled_at="2026-05-01T09:00:00",
            task_type="remind",
            payload_json='{"message": "Check flight prices"}',
        )
        assert "id" in result
        assert result["task_type"] == "remind"
        assert result["payload"] == {"message": "Check flight prices"}

    def test_missing_scheduled_at(self, patched_db):
        result = create_scheduled_task(scheduled_at="", task_type="remind")
        assert "error" in result
        assert "scheduled_at" in result["error"]

    def test_invalid_iso_date(self, patched_db):
        result = create_scheduled_task(scheduled_at="not-a-date", task_type="remind")
        assert "error" in result
        assert "ISO-8601" in result["error"]

    def test_invalid_payload_json(self, patched_db):
        result = create_scheduled_task(
            scheduled_at="2026-05-01T09:00:00",
            payload_json="not json",
        )
        assert "error" in result
        assert "payload_json" in result["error"]

    def test_with_thing_id(self, patched_db):
        result = create_scheduled_task(
            scheduled_at="2026-05-01T09:00:00",
            thing_id="",
            task_type="check",
        )
        assert "id" in result
        assert result["task_type"] == "check"
        assert result["thing_id"] is None


class TestGetDueScheduledTasks:
    def test_returns_due_tasks(self, patched_db):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        create_scheduled_task(scheduled_at=past, task_type="remind")
        due = get_due_scheduled_tasks()
        assert len(due) == 1

    def test_excludes_executed_tasks(self, patched_db):
        import backend.db_engine as _engine_mod

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        result = create_scheduled_task(scheduled_at=past, task_type="remind")
        # Mark as executed
        with Session(_engine_mod.engine) as session:
            record = session.get(ScheduledTaskRecord, result["id"])
            record.executed_at = datetime.now(timezone.utc)
            session.add(record)
            session.commit()
        due = get_due_scheduled_tasks()
        assert len(due) == 0

    def test_excludes_future_tasks(self, patched_db):
        future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        create_scheduled_task(scheduled_at=future, task_type="remind")
        due = get_due_scheduled_tasks()
        assert len(due) == 0


class TestProcessScheduledTasks:
    def test_processes_due_remind_task(self, patched_db):
        import backend.db_engine as _engine_mod
        from backend.sweep_scheduler import _process_scheduled_tasks

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        result = create_scheduled_task(
            scheduled_at=past,
            task_type="remind",
            payload_json='{"message": "Test reminder"}',
        )
        task_id = result["id"]

        asyncio.run(_process_scheduled_tasks())

        # Verify task is marked executed
        with Session(_engine_mod.engine) as session:
            task = session.get(ScheduledTaskRecord, task_id)
            assert task.executed_at is not None
            assert task.result == {"status": "executed", "task_type": "remind"}

            # Verify a SweepFindingRecord was created
            findings = session.exec(
                select(SweepFindingRecord).where(SweepFindingRecord.finding_type == "reminder")
            ).all()
            assert len(findings) == 1
            assert findings[0].message == "Test reminder"


class TestScheduledTasksNotReExecuted:
    def test_already_executed_task_skipped(self, patched_db):
        import backend.db_engine as _engine_mod
        from backend.sweep_scheduler import _process_scheduled_tasks

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        result = create_scheduled_task(
            scheduled_at=past,
            task_type="remind",
            payload_json='{"message": "Already done"}',
        )

        # Mark as already executed
        with Session(_engine_mod.engine) as session:
            task = session.get(ScheduledTaskRecord, result["id"])
            task.executed_at = datetime.now(timezone.utc)
            task.result = {"status": "executed", "task_type": "remind"}
            session.add(task)
            session.commit()

        # Run processor — should not create any new findings
        asyncio.run(_process_scheduled_tasks())

        with Session(_engine_mod.engine) as session:
            findings = session.exec(
                select(SweepFindingRecord).where(SweepFindingRecord.finding_type == "reminder")
            ).all()
            assert len(findings) == 0
