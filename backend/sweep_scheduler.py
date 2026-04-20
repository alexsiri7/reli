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
    from sqlmodel import Session, select

    import backend.db_engine as _engine_mod

    from .db_models import UserRecord

    with Session(_engine_mod.engine) as session:
        records = session.exec(select(UserRecord).order_by(UserRecord.created_at)).all()  # type: ignore[arg-type]
    if not records:
        return [""]  # No users — run in legacy single-user mode
    return [r.id for r in records]


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
    from sqlmodel import Session

    import backend.db_engine as _engine_mod

    from .db_models import SweepRunRecord

    with Session(_engine_mod.engine) as session:
        existing = session.get(SweepRunRecord, run_id)
        if existing:
            existing.status = status
            existing.candidates_found = candidates_found
            existing.findings_created = findings_created
            existing.model = model
            existing.prompt_tokens = prompt_tokens
            existing.completion_tokens = completion_tokens
            existing.cost_usd = cost_usd
            existing.error = error
            if completed_at:
                existing.completed_at = datetime.fromisoformat(completed_at)
        else:
            session.add(
                SweepRunRecord(
                    id=run_id,
                    user_id=user_id or None,
                    status=status,
                    candidates_found=candidates_found,
                    findings_created=findings_created,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost_usd,
                    error=error,
                    started_at=datetime.fromisoformat(started_at) if started_at else datetime.now(timezone.utc),
                    completed_at=datetime.fromisoformat(completed_at) if completed_at else None,
                )
            )
        session.commit()


async def _run_dependency_sweep_for_user(user_id: str, user_label: str) -> None:
    """Run the dependency detection sweep for one user, logging results."""
    from .dependency_sweep import run_dependency_sweep

    try:
        async with asyncio.timeout(300):
            dep_result = await run_dependency_sweep(user_id=user_id)
        if dep_result.suggestions_created or dep_result.findings_created:
            logger.info(
                "Dependency sweep [%s]: %d suggestions, %d findings",
                user_label,
                dep_result.suggestions_created,
                dep_result.findings_created,
            )
    except TimeoutError:
        logger.error("Dependency sweep timed out for user %s (300s limit)", user_label)
    except Exception:
        logger.exception("Dependency sweep failed for user %s", user_label)


