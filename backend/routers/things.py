"""CRUD endpoints for Things."""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from ..database import db
from ..models import Relationship, RelationshipCreate, Thing, ThingCreate, ThingUpdate
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
    # SQLite data may be double-encoded (string containing JSON string).
    # Unwrap until we get a dict/list/None or a non-JSON string.
    while isinstance(data, str) and data:
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            break
    if isinstance(data, str):
        data = None
    # Handle surface column (may be missing in older DBs before migration runs)
    surface = True
    try:
        surface = bool(row["surface"]) if row["surface"] is not None else True
    except (IndexError, KeyError):
        pass

    last_referenced = None
    try:
        last_referenced = _parse_dt(row["last_referenced"])
    except (IndexError, KeyError):
        pass

    return Thing(
        id=row["id"],
        title=row["title"],
        type_hint=row["type_hint"],
        parent_id=row["parent_id"],
        checkin_date=_parse_dt(row["checkin_date"]),
        priority=row["priority"],
        active=bool(row["active"]),
        surface=surface,
        data=data,
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
        last_referenced=last_referenced,
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
            """INSERT INTO things (id, title, type_hint, parent_id, checkin_date, priority, active, surface, data, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (thing_id, body.title, body.type_hint, body.parent_id, checkin,
             body.priority, int(body.active), int(body.surface), data_json, now, now),
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
        if body.surface is not None:
            fields["surface"] = int(body.surface)
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


# ── Relationships ────────────────────────────────────────────────────────────


def _parse_rel_row(row) -> Relationship:
    meta = row["metadata"]
    if isinstance(meta, str) and meta:
        try:
            meta = json.loads(meta)
        except (json.JSONDecodeError, ValueError):
            meta = None
    if isinstance(meta, str):
        meta = None
    return Relationship(
        id=row["id"],
        from_thing_id=row["from_thing_id"],
        to_thing_id=row["to_thing_id"],
        relationship_type=row["relationship_type"],
        metadata=meta,
        created_at=_parse_dt(row["created_at"]),
    )


@router.get("/{thing_id}/relationships", response_model=list[Relationship], summary="List relationships for a Thing")
def list_relationships(thing_id: str):
    with db() as conn:
        row = conn.execute("SELECT id FROM things WHERE id = ?", (thing_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Thing '{thing_id}' not found")
        rows = conn.execute(
            "SELECT * FROM thing_relationships WHERE from_thing_id = ? OR to_thing_id = ?",
            (thing_id, thing_id),
        ).fetchall()
    return [_parse_rel_row(r) for r in rows]


@router.post("/relationships", response_model=Relationship, status_code=status.HTTP_201_CREATED, summary="Create a relationship")
def create_relationship(body: RelationshipCreate):
    rel_id = str(uuid.uuid4())
    meta_json = json.dumps(body.metadata) if body.metadata is not None else None
    with db() as conn:
        # Validate both things exist
        for tid, label in [(body.from_thing_id, "from"), (body.to_thing_id, "to")]:
            if not conn.execute("SELECT id FROM things WHERE id = ?", (tid,)).fetchone():
                raise HTTPException(status_code=404, detail=f"{label}_thing_id '{tid}' not found")
        if body.from_thing_id == body.to_thing_id:
            raise HTTPException(status_code=422, detail="A Thing cannot have a relationship with itself")
        conn.execute(
            "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type, metadata) VALUES (?, ?, ?, ?, ?)",
            (rel_id, body.from_thing_id, body.to_thing_id, body.relationship_type, meta_json),
        )
        row = conn.execute("SELECT * FROM thing_relationships WHERE id = ?", (rel_id,)).fetchone()
    return _parse_rel_row(row)


@router.delete("/relationships/{rel_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a relationship")
def delete_relationship(rel_id: str):
    with db() as conn:
        row = conn.execute("SELECT id FROM thing_relationships WHERE id = ?", (rel_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Relationship '{rel_id}' not found")
        conn.execute("DELETE FROM thing_relationships WHERE id = ?", (rel_id,))
