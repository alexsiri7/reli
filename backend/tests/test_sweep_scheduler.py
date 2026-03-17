"""Tests for the sweep scheduler background task."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.sweep_scheduler import (
    _get_config,
    _run_sweep,
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


class TestRunSweep:
    @pytest.mark.asyncio
    async def test_no_candidates_produces_empty_run(self, patched_db):
        """When SQL phase finds nothing, sweep completes with zero findings."""
        mock_result = MagicMock(
            candidates_found=0, findings_created=0,
            things_created=0, things_updated=0,
        )
        with patch(
            "backend.sweep.run_full_sweep",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_sweep:
            await _run_sweep()
            mock_sweep.assert_called_once()

    @pytest.mark.asyncio
    async def test_with_users_runs_per_user(self, patched_db):
        """When users exist, sweep runs once per user."""
        mock_result = MagicMock(
            candidates_found=1, findings_created=1,
            things_created=0, things_updated=0,
        )
        with (
            patch(
                "backend.sweep_scheduler._get_all_user_ids",
                return_value=["user-1", "user-2"],
            ),
            patch(
                "backend.sweep.run_full_sweep",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_sweep,
        ):
            await _run_sweep()
            assert mock_sweep.call_count == 2

    @pytest.mark.asyncio
    async def test_error_handled(self, patched_db):
        """Errors in sweep are logged, not raised."""
        with patch(
            "backend.sweep.run_full_sweep",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            # Should not raise
            await _run_sweep()


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_creates_task(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SWEEP_ENABLED", "false")
        import backend.sweep_scheduler as mod

        mod._task = None
        start_scheduler()
        assert mod._task is not None
        # Let the task start and exit (disabled → returns immediately)
        await asyncio.sleep(0.1)
        stop_scheduler()
        assert mod._task is None

    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        import backend.sweep_scheduler as mod

        mod._task = None
        stop_scheduler()  # should not raise
        assert mod._task is None
