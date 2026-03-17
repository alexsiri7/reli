"""Sweep scheduler — runs the nightly sweep as a background asyncio task.

Default schedule: daily at 03:00 local time.  Configurable via the
``SWEEP_HOUR`` (0-23) and ``SWEEP_MINUTE`` (0-59) environment variables.
Set ``SWEEP_ENABLED=false`` to disable entirely.

The scheduler processes each user separately, running the full sweep pipeline
(SQL candidates → LLM reflection → reasoning) per user.  Errors are logged
but never propagate to the main application.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _get_config() -> tuple[bool, int, int]:
    """Return (enabled, hour, minute) from settings.

    Constructs a fresh Settings instance so that tests can override env vars
    per test case via monkeypatch.
    """
    from .config import Settings

    s = Settings()
    return (
        s.sweep_enabled_bool,
        max(0, min(23, s.SWEEP_HOUR)),
        max(0, min(59, s.SWEEP_MINUTE)),
    )


def _seconds_until(hour: int, minute: int) -> float:
    """Seconds until the next occurrence of *hour:minute* local time."""
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _get_all_user_ids() -> list[str]:
    """Return all user IDs from the database."""
    from .database import db

    with db() as conn:
        rows = conn.execute("SELECT id FROM users").fetchall()
    return [row["id"] for row in rows]


async def _run_sweep() -> None:
    """Execute one sweep cycle: per-user full sweep pipeline."""
    from .sweep import run_full_sweep

    logger.info("Sweep started")

    try:
        user_ids = _get_all_user_ids()

        if not user_ids:
            # No users yet — run a single sweep without user filtering
            logger.info("Sweep: no users found, running without user filter")
            result = await run_full_sweep(user_id=None, trigger="scheduled")
            logger.info(
                "Sweep complete — %d candidates, %d findings, %d created, %d updated",
                result.candidates_found, result.findings_created,
                result.things_created, result.things_updated,
            )
            return

        logger.info("Sweep: processing %d users", len(user_ids))
        for uid in user_ids:
            try:
                result = await run_full_sweep(user_id=uid, trigger="scheduled")
                logger.info(
                    "Sweep user=%s — %d candidates, %d findings, %d created, %d updated",
                    uid, result.candidates_found, result.findings_created,
                    result.things_created, result.things_updated,
                )
            except Exception:
                logger.exception("Sweep failed for user=%s", uid)

        logger.info("Sweep complete — all users processed")

    except Exception:
        logger.exception("Sweep failed")


async def sweep_loop() -> None:
    """Background loop that runs the sweep at the configured time each day."""
    enabled, hour, minute = _get_config()
    if not enabled:
        logger.info("Sweep scheduler disabled (SWEEP_ENABLED=false)")
        return

    logger.info("Sweep scheduler started — daily at %02d:%02d", hour, minute)

    while True:
        delay = _seconds_until(hour, minute)
        logger.debug("Next sweep in %.0f seconds", delay)

        await asyncio.sleep(delay)

        try:
            await _run_sweep()
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
