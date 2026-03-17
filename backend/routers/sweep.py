"""Sweep endpoints — run nightly sweep (SQL candidates + LLM reflection)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from ..cross_project_sweep import (
    collect_cross_project_findings,
    persist_findings,
    run_cross_project_sweep,
)
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


@router.post("/cross-project", summary="Run cross-project pattern detection")
async def run_cross_project() -> dict[str, Any]:
    """Detect patterns across projects: shared blockers, resource conflicts,
    thematic connections, and duplicated effort.

    Findings are stored as Things tagged #sweep-finding.
    """
    return await run_cross_project_sweep()


@router.get("/cross-project/preview", summary="Preview cross-project findings")
def preview_cross_project() -> dict[str, Any]:
    """Preview cross-project findings without persisting them."""
    findings = collect_cross_project_findings()
    return {
        "findings_detected": len(findings),
        "findings": [
            {
                "finding_type": f.finding_type,
                "title": f.title,
                "message": f.message,
                "priority": f.priority,
                "related_thing_ids": f.related_thing_ids,
                "related_project_ids": f.related_project_ids,
            }
            for f in findings
        ],
    }