async def _run_sweep_for_user(user_id: str) -> None:
    """Execute one sweep cycle for a single user."""
    from .sweep import collect_candidates, dismiss_stale_findings, reflect_on_candidates

    run_id = f"sr-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    _log_run(run_id, user_id, status="running", started_at=now)

    try:
        # Phase 0: clean up stale findings
        user_label = user_id[:8] if user_id else "legacy"
        dismissed = dismiss_stale_findings(user_id)
        if dismissed:
            logger.info("Sweep [%s] dismissed %d stale findings", user_label, dismissed)

        candidates = collect_candidates(user_id=user_id)
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
            # Run preference aggregation even when no candidates
            try:
                from .preference_sweep import aggregate_preference_patterns

                async with asyncio.timeout(300):
                    pref_result = await aggregate_preference_patterns(user_id=user_id)
                if pref_result.preferences_created or pref_result.preferences_updated:
                    logger.info(
                        "Preference sweep [%s]: %d created, %d updated",
                        user_label,
                        pref_result.preferences_created,
                        pref_result.preferences_updated,
                    )
            except TimeoutError:
                logger.error("Preference sweep timed out for user %s (300s limit)", user_label)
            except Exception:
                logger.exception("Preference sweep failed for user %s", user_label)

            # Run communication style aggregation even when no candidates
            try:
                from .preference_sweep import aggregate_communication_style_patterns

                async with asyncio.timeout(300):
                    comm_result = await aggregate_communication_style_patterns(user_id=user_id)
                if comm_result.patterns_added or comm_result.patterns_reinforced or comm_result.patterns_removed:
                    logger.info(
                        "Comm style sweep [%s]: %d added, %d reinforced, %d removed",
                        user_label,
                        comm_result.patterns_added,
                        comm_result.patterns_reinforced,
                        comm_result.patterns_removed,
                    )
            except TimeoutError:
                logger.error("Comm style sweep timed out for user %s (300s limit)", user_label)
            except Exception:
                logger.exception("Comm style sweep failed for user %s", user_label)

            # Dependency sweep: LLM-powered implicit dependency detection (runs even when no candidates)
            await _run_dependency_sweep_for_user(user_id, user_label)

            # Still generate morning briefing (captures priorities, overdue, blockers)
            try:
                from .morning_briefing import generate_morning_briefing, store_morning_briefing

                async with asyncio.timeout(300):
                    content = await asyncio.to_thread(generate_morning_briefing, user_id)
                    await asyncio.to_thread(store_morning_briefing, user_id, content)
                logger.info("Morning briefing generated for user %s (no sweep candidates)", user_label)
            except TimeoutError:
                logger.error("Morning briefing timed out for user %s (300s limit)", user_label)
            except Exception:
                logger.exception("Failed to generate morning briefing for user %s", user_label)

            # Generate weekly briefing on Mondays
            try:
                if datetime.now().weekday() == 0:  # 0 = Monday
                    from .weekly_briefing import generate_weekly_briefing, store_weekly_briefing

                    async with asyncio.timeout(300):
                        weekly_content = await asyncio.to_thread(generate_weekly_briefing, user_id)
                        await asyncio.to_thread(store_weekly_briefing, user_id, weekly_content)
                    logger.info("Weekly briefing generated for user %s (no sweep candidates)", user_label)
            except TimeoutError:
                logger.error("Weekly briefing timed out for user %s (300s limit)", user_label)
            except Exception:
                logger.exception("Failed to generate weekly briefing for user %s", user_label)
            return

        async with asyncio.timeout(300):
            result = await reflect_on_candidates(candidates, user_id=user_id)

        # Preference aggregation: detect behavioral patterns from interactions
        try:
            from .preference_sweep import aggregate_preference_patterns

            async with asyncio.timeout(300):
                pref_result = await aggregate_preference_patterns(user_id=user_id)
            if pref_result.preferences_created or pref_result.preferences_updated:
                logger.info(
                    "Preference sweep [%s]: %d created, %d updated",
                    user_label,
                    pref_result.preferences_created,
                    pref_result.preferences_updated,
                )
        except TimeoutError:
            logger.error("Preference sweep timed out for user %s (300s limit)", user_label)
        except Exception:
            logger.exception("Preference sweep failed for user %s", user_label)

        # Communication style aggregation: reinforce reli_communication patterns
        try:
            from .preference_sweep import aggregate_communication_style_patterns

            async with asyncio.timeout(300):
                comm_result = await aggregate_communication_style_patterns(user_id=user_id)
            if comm_result.patterns_added or comm_result.patterns_reinforced or comm_result.patterns_removed:
                logger.info(
                    "Comm style sweep [%s]: %d added, %d reinforced, %d removed",
                    user_label,
                    comm_result.patterns_added,
                    comm_result.patterns_reinforced,
                    comm_result.patterns_removed,
                )
        except TimeoutError:
            logger.error("Comm style sweep timed out for user %s (300s limit)", user_label)
        except Exception:
            logger.exception("Comm style sweep failed for user %s", user_label)

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

        # Breakdown sweep: auto-create subtasks for broad Things without children
        try:
            from .sweep import breakdown_broad_things

            async with asyncio.timeout(300):
                bd_result = await breakdown_broad_things(user_id=user_id)
            if bd_result.things_created:
                logger.info(
                    "Breakdown sweep [%s]: %d subtasks created under %d parents",
                    user_label,
                    bd_result.things_created,
                    bd_result.parents_broken_down,
                )
        except TimeoutError:
            logger.error("Breakdown sweep timed out for user %s (300s limit)", user_label)
        except Exception:
            logger.exception("Breakdown sweep failed for user %s", user_label)

        # Dependency sweep: LLM-powered implicit dependency detection
        await _run_dependency_sweep_for_user(user_id, user_label)

        # Generate morning briefing after sweep completes
        try:
            from .morning_briefing import generate_morning_briefing, store_morning_briefing

            async with asyncio.timeout(300):
                content = await asyncio.to_thread(generate_morning_briefing, user_id)
                await asyncio.to_thread(store_morning_briefing, user_id, content)
            logger.info("Morning briefing generated for user %s", user_label)
        except TimeoutError:
            logger.error("Morning briefing timed out for user %s (300s limit)", user_label)
        except Exception:
            logger.exception("Failed to generate morning briefing for user %s", user_label)

        # Generate weekly briefing on Mondays
        try:
            if datetime.now().weekday() == 0:  # 0 = Monday
                from .weekly_briefing import generate_weekly_briefing, store_weekly_briefing

                async with asyncio.timeout(300):
                    weekly_content = await asyncio.to_thread(generate_weekly_briefing, user_id)
                    await asyncio.to_thread(store_weekly_briefing, user_id, weekly_content)
                logger.info("Weekly briefing generated for user %s", user_label)
        except TimeoutError:
            logger.error("Weekly briefing timed out for user %s (300s limit)", user_label)
        except Exception:
            logger.exception("Failed to generate weekly briefing for user %s", user_label)
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

        async with asyncio.timeout(300):
            conn_result = await run_connection_sweep()
        logger.info(
            "Connection sweep: %d candidates, %d suggestions created",
            conn_result.candidates_found,
            conn_result.suggestions_created,
        )
    except TimeoutError:
        logger.error("Connection sweep timed out (300s limit)")
    except Exception:
        logger.exception("Connection sweep failed")

    logger.info("Sweep cycle complete")


