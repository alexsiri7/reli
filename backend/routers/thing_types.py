"""CRUD endpoints for Thing Types."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from ..database import db
from ..models import ThingType, ThingTypeCreate, ThingTypeUpdate

router = APIRouter(prefix="/thing-types", tags=["thing-types"])


def _parse_dt(val: str | None) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    return datetime.fromisoformat(val)


def _row_to_thing_type(row: Any) -> ThingType:
    return ThingType(
        id=row["id"],
        name=row["name"],
        icon=row["icon"],
        color=row["color"],
        created_at=_parse_dt(row["created_at"]) or datetime.min,
    )


@router.get("", response_model=list[ThingType], summary="List all Thing Types")
def list_thing_types(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ThingType]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM thing_types ORDER BY name ASC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [_row_to_thing_type(r) for r in rows]


@router.get("/{type_id}", response_model=ThingType, summary="Get a Thing Type")
def get_thing_type(type_id: str) -> ThingType:
    with db() as conn:
        row = conn.execute("SELECT * FROM thing_types WHERE id = ?", (type_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Thing type '{type_id}' not found")
    return _row_to_thing_type(row)


@router.post("", response_model=ThingType, status_code=status.HTTP_201_CREATED, summary="Create a Thing Type")
def create_thing_type(body: ThingTypeCreate) -> ThingType:
    type_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        # Check for duplicate name
        existing = conn.execute("SELECT id FROM thing_types WHERE name = ?", (body.name,)).fetchone()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Thing type with name '{body.name}' already exists",
            )
        conn.execute(
            "INSERT INTO thing_types (id, name, icon, color, created_at) VALUES (?, ?, ?, ?, ?)",
            (type_id, body.name, body.icon, body.color, now),
        )
        row = conn.execute("SELECT * FROM thing_types WHERE id = ?", (type_id,)).fetchone()
    return _row_to_thing_type(row)


@router.patch("/{type_id}", response_model=ThingType, summary="Update a Thing Type")
def update_thing_type(type_id: str, body: ThingTypeUpdate) -> ThingType:
    with db() as conn:
        row = conn.execute("SELECT * FROM thing_types WHERE id = ?", (type_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Thing type '{type_id}' not found")

        fields: dict[str, str | None] = {}
        if body.name is not None:
            # Check for duplicate name (excluding self)
            existing = conn.execute(
                "SELECT id FROM thing_types WHERE name = ? AND id != ?",
                (body.name, type_id),
            ).fetchone()
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail=f"Thing type with name '{body.name}' already exists",
                )
            fields["name"] = body.name
        if body.icon is not None:
            fields["icon"] = body.icon
        if body.color is not None:
            fields["color"] = body.color

        if not fields:
            return _row_to_thing_type(row)

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [type_id]
        conn.execute(f"UPDATE thing_types SET {set_clause} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM thing_types WHERE id = ?", (type_id,)).fetchone()
    return _row_to_thing_type(row)


@router.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a Thing Type")
def delete_thing_type(type_id: str) -> None:
    with db() as conn:
        row = conn.execute("SELECT id FROM thing_types WHERE id = ?", (type_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Thing type '{type_id}' not found")
        conn.execute("DELETE FROM thing_types WHERE id = ?", (type_id,))
