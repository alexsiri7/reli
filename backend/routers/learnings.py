"""Learnings CRUD endpoints — user behavior patterns discovered by meta-learning."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_user, user_filter
from ..database import db
from ..models import Learning, LearningUpdate

router = APIRouter(prefix="/learnings", tags=["learnings"])


def _row_to_learning(row: sqlite3.Row) -> Learning:
    evidence = None
    if row["evidence"]:
        try:
            evidence = json.loads(row["evidence"]) if isinstance(row["evidence"], str) else row["evidence"]
        except (json.JSONDecodeError, TypeError):
            evidence = None
    return Learning(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        category=row["category"],
        confidence=row["confidence"],
        observation_count=row["observation_count"],
        evidence=evidence,
        active=bool(row["active"]),
        last_observed_at=row["last_observed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("", response_model=list[Learning], summary="List learnings")
def list_learnings(
    active_only: bool = True,
    category: str | None = None,
    user_id: str = Depends(require_user),
) -> list[Learning]:
    """List all learnings, optionally filtered by active status and category."""
    uf_sql, uf_params = user_filter(user_id)
    conditions = ["1=1"]
    params: list = []

    if active_only:
        conditions.append("active = 1")
    if category:
        conditions.append("category = ?")
        params.append(category)

    where = " AND ".join(conditions)

    with db() as conn:
        rows = conn.execute(
            f"""SELECT * FROM learnings
                WHERE {where}{uf_sql}
                ORDER BY confidence DESC, updated_at DESC""",
            [*params, *uf_params],
        ).fetchall()

    return [_row_to_learning(r) for r in rows]


@router.get("/{learning_id}", response_model=Learning, summary="Get a learning")
def get_learning(learning_id: str, user_id: str = Depends(require_user)) -> Learning:
    """Get a single learning by ID."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        row = conn.execute(
            f"SELECT * FROM learnings WHERE id = ?{uf_sql}",
            [learning_id, *uf_params],
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Learning not found")
    return _row_to_learning(row)


@router.patch("/{learning_id}", response_model=Learning, summary="Update a learning")
def update_learning(
    learning_id: str,
    body: LearningUpdate,
    user_id: str = Depends(require_user),
) -> Learning:
    """Update a learning's title, description, or active status."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        row = conn.execute(
            f"SELECT * FROM learnings WHERE id = ?{uf_sql}",
            [learning_id, *uf_params],
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Learning not found")

        updates: dict[str, Any] = {}
        if body.title is not None:
            updates["title"] = body.title
        if body.description is not None:
            updates["description"] = body.description
        if body.active is not None:
            updates["active"] = int(body.active)

        if not updates:
            return _row_to_learning(row)

        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values())

        conn.execute(
            f"UPDATE learnings SET {set_clause} WHERE id = ?{uf_sql}",
            [*values, learning_id, *uf_params],
        )
        row = conn.execute("SELECT * FROM learnings WHERE id = ?", (learning_id,)).fetchone()

    return _row_to_learning(row)


@router.delete("/{learning_id}", status_code=204, summary="Delete a learning")
def delete_learning(learning_id: str, user_id: str = Depends(require_user)) -> None:
    """Delete a learning permanently."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        row = conn.execute(
            f"SELECT id FROM learnings WHERE id = ?{uf_sql}",
            [learning_id, *uf_params],
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Learning not found")
        conn.execute(
            f"DELETE FROM learnings WHERE id = ?{uf_sql}",
            [learning_id, *uf_params],
        )
