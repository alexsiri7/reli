"""Sweep endpoints — run sweep (SQL candidates + LLM reflection + reasoning).

Manual trigger for the sweep pipeline. The scheduled sweep runs automatically
via sweep_scheduler.py, but this endpoint allows on-demand triggering.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from ..auth import require_user, user_filter
from ..database import db
from ..sweep import run_full_sweep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sweep", tags=["sweep"])


@router.post("/run", summary="Run sweep for the current user")
async def run_sweep(user_id: str = Depends(require_user)) -> dict[str, Any]:
    """Run the full sweep pipeline for the current user.

    Executes: SQL candidate collection → LLM reflection → reasoning pipeline.
    All runs are logged in the sweep_runs table.
    """
    result = await run_full_sweep(
        user_id=user_id or None,
        trigger="manual",
    )

    return {
        "run_id": result.run_id,
        "candidates_found": result.candidates_found,
        "findings_created": result.findings_created,
        "things_created": result.things_created,
        "things_updated": result.things_updated,
        "relationships_created": result.relationships_created,
        "usage": result.usage,
        "error": result.error,
    }


@router.get("/runs", summary="List sweep run history")
def list_sweep_runs(
    limit: int = 20,
    user_id: str = Depends(require_user),
) -> list[dict[str, Any]]:
    """Return recent sweep runs for the current user."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        rows = conn.execute(
            f"""SELECT * FROM sweep_runs
               WHERE 1=1{uf_sql}
               ORDER BY started_at DESC
               LIMIT ?""",
            (*uf_params, min(limit, 100)),
        ).fetchall()
    return [dict(r) for r in rows]
