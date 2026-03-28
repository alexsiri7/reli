"""Endpoints for querying the MCP mutations journal."""

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..auth import require_user
from ..database import db

router = APIRouter(prefix="/mutations", tags=["mutations"])


def _row_to_mutation(row: Any) -> dict[str, Any]:
    before = row["before_snapshot"]
    after = row["after_snapshot"]
    if isinstance(before, str) and before:
        try:
            before = json.loads(before)
        except (json.JSONDecodeError, ValueError):
            pass
    if isinstance(after, str) and after:
        try:
            after = json.loads(after)
        except (json.JSONDecodeError, ValueError):
            pass
    return {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "client_id": row["client_id"],
        "operation": row["operation"],
        "thing_id": row["thing_id"],
        "before_snapshot": before,
        "after_snapshot": after,
        "created_at": row["created_at"],
    }


@router.get("", summary="List MCP mutations")
def list_mutations(
    thing_id: str | None = Query(None, description="Filter by Thing ID"),
    operation: str | None = Query(None, description="Filter by operation type"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of results"),
    _user_id: str = Depends(require_user),
) -> list[dict[str, Any]]:
    """Return recent MCP write operations from the mutations journal, newest first.

    Can be filtered by thing_id or operation type (create_thing, update_thing,
    delete_thing, merge_things, create_relationship, delete_relationship).
    """
    where_clauses = []
    params: list[Any] = []

    if thing_id:
        where_clauses.append("thing_id = ?")
        params.append(thing_id)
    if operation:
        where_clauses.append("operation = ?")
        params.append(operation)

    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    params.append(limit)

    with db() as conn:
        rows = conn.execute(
            f"SELECT * FROM mcp_mutations {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()

    return [_row_to_mutation(r) for r in rows]
