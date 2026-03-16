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
        from backend.settings import settings

        monkeypatch.setattr(settings, "sweep_enabled", "true")
        monkeypatch.setattr(settings, "sweep_hour", 3)
        monkeypatch.setattr(settings, "sweep_minute", 0)
        enabled, hour, minute = _get_config()
        assert enabled is True
        assert hour == 3
        assert minute == 0

    def test_disabled(self, monkeypatch: pytest.MonkeyPatch):
        from backend.settings import settings

        monkeypatch.setattr(settings, "sweep_enabled", "false")
        enabled, _, _ = _get_config()
        assert enabled is False

    def test_disabled_zero(self, monkeypatch: pytest.MonkeyPatch):
        from backend.settings import settings

        monkeypatch.setattr(settings, "sweep_enabled", "0")
        enabled, _, _ = _get_config()
        assert enabled is False

    def test_custom_time(self, monkeypatch: pytest.MonkeyPatch):
        from backend.settings import settings

        monkeypatch.setattr(settings, "sweep_hour", 14)
        monkeypatch.setattr(settings, "sweep_minute", 30)
        _, hour, minute = _get_config()
        assert hour == 14
        assert minute == 30

    def test_clamped_values(self, monkeypatch: pytest.MonkeyPatch):
        from backend.settings import settings

        monkeypatch.setattr(settings, "sweep_hour", 99)
        monkeypatch.setattr(settings, "sweep_minute", -5)
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
    async def test_no_candidates_skips_llm(self, patched_db):
        """When SQL phase finds nothing, LLM phase is not called."""
        with (
            patch("backend.sweep.collect_candidates", return_value=[]) as mock_collect,
            patch("backend.sweep.reflect_on_candidates") as mock_reflect,
        ):
            await _run_sweep()
            mock_collect.assert_called_once()
            mock_reflect.assert_not_called()

    @pytest.mark.asyncio
    async def test_with_candidates_runs_llm(self, patched_db):
        """When SQL phase finds candidates, LLM phase runs."""
        fake_candidate = MagicMock()
        mock_result = MagicMock(findings_created=2, usage={"total_tokens": 100})

        with (
            patch(
                "backend.sweep.collect_candidates",
                return_value=[fake_candidate],
            ),
            patch(
                "backend.sweep.reflect_on_candidates",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_reflect,
        ):
            await _run_sweep()
            mock_reflect.assert_called_once_with([fake_candidate])

    @pytest.mark.asyncio
    async def test_sql_error_handled(self, patched_db):
        """Errors in SQL phase are logged, not raised."""
        with patch(
            "backend.sweep.collect_candidates",
            side_effect=RuntimeError("db boom"),
        ):
            # Should not raise
            await _run_sweep()

    @pytest.mark.asyncio
    async def test_llm_error_handled(self, patched_db):
        """Errors in LLM phase are logged, not raised."""
        fake_candidate = MagicMock()
        with (
            patch(
                "backend.sweep.collect_candidates",
                return_value=[fake_candidate],
            ),
            patch(
                "backend.sweep.reflect_on_candidates",
                new_callable=AsyncMock,
                side_effect=RuntimeError("llm boom"),
            ),
        ):
            # Should not raise
            await _run_sweep()


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_creates_task(self, monkeypatch: pytest.MonkeyPatch):
        from backend.settings import settings

        monkeypatch.setattr(settings, "sweep_enabled", "false")
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
