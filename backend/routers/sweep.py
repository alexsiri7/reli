"""Sweep endpoints — run nightly sweep (SQL candidates + LLM reflection)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from ..sweep import ReflectionResult, collect_candidates, reflect_on_candidates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sweep", tags=["sweep"])


@router.post("/run", summary="Run nightly sweep")
async def run_sweep() -> dict[str, Any]:
    """Run the full nightly sweep: SQL candidate collection + LLM reflection.

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
