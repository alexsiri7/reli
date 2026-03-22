"""Sweep endpoints — run nightly sweep (SQL candidates + LLM reflection)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from ..auth import require_user, user_filter
from ..database import db
from ..sweep import (
    PreferenceAggregationResult,
    ReflectionResult,
    aggregate_preferences,
    collect_candidates,
    reflect_on_candidates,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sweep", tags=["sweep"])


@router.post("/run", summary="Run nightly sweep")
async def run_sweep(user_id: str = Depends(require_user)) -> dict[str, Any]:
    """Run the full nightly sweep: SQL candidate collection + LLM reflection.

    Returns the candidates found and the findings created by LLM reflection.
    """
    candidates = collect_candidates(user_id=user_id)
    result: ReflectionResult = await reflect_on_candidates(candidates, user_id=user_id)

    return {
        "candidates_found": len(candidates),
        "findings_created": result.findings_created,
        "findings": result.findings,
        "usage": result.usage,
    }


@router.get("/runs", summary="List sweep run history")
def list_sweep_runs(
    limit: int = 20,
    user_id: str = Depends(require_user),
) -> list[dict[str, Any]]:
    """Return recent sweep run history for the current user."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        rows = conn.execute(
            f"""SELECT * FROM sweep_runs
               WHERE 1=1{uf_sql}
               ORDER BY started_at DESC
               LIMIT ?""",
            (*uf_params, limit),
        ).fetchall()

    return [dict(row) for row in rows]


@router.post("/preferences", summary="Run preference aggregation")
async def run_preference_aggregation(
    lookback_days: int = 7,
    user_id: str = Depends(require_user),
) -> dict[str, Any]:
    """Run the preference aggregation phase: analyze recent interactions for patterns.

    Detects repeated behavioral patterns in chat history and creates or updates
    preference Things with appropriate confidence levels.
    """
    result: PreferenceAggregationResult = await aggregate_preferences(
        user_id=user_id, lookback_days=lookback_days
    )
    return {
        "patterns_created": result.patterns_created,
        "patterns_updated": result.patterns_updated,
        "patterns": result.patterns,
        "usage": result.usage,
    }


@router.post("/connections", summary="Run connection sweep")
async def run_connection_sweep() -> dict[str, Any]:
    """Run the connection sweep: find semantically similar but unconnected Things.

    Returns the candidate pairs found and the suggestions created by LLM validation.
    """
    from ..connection_sweep import run_connection_sweep as _run

    result = await _run()
    return {
        "candidates_found": result.candidates_found,
        "suggestions_created": result.suggestions_created,
        "suggestions": result.suggestions,
        "usage": result.usage,
    }
