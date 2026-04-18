"""Tests for the sweep scheduler background task."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.sweep_scheduler import (
    _get_all_user_ids,
    _get_config,
    _log_run,
    _run_sweep,
    _run_sweep_for_user,
    _seconds_until,
    start_scheduler,
    stop_scheduler,
)


class TestGetConfig:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SWEEP_ENABLED", raising=False)
        monkeypatch.delenv("SWEEP_HOUR", raising=False)
        monkeypatch.delenv("SWEEP_MINUTE", raising=False)
        enabled, hour, minute = _get_config()
        assert enabled is True
        assert hour == 3
        assert minute == 0

    def test_disabled(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SWEEP_ENABLED", "false")
        enabled, _, _ = _get_config()
        assert enabled is False

    def test_disabled_zero(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SWEEP_ENABLED", "0")
        enabled, _, _ = _get_config()
        assert enabled is False

    def test_custom_time(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SWEEP_HOUR", "14")
        monkeypatch.setenv("SWEEP_MINUTE", "30")
        _, hour, minute = _get_config()
        assert hour == 14
        assert minute == 30

    def test_clamped_values(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SWEEP_HOUR", "99")
        monkeypatch.setenv("SWEEP_MINUTE", "-5")
        _, hour, minute = _get_config()
        assert hour == 23
        assert minute == 0


class TestSecondsUntil:
    def test_future_today(self):
        now = datetime.now()
        future_hour = (now.hour + 2) % 24
        secs = _seconds_until(future_hour, 0)
        # Should be roughly 2 hours if the target is later today
        if future_hour > now.hour:
            assert 3000 < secs < 8000
        else:
            # Wrapped to next day
            assert secs > 0

    def test_past_today_wraps_to_tomorrow(self):
        now = datetime.now()
        # Pick an hour that's already passed today
        past_hour = (now.hour - 2) % 24
        secs = _seconds_until(past_hour, 0)
        # Should be roughly 22 hours (wraps to tomorrow)
        assert secs > 3600 * 20

    def test_always_positive(self):
        for h in range(24):
            assert _seconds_until(h, 0) > 0


class TestGetAllUserIds:
    def test_no_users_returns_legacy(self, patched_db):
        result = _get_all_user_ids()
        assert result == [""]

    def test_returns_user_ids(self, patched_db, db):

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "a@b.com", "g1", "Alice"),
            )
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u2", "c@d.com", "g2", "Bob"),
            )
        result = _get_all_user_ids()
        assert result == ["u1", "u2"]


class TestLogRun:
    def test_creates_run_record(self, patched_db, db):

        _log_run(
            "sr-test1",
            "",
            status="completed",
            candidates_found=5,
            findings_created=2,
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:01:00Z",
        )

        with db() as conn:
            row = conn.execute("SELECT * FROM sweep_runs WHERE id = ?", ("sr-test1",)).fetchone()
        assert row is not None
        assert row["status"] == "completed"
        assert row["candidates_found"] == 5
        assert row["findings_created"] == 2

    def test_upsert_updates_existing(self, patched_db, db):

        _log_run("sr-test2", "", status="running", started_at="2026-01-01T00:00:00Z")
        _log_run(
            "sr-test2",
            "",
            status="completed",
            candidates_found=3,
            findings_created=1,
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:01:00Z",
        )

        with db() as conn:
            row = conn.execute("SELECT * FROM sweep_runs WHERE id = ?", ("sr-test2",)).fetchone()
        assert row["status"] == "completed"
        assert row["candidates_found"] == 3


class TestRunSweepForUser:
    @pytest.mark.asyncio
    async def test_no_candidates_logs_completed(self, patched_db, db):

        with patch("backend.sweep.collect_candidates", return_value=[]):
            await _run_sweep_for_user("")

        with db() as conn:
            rows = conn.execute("SELECT * FROM sweep_runs").fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "completed"
        assert rows[0]["candidates_found"] == 0

    @pytest.mark.asyncio
    async def test_with_candidates_runs_reflection(self, patched_db, db):

        fake_candidate = MagicMock()
        mock_result = MagicMock(
            findings_created=2,
            usage={"model": "test-model", "prompt_tokens": 50, "completion_tokens": 30, "cost_usd": 0.01},
        )

        with (
            patch("backend.sweep.collect_candidates", return_value=[fake_candidate]),
            patch("backend.sweep.reflect_on_candidates", new_callable=AsyncMock, return_value=mock_result),
        ):
            await _run_sweep_for_user("")

        with db() as conn:
            rows = conn.execute("SELECT * FROM sweep_runs").fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "completed"
        assert rows[0]["candidates_found"] == 1
        assert rows[0]["findings_created"] == 2

    @pytest.mark.asyncio
    async def test_runs_dependency_sweep(self, patched_db, db):
        mock_dep_result = MagicMock(suggestions_created=1, findings_created=1)

        with (
            patch("backend.sweep.collect_candidates", return_value=[]),
            patch(
                "backend.dependency_sweep.run_dependency_sweep",
                new_callable=AsyncMock,
                return_value=mock_dep_result,
            ) as mock_dep,
        ):
            await _run_sweep_for_user("u1")

        mock_dep.assert_called_once_with(user_id="u1")


class TestRunSweep:
    @pytest.mark.asyncio
    async def test_iterates_over_users(self, patched_db, db):

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "a@b.com", "g1", "Alice"),
            )
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u2", "c@d.com", "g2", "Bob"),
            )

        with patch("backend.sweep.collect_candidates", return_value=[]) as mock_collect:
            await _run_sweep()

        # Should have been called once per user
        assert mock_collect.call_count == 2
        call_user_ids = [c.kwargs.get("user_id") for c in mock_collect.call_args_list]
        assert "u1" in call_user_ids
        assert "u2" in call_user_ids

    @pytest.mark.asyncio
    async def test_error_in_one_user_doesnt_block_others(self, patched_db, db):

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "a@b.com", "g1", "Alice"),
            )
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u2", "c@d.com", "g2", "Bob"),
            )

        call_count = 0

        def side_effect(user_id="", **kwargs):
            nonlocal call_count
            call_count += 1
            if user_id == "u1":
                raise RuntimeError("boom")
            return []

        with patch("backend.sweep.collect_candidates", side_effect=side_effect):
            await _run_sweep()  # Should not raise

        assert call_count == 2  # Both users attempted


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_creates_task(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SWEEP_ENABLED", "false")
        import backend.sweep_scheduler as mod

        mod._task = None
        await start_scheduler()
        assert mod._task is not None
        # Let the task start and exit (disabled -> returns immediately)
        await asyncio.sleep(0.1)
        await stop_scheduler()
        assert mod._task is None

    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        import backend.sweep_scheduler as mod

        mod._task = None
        await stop_scheduler()  # should not raise
        assert mod._task is None
