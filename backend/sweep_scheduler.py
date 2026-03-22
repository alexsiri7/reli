"""Sweep scheduler — runs the nightly sweep as a background asyncio task.

Default schedule: daily at 03:00 local time.  Configurable via the
``SWEEP_HOUR`` (0-23) and ``SWEEP_MINUTE`` (0-59) environment variables.
Set ``SWEEP_ENABLED=false`` to disable entirely.

The scheduler iterates over all users, running the SQL candidate phase and
LLM reflection phase per-user.  Each run is logged in the sweep_runs table.
Errors are logged but never propagate to the main application.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

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
    """Return all user IDs from the database. Returns [''] if no users exist."""
    from .database import db

    with db() as conn:
        rows = conn.execute("SELECT id FROM users ORDER BY created_at").fetchall()
    if not rows:
        return [""]  # No users — run in legacy single-user mode
    return [row["id"] for row in rows]


def _log_run(
    run_id: str,
    user_id: str,
    status: str,
    candidates_found: int = 0,
    findings_created: int = 0,
    model: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_usd: float = 0.0,
    error: str | None = None,
    started_at: str = "",
    completed_at: str | None = None,
) -> None:
    """Insert or update a sweep run record."""
    from .database import db

    with db() as conn:
        conn.execute(
            """INSERT INTO sweep_runs
               (id, user_id, status, candidates_found, findings_created,
                model, prompt_tokens, completion_tokens, cost_usd,
                error, started_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 status=excluded.status,
                 candidates_found=excluded.candidates_found,
                 findings_created=excluded.findings_created,
                 model=excluded.model,
                 prompt_tokens=excluded.prompt_tokens,
                 completion_tokens=excluded.completion_tokens,
                 cost_usd=excluded.cost_usd,
                 error=excluded.error,
                 completed_at=excluded.completed_at""",
            (
                run_id,
                user_id or None,
                status,
                candidates_found,
                findings_created,
                model,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                error,
                started_at,
                completed_at,
            ),
        )


async def _run_sweep_for_user(user_id: str) -> None:
    """Execute one sweep cycle for a single user."""
    from .sweep import collect_candidates, reflect_on_candidates

    run_id = f"sr-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    _log_run(run_id, user_id, status="running", started_at=now)

    try:
        candidates = collect_candidates(user_id=user_id)
        user_label = user_id[:8] if user_id else "legacy"
        logger.info("Sweep [%s] SQL phase: %d candidates found", user_label, len(candidates))

        if not candidates:
            _log_run(
                run_id,
                user_id,
                status="completed",
                candidates_found=0,
                findings_created=0,
                started_at=now,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            # Still generate morning briefing (captures priorities, overdue, blockers)
            try:
                from .morning_briefing import generate_morning_briefing, store_morning_briefing

                content = generate_morning_briefing(user_id)
                store_morning_briefing(user_id, content)
                logger.info("Morning briefing generated for user %s (no sweep candidates)", user_label)
            except Exception:
                logger.exception("Failed to generate morning briefing for user %s", user_label)
            return

        result = await reflect_on_candidates(candidates, user_id=user_id)
        _log_run(
            run_id,
            user_id,
            status="completed",
            candidates_found=len(candidates),
            findings_created=result.findings_created,
            model=result.usage.get("model"),
            prompt_tokens=result.usage.get("prompt_tokens", 0),
            completion_tokens=result.usage.get("completion_tokens", 0),
            cost_usd=result.usage.get("cost_usd", 0.0),
            started_at=now,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.info(
            "Sweep [%s] complete — %d findings created (usage: %s)",
            user_label,
            result.findings_created,
            result.usage,
        )

        # Generate morning briefing after sweep completes
        try:
            from .morning_briefing import generate_morning_briefing, store_morning_briefing

            content = generate_morning_briefing(user_id)
            store_morning_briefing(user_id, content)
            logger.info("Morning briefing generated for user %s", user_label)
        except Exception:
            logger.exception("Failed to generate morning briefing for user %s", user_label)
    except Exception as exc:
        logger.exception("Sweep failed for user %s", user_id)
        _log_run(
            run_id,
            user_id,
            status="failed",
            error=str(exc),
            started_at=now,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )


async def _run_sweep() -> None:
    """Execute one sweep cycle: iterate over all users, then run connection sweep."""
    logger.info("Sweep started")
    user_ids = _get_all_user_ids()
    logger.info("Sweep processing %d user(s)", len(user_ids))

    for user_id in user_ids:
        try:
            await _run_sweep_for_user(user_id)
        except Exception:
            logger.exception("Sweep failed for user %s", user_id)

    # Connection sweep: find semantically similar but unconnected Things
    try:
        from .connection_sweep import run_connection_sweep

        conn_result = await run_connection_sweep()
        logger.info(
            "Connection sweep: %d candidates, %d suggestions created",
            conn_result.candidates_found,
            conn_result.suggestions_created,
        )
    except Exception:
        logger.exception("Connection sweep failed")

    logger.info("Sweep cycle complete")


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
