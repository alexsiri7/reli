"""Sweep endpoints — run nightly sweep and view sweep run history."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from ..agents import UsageStats
from ..auth import require_user
from ..database import db
from ..sweep import ReflectionResult, collect_candidates, reflect_on_candidates
from ..sweep_agent import run_sweep_agent
from ..sweep_scheduler import _log_sweep_complete, _log_sweep_start

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sweep", tags=["sweep"])


@router.post("/run", summary="Run sweep (SQL candidates + LLM reflection)")
async def run_sweep(request: Request) -> dict[str, Any]:
    """Run the SQL candidate collection + LLM reflection sweep.

    Returns the candidates found and the findings created by LLM reflection.
    """
    candidates = collect_candidates()
    result: ReflectionResult = await reflect_on_candidates(candidates)

    return {
        "candidates_found": len(candidates),
        "findings_created": result.findings_created,
        "findings": result.findings,
        "usage": result.usage,
    }


@router.post("/run-agent", summary="Run sweep reasoning agent")
async def run_sweep_agent_endpoint(request: Request) -> dict[str, Any]:
    """Run the full sweep reasoning agent against the user's complete graph.

    This runs the reasoning pipeline with tool calling (create, update,
    relate, propose) against all active Things and relationships.
    Results are logged in sweep_runs.
    """
    user_id: str = request.state.user_id
    usage_stats = UsageStats()
    run_id = _log_sweep_start(user_id)

    try:
        # Phase 1: SQL candidates + reflection
        candidates = collect_candidates()
        reflection_findings = 0
        if candidates:
            reflection_result = await reflect_on_candidates(candidates)
            reflection_findings = reflection_result.findings_created

        # Phase 2: Reasoning agent
        from ..config import Settings

        s = Settings()
        sweep_model = s.SWEEP_MODEL or None

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

        _log_sweep_complete(
            run_id,
            candidates_found=len(candidates),
            findings_created=reflection_findings + agent_findings,
            things_created=agent_created,
            things_updated=agent_updated,
            relationships_created=agent_rels,
            thing_count=agent_result.get("thing_count", 0),
            model=sweep_model or "",
            usage_stats=usage_stats,
        )

        return {
            "run_id": run_id,
            "candidates_found": len(candidates),
            "reflection_findings": reflection_findings,
            "agent_result": {
                "reasoning_summary": agent_result.get("reasoning_summary", ""),
                "thing_count": agent_result.get("thing_count", 0),
                "relationship_count": agent_result.get("relationship_count", 0),
                "things_created": agent_created,
                "things_updated": agent_updated,
                "relationships_created": agent_rels,
                "findings_created": agent_findings,
            },
            "usage": usage_stats.to_dict(),
        }

    except Exception as exc:
        logger.exception("Manual sweep agent run failed")
        _log_sweep_complete(
            run_id,
            status="failed",
            error=str(exc),
            usage_stats=usage_stats,
        )
        raise


@router.get("/runs", summary="List sweep run history")
async def list_sweep_runs(
    request: Request,
    limit: int = 20,
) -> dict[str, Any]:
    """Return recent sweep run history for the current user."""
    user_id: str = request.state.user_id

    with db() as conn:
        rows = conn.execute(
            """SELECT * FROM sweep_runs
               WHERE user_id = ?
               ORDER BY started_at DESC
               LIMIT ?""",
            (user_id, min(limit, 100)),
        ).fetchall()

    runs = [dict(row) for row in rows]
    return {"runs": runs, "count": len(runs)}
