"""Sweep endpoints — run nightly sweep (SQL candidates + LLM reflection)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

import backend.db_engine as _engine_mod
from ..auth import require_user
from ..db_engine import user_filter_clause
from ..db_models import SweepRunRecord
from ..sweep import (
    GapQuestionResult,
    PatternAggregationResult,
    ReflectionResult,
    aggregate_personality_patterns,
    collect_candidates,
    find_incomplete_things,
    generate_gap_questions,
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

    # Phase 3: Aggregate personality patterns from behavioral signals
    pattern_result: PatternAggregationResult = await aggregate_personality_patterns(user_id=user_id)

    return {
        "candidates_found": len(candidates),
        "findings_created": result.findings_created,
        "findings": result.findings,
        "personality_patterns_updated": pattern_result.patterns_updated,
        "personality_patterns": pattern_result.patterns,
        "usage": result.usage,
    }


@router.get("/runs", summary="List sweep run history")
def list_sweep_runs(
    limit: int = 20,
    user_id: str = Depends(require_user),
) -> list[dict[str, Any]]:
    """Return recent sweep run history for the current user."""
    with Session(_engine_mod.engine) as session:
        stmt = (
            select(SweepRunRecord)
            .where(user_filter_clause(SweepRunRecord.user_id, user_id))
            .order_by(SweepRunRecord.started_at.desc())  # type: ignore[union-attr]
            .limit(limit)
        )
        rows = session.exec(stmt).all()

    return [row.model_dump() for row in rows]


@router.post("/gaps", summary="Detect incomplete Things and generate questions")
async def run_gap_sweep(user_id: str = Depends(require_user)) -> dict[str, Any]:
    """Detect Things with missing information and generate open questions.

    Phase 1: SQL query finds Things with gaps (no dates, minimal data,
    name-only people, no deadlines).
    Phase 2: LLM generates tailored questions and stores them as
    open_questions on each Thing.
    """
    with Session(_engine_mod.engine) as session:
        candidates = find_incomplete_things(session, user_id=user_id)

    result: GapQuestionResult = await generate_gap_questions(candidates, user_id=user_id)

    return {
        "candidates_found": len(candidates),
        "things_updated": result.things_updated,
        "questions_generated": result.questions_generated,
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


@router.post("/dependencies", summary="Run dependency detection sweep")
async def run_dependency_sweep_endpoint(user_id: str = Depends(require_user)) -> dict[str, Any]:
    """Run the dependency detection sweep: find clusters of related Things,
    detect implicit dependencies via LLM, surface conflicts as sweep findings.

    Creates ConnectionSuggestion records for detected dependencies (user reviews)
    and SweepFinding records for detected conflicts (shown in briefing).
    """
    from ..dependency_sweep import run_dependency_sweep as _run

    result = await _run(user_id=user_id)
    return {
        "clusters_found": result.clusters_found,
        "suggestions_created": result.suggestions_created,
        "findings_created": result.findings_created,
        "suggestions": result.suggestions,
        "findings": result.findings,
        "usage": result.usage,
    }