async def _process_scheduled_tasks() -> None:
    """Process all due scheduled tasks across all users."""
    from sqlmodel import Session

    import backend.db_engine as _engine_mod

    from .db_models import ScheduledTaskRecord, SweepFindingRecord
    from .tools import get_due_scheduled_tasks

    user_ids = _get_all_user_ids()
    for user_id in user_ids:
        due_tasks = get_due_scheduled_tasks(user_id=user_id)
        if not due_tasks:
            continue

        # "legacy" = pre-multi-tenant rows where user_id IS NULL
        user_label = user_id[:8] if user_id else "legacy"
        logger.info("Processing %d due scheduled task(s) for user %s", len(due_tasks), user_label)

        with Session(_engine_mod.engine) as session:
            for task_dict in due_tasks:
                task_record = session.get(ScheduledTaskRecord, task_dict["id"])
                if not task_record or task_record.executed_at is not None:
                    continue

                task_type = task_record.task_type
                payload = task_record.payload or {}

                # MVP stub: "check", "sweep_concern", and "custom" types are not yet
                # fully executed — they produce a generic finding so the user
                # sees something in their briefing.  Full execution is deferred.
                if task_type == "remind":
                    finding_type = "reminder"
                    default_message = "Scheduled reminder"
                else:
                    finding_type = f"scheduled_{task_type}"
                    default_message = f"Scheduled {task_type} task due"
                session.add(SweepFindingRecord(
                    id=str(uuid.uuid4()),
                    thing_id=task_record.thing_id,
                    finding_type=finding_type,
                    message=payload.get("message", default_message),
                    priority=2,
                    user_id=user_id or None,
                ))

                task_record.executed_at = datetime.now(timezone.utc)
                task_record.result = {"status": "executed", "task_type": task_type}
                session.add(task_record)

            session.commit()


async def _scheduled_task_loop() -> None:
    """Background loop that processes due scheduled tasks every 15 minutes."""
    logger.info("Scheduled task processor started — running every 15 minutes")

    while True:
        await asyncio.sleep(900)  # Sleep first to avoid running before DB init
        try:
            await _process_scheduled_tasks()
        except Exception:
            logger.exception("Unexpected error in scheduled task processor")


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
_task_scheduled: asyncio.Task[None] | None = None
_scheduler_lock = asyncio.Lock()


async def start_scheduler() -> None:
    """Start the sweep and scheduled task background tasks.  Safe to call multiple times."""
    global _task, _task_scheduled
    async with _scheduler_lock:
        if _task is None or _task.done():
            _task = asyncio.create_task(sweep_loop())
            logger.info("Sweep scheduler task created")
        if _task_scheduled is None or _task_scheduled.done():
            _task_scheduled = asyncio.create_task(_scheduled_task_loop())
            logger.info("Scheduled task processor task created")


async def stop_scheduler() -> None:
    """Cancel the sweep and scheduled task background tasks if running."""
    global _task, _task_scheduled
    async with _scheduler_lock:
        if _task is not None and not _task.done():
            _task.cancel()
            try:
                await _task
            except asyncio.CancelledError:
                pass
            logger.info("Sweep scheduler task cancelled")
        _task = None

        if _task_scheduled is not None and not _task_scheduled.done():
            _task_scheduled.cancel()
            try:
                await _task_scheduled
            except asyncio.CancelledError:
                pass
            logger.info("Scheduled task processor task cancelled")
        _task_scheduled = None
