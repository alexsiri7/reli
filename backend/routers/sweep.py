"""Sweep endpoints — nightly sweep (SQL + LLM reflection) and reasoning sweep."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_user
from ..database import db
from ..models import SweepRun, SweepRunsResponse
from ..sweep import ReflectionResult, collect_candidates, reflect_on_candidates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sweep", tags=["sweep"])


@router.post("/run", summary="Run nightly sweep (SQL + LLM reflection)")
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


@router.post(
    "/reasoning/run",
    response_model=SweepRun,
    summary="Trigger sweep reasoning for current user",
)
async def run_reasoning_sweep(user_id: str = Depends(require_user)) -> SweepRun:
    """Manually trigger the sweep reasoning pipeline for the current user.

    Runs the reasoning agent against the user's full knowledge graph with
    guard rails (no delete, only create/update/propose).
    """
    from ..sweep_reasoning import run_sweep_reasoning

    result = await run_sweep_reasoning(user_id, trigger="manual")

    # Fetch the stored run record
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM sweep_runs WHERE id = ?", (result.run_id,)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=500, detail="Sweep run record not found")

    return SweepRun(
        id=row["id"],
        user_id=row["user_id"],
        status=row["status"],
        trigger=row["trigger"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        things_processed=row["things_processed"] or 0,
        findings_created=row["findings_created"] or 0,
        changes_created=row["changes_created"] or 0,
        changes_updated=row["changes_updated"] or 0,
        relationships_created=row["relationships_created"] or 0,
        model=row["model"],
        prompt_tokens=row["prompt_tokens"] or 0,
        completion_tokens=row["completion_tokens"] or 0,
        cost_usd=row["cost_usd"] or 0.0,
        error_message=row["error_message"],
    )


@router.get(
    "/runs",
    response_model=SweepRunsResponse,
    summary="List sweep reasoning runs",
)
def list_sweep_runs(
    limit: int = 20,
    offset: int = 0,
    user_id: str = Depends(require_user),
) -> SweepRunsResponse:
    """List sweep reasoning run history for the current user."""
    from ..auth import user_filter

    uf_sql, uf_params = user_filter(user_id)

    with db() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM sweep_runs WHERE 1=1{uf_sql}",
            uf_params,
        ).fetchone()
        total = total_row["cnt"] if total_row else 0

        rows = conn.execute(
            f"SELECT * FROM sweep_runs WHERE 1=1{uf_sql}"
            " ORDER BY started_at DESC LIMIT ? OFFSET ?",
            [*uf_params, limit, offset],
        ).fetchall()

    runs = [
        SweepRun(
            id=r["id"],
            user_id=r["user_id"],
            status=r["status"],
            trigger=r["trigger"],
            started_at=r["started_at"],
            completed_at=r["completed_at"],
            things_processed=r["things_processed"] or 0,
            findings_created=r["findings_created"] or 0,
            changes_created=r["changes_created"] or 0,
            changes_updated=r["changes_updated"] or 0,
            relationships_created=r["relationships_created"] or 0,
            model=r["model"],
            prompt_tokens=r["prompt_tokens"] or 0,
            completion_tokens=r["completion_tokens"] or 0,
            cost_usd=r["cost_usd"] or 0.0,
            error_message=r["error_message"],
        )
        for r in rows
    ]

    return SweepRunsResponse(runs=runs, total=total)


@router.get(
    "/runs/{run_id}",
    response_model=SweepRun,
    summary="Get sweep run details",
)
def get_sweep_run(
    run_id: str,
    user_id: str = Depends(require_user),
) -> SweepRun:
    """Get details of a specific sweep reasoning run."""
    from ..auth import user_filter

    uf_sql, uf_params = user_filter(user_id)

    with db() as conn:
        row = conn.execute(
            f"SELECT * FROM sweep_runs WHERE id = ?{uf_sql}",
            [run_id, *uf_params],
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Sweep run not found")

    return SweepRun(
        id=row["id"],
        user_id=row["user_id"],
        status=row["status"],
        trigger=row["trigger"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        things_processed=row["things_processed"] or 0,
        findings_created=row["findings_created"] or 0,
        changes_created=row["changes_created"] or 0,
        changes_updated=row["changes_updated"] or 0,
        relationships_created=row["relationships_created"] or 0,
        model=row["model"],
        prompt_tokens=row["prompt_tokens"] or 0,
        completion_tokens=row["completion_tokens"] or 0,
        cost_usd=row["cost_usd"] or 0.0,
        error_message=row["error_message"],
    )
