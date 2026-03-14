"""CRUD endpoints for Things."""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from ..database import db
from ..models import Thing, ThingCreate, ThingUpdate
from ..vector_store import delete_thing as vs_delete, upsert_thing

router = APIRouter(prefix="/things", tags=["things"])


def _parse_dt(val: str | None) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    return datetime.fromisoformat(val)


def _row_to_thing(row) -> Thing:
    data = row["data"]
    if isinstance(data, str):
        data = json.loads(data) if data else None
    return Thing(
        id=row["id"],
        title=row["title"],
        type_hint=row["type_hint"],
        parent_id=row["parent_id"],
        checkin_date=_parse_dt(row["checkin_date"]),
        priority=row["priority"],
        active=bool(row["active"]),
        data=data,
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
    )


@router.get("", response_model=list[Thing], summary="List Things")
def list_things(
    active_only: bool = Query(True, description="Filter to active Things only"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    with db() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM things WHERE active = 1 ORDER BY checkin_date ASC, priority ASC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM things ORDER BY checkin_date ASC, priority ASC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
    return [_row_to_thing(r) for r in rows]


@router.post("", response_model=Thing, status_code=status.HTTP_201_CREATED, summary="Create a Thing")
def create_thing(body: ThingCreate, background_tasks: BackgroundTasks):
    thing_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    data_json = json.dumps(body.data) if body.data is not None else None
    checkin = body.checkin_date.isoformat() if body.checkin_date else None

    if body.parent_id:
        with db() as conn:
            parent = conn.execute("SELECT id FROM things WHERE id = ?", (body.parent_id,)).fetchone()
        if not parent:
            raise HTTPException(status_code=404, detail=f"Parent thing '{body.parent_id}' not found")

    with db() as conn:
        conn.execute(
            """INSERT INTO things (id, title, type_hint, parent_id, checkin_date, priority, active, data, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (thing_id, body.title, body.type_hint, body.parent_id, checkin,
             body.priority, int(body.active), data_json, now, now),
        )
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
    background_tasks.add_task(upsert_thing, dict(row))
    return _row_to_thing(row)


@router.get("/{thing_id}", response_model=Thing, summary="Get a Thing")
def get_thing(thing_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Thing '{thing_id}' not found")
    return _row_to_thing(row)


@router.patch("/{thing_id}", response_model=Thing, summary="Update a Thing")
def update_thing(thing_id: str, body: ThingUpdate, background_tasks: BackgroundTasks):
    with db() as conn:
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Thing '{thing_id}' not found")

        if body.parent_id is not None:
            if body.parent_id == thing_id:
                raise HTTPException(status_code=422, detail="A Thing cannot be its own parent")
            parent = conn.execute("SELECT id FROM things WHERE id = ?", (body.parent_id,)).fetchone()
            if not parent:
                raise HTTPException(status_code=404, detail=f"Parent thing '{body.parent_id}' not found")

        fields: dict = {}
        if body.title is not None:
            fields["title"] = body.title
        if body.type_hint is not None:
            fields["type_hint"] = body.type_hint
        if body.parent_id is not None:
            fields["parent_id"] = body.parent_id
        if body.checkin_date is not None:
            fields["checkin_date"] = body.checkin_date.isoformat()
        if body.priority is not None:
            fields["priority"] = body.priority
        if body.active is not None:
            fields["active"] = int(body.active)
        if body.data is not None:
            fields["data"] = json.dumps(body.data)
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [thing_id]
        conn.execute(f"UPDATE things SET {set_clause} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
    background_tasks.add_task(upsert_thing, dict(row))
    return _row_to_thing(row)


@router.delete("/{thing_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a Thing")
def delete_thing(thing_id: str, background_tasks: BackgroundTasks):
    with db() as conn:
        row = conn.execute("SELECT id FROM things WHERE id = ?", (thing_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Thing '{thing_id}' not found")
        conn.execute("DELETE FROM things WHERE id = ?", (thing_id,))
    background_tasks.add_task(vs_delete, thing_id)
