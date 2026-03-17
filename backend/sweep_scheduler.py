"""Sweep scheduler — runs the nightly sweep as a background asyncio task.

Default schedule: daily at 03:00 local time.  Configurable via the
``SWEEP_HOUR`` (0-23) and ``SWEEP_MINUTE`` (0-59) environment variables.
Set ``SWEEP_ENABLED=false`` to disable entirely.

The scheduler runs per-user:
1. SQL candidate phase (cheap queries)
2. LLM reflection phase (if candidates found)
3. Reasoning agent phase (full graph analysis with tool calling)

Each run is logged in the sweep_runs table for auditability.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from .agents import UsageStats
from .database import db

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
    with db() as conn:
        rows = conn.execute("SELECT id FROM users ORDER BY created_at").fetchall()
    return [row["id"] for row in rows]


def _log_sweep_start(user_id: str) -> str:
    """Create a sweep_runs record and return its ID."""
    run_id = f"sr-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """INSERT INTO sweep_runs (id, user_id, started_at, status)
               VALUES (?, ?, ?, 'running')""",
            (run_id, user_id, now),
        )
    return run_id


def _log_sweep_complete(
    run_id: str,
    *,
    status: str = "completed",
    candidates_found: int = 0,
    findings_created: int = 0,
    things_created: int = 0,
    things_updated: int = 0,
    relationships_created: int = 0,
    thing_count: int = 0,
    model: str = "",
    usage_stats: UsageStats | None = None,
    error: str | None = None,
) -> None:
    """Update a sweep_runs record with completion details."""
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """UPDATE sweep_runs SET
                completed_at = ?, status = ?,
                candidates_found = ?, findings_created = ?,
                things_created = ?, things_updated = ?,
                relationships_created = ?, thing_count = ?,
                model = ?,
                prompt_tokens = ?, completion_tokens = ?, cost_usd = ?,
                error = ?
               WHERE id = ?""",
            (
                now, status,
                candidates_found, findings_created,
                things_created, things_updated,
                relationships_created, thing_count,
                model or None,
                usage_stats.prompt_tokens if usage_stats else 0,
                usage_stats.completion_tokens if usage_stats else 0,
                round(usage_stats.cost_usd, 6) if usage_stats else 0.0,
                error,
                run_id,
            ),
        )


async def _run_sweep_for_user(user_id: str) -> None:
    """Execute a full sweep cycle for one user."""
    from .config import Settings
    from .sweep import collect_candidates, reflect_on_candidates
    from .sweep_agent import run_sweep_agent

    run_id = _log_sweep_start(user_id)
    usage_stats = UsageStats()

    try:
        # Phase 1: SQL candidates
        candidates = collect_candidates()
        logger.info("Sweep SQL phase (user=%s): %d candidates", user_id, len(candidates))

        reflection_findings = 0
        if candidates:
            # Phase 2: LLM reflection on candidates
            result = await reflect_on_candidates(candidates)
            reflection_findings = result.findings_created
            logger.info(
                "Sweep reflection (user=%s): %d findings",
                user_id, reflection_findings,
            )

        # Phase 3: Reasoning agent against full graph
        s = Settings()
        sweep_model = s.SWEEP_MODEL or None  # None = use default reasoning model
        agent_result = await run_sweep_agent(
            user_id=user_id,
            model=sweep_model,
            usage_stats=usage_stats,
        )

        applied = agent_result.get("applied_changes", {})
        agent_findings = len(applied.get("findings_created", []))
        agent_created = len(applied.get("created", []))
        agent_updated = len(applied.get("updated", []))
        agent_rels = len(applied.get("relationships_created", []))

        total_findings = reflection_findings + agent_findings

        logger.info(
            "Sweep complete (user=%s) — %d candidates, %d findings, "
            "%d created, %d updated, %d relationships (usage: %s)",
            user_id, len(candidates), total_findings,
            agent_created, agent_updated, agent_rels,
            usage_stats.to_dict(),
        )

        _log_sweep_complete(
            run_id,
            candidates_found=len(candidates),
            findings_created=total_findings,
            things_created=agent_created,
            things_updated=agent_updated,
            relationships_created=agent_rels,
            thing_count=agent_result.get("thing_count", 0),
            model=sweep_model or "",
            usage_stats=usage_stats,
        )

    except Exception as exc:
        logger.exception("Sweep failed for user %s", user_id)
        _log_sweep_complete(
            run_id,
            status="failed",
            error=str(exc),
            usage_stats=usage_stats,
        )


async def _run_sweep() -> None:
    """Execute one sweep cycle for all users."""
    logger.info("Sweep started")

    user_ids = _get_all_user_ids()
    if not user_ids:
        logger.info("Sweep: no users found, skipping")
        return

    for user_id in user_ids:
        try:
            await _run_sweep_for_user(user_id)
        except Exception:
            logger.exception("Sweep failed for user %s", user_id)


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
