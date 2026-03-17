"""Sweep scheduler — runs the nightly sweep as a background asyncio task.

Default schedule: daily at 03:00 local time.  Configurable via the
``SWEEP_HOUR`` (0-23) and ``SWEEP_MINUTE`` (0-59) environment variables.
Set ``SWEEP_ENABLED=false`` to disable entirely.

The scheduler runs the SQL candidate phase first.  If candidates are found,
it proceeds to the LLM reflection phase.  Errors are logged but never
propagate to the main application.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _get_config() -> tuple[bool, int, int, bool]:
    """Return (enabled, hour, minute, reasoning_enabled) from settings.

    Constructs a fresh Settings instance so that tests can override env vars
    per test case via monkeypatch.
    """
    from .config import Settings

    s = Settings()
    return (
        s.sweep_enabled_bool,
        max(0, min(23, s.SWEEP_HOUR)),
        max(0, min(59, s.SWEEP_MINUTE)),
        s.sweep_reasoning_enabled_bool,
    )


def _seconds_until(hour: int, minute: int) -> float:
    """Seconds until the next occurrence of *hour:minute* local time."""
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _run_sweep(reasoning_enabled: bool = False) -> None:
    """Execute one sweep cycle: SQL candidates → LLM reflection → optional reasoning sweep."""
    from .sweep import collect_candidates, reflect_on_candidates

    logger.info("Sweep started")

    try:
        candidates = collect_candidates()
        logger.info("Sweep SQL phase: %d candidates found", len(candidates))

        if candidates:
            result = await reflect_on_candidates(candidates)
            logger.info(
                "Sweep reflection complete — %d findings created (usage: %s)",
                result.findings_created,
                result.usage,
            )
        else:
            logger.info("Sweep SQL phase: no candidates, skipping LLM reflection")
    except Exception:
        logger.exception("Sweep reflection failed")

    # Phase 3: Reasoning sweep (per-user, against full graph)
    if reasoning_enabled:
        try:
            from .sweep_reasoning import run_sweep_reasoning_all_users

            logger.info("Sweep reasoning phase started")
            results = await run_sweep_reasoning_all_users()
            total_findings = sum(r.findings_created for r in results)
            total_changes = sum(
                len(r.changes.get("created", []))
                + len(r.changes.get("updated", []))
                + len(r.changes.get("relationships_created", []))
                for r in results
            )
            logger.info(
                "Sweep reasoning complete — %d users processed, %d findings, %d changes",
                len(results),
                total_findings,
                total_changes,
            )
        except Exception:
            logger.exception("Sweep reasoning failed")


async def sweep_loop() -> None:
    """Background loop that runs the sweep at the configured time each day."""
    enabled, hour, minute, reasoning_enabled = _get_config()
    if not enabled:
        logger.info("Sweep scheduler disabled (SWEEP_ENABLED=false)")
        return

    logger.info(
        "Sweep scheduler started — daily at %02d:%02d (reasoning=%s)",
        hour, minute, reasoning_enabled,
    )

    while True:
        delay = _seconds_until(hour, minute)
        logger.debug("Next sweep in %.0f seconds", delay)

        await asyncio.sleep(delay)

        try:
            await _run_sweep(reasoning_enabled=reasoning_enabled)
        except Exception:
            logger.exception("Unexpected error in sweep loop")

        # Sleep a short time to avoid re-triggering within the same minute
        await asyncio.sleep(61)


_task: asyncio.Task[None] | None = None


def start_scheduler() -> None:
    """Start the sweep background task.  Safe to call multiple times."""
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(sweep_loop())
    logger.info("Sweep scheduler task created")


def stop_scheduler() -> None:
    """Cancel the sweep background task if running."""
    global _task
    if _task is not None and not _task.done():
        _task.cancel()
        logger.info("Sweep scheduler task cancelled")
    _task = None
