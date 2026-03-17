"""Sweep endpoints — run nightly sweep (SQL candidates + LLM reflection + learnings)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from ..auth import require_user
from ..sweep import (
    LearningResult,
    ReflectionResult,
    collect_candidates,
    generate_learnings,
    reflect_on_candidates,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sweep", tags=["sweep"])


@router.post("/run", summary="Run nightly sweep")
async def run_sweep(user_id: str = Depends(require_user)) -> dict[str, Any]:
    """Run the full nightly sweep: SQL candidates + LLM reflection + learning generation.

    Returns the candidates found, findings created, and learnings generated.
    """
    candidates = collect_candidates()
    reflection: ReflectionResult = await reflect_on_candidates(candidates)
    learnings: LearningResult = await generate_learnings(user_id=user_id)

    return {
        "candidates_found": len(candidates),
        "findings_created": reflection.findings_created,
        "findings": reflection.findings,
        "learnings_created": learnings.learnings_created,
        "learnings": learnings.learnings,
        "usage": {
            "reflection": reflection.usage,
            "learnings": learnings.usage,
        },
    }


@router.post("/learnings", summary="Generate learnings from conversations")
async def run_learning_generation(user_id: str = Depends(require_user)) -> dict[str, Any]:
    """Run learning generation: analyze recent conversations to extract user patterns.

    Creates Learning Things tagged #learning, connected to User Thing via
    LearnedAbout relationship. This is the nightly sweep's learning phase.
    """
    result: LearningResult = await generate_learnings(user_id=user_id)

    return {
        "learnings_created": result.learnings_created,
        "learnings": result.learnings,
        "usage": result.usage,
    }
