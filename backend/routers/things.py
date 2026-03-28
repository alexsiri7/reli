"""CRUD endpoints for Things."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ..auth import require_user, user_filter
from ..database import clean_orphan_relationships, db
from ..models import (
    GraphEdge,
    GraphNode,
    GraphResponse,
    MergeHistoryRecord,
    MergeRequest,
    MergeResult,
    MergeSuggestion,
    MergeSuggestionThing,
    OrphanCleanupResult,
    Relationship,
    RelationshipCreate,
    Thing,
    ThingCreate,
    ThingUpdate,
)
from ..vector_store import delete_thing as vs_delete
from ..vector_store import reindex_all, upsert_thing

router = APIRouter(prefix="/things", tags=["things"])


def _parse_dt(val: str | None) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    return datetime.fromisoformat(val)


def _row_to_thing(row: sqlite3.Row) -> Thing:
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

    open_questions = None
    try:
        raw_oq = row["open_questions"]
        if raw_oq:
            oq = raw_oq
            while isinstance(oq, str):
                try:
                    oq = json.loads(oq)
                except (json.JSONDecodeError, ValueError):
                    break
            if isinstance(oq, list):
                open_questions = oq
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
        created_at=_parse_dt(row["created_at"]) or datetime.min,
        updated_at=_parse_dt(row["updated_at"]) or datetime.min,
        last_referenced=last_referenced,
        open_questions=open_questions,
    )


class UserProfileResponse(BaseModel):
    """The user's anchor Thing with its relationships."""

    thing: Thing
    relationships: list[Relationship]

    model_config = {"from_attributes": True}


class UserProfileRelationship(BaseModel):
    """A relationship resolved with the related Thing's title."""

    id: str
    relationship_type: str
    direction: str  # "outgoing" or "incoming"
    related_thing_id: str
    related_thing_title: str


class UserProfileDetail(BaseModel):
    """The user's anchor Thing with resolved relationships."""

    thing: Thing
    relationships: list[UserProfileRelationship]


@router.get("/me", response_model=UserProfileDetail, summary="Get the current user's profile Thing")
def get_user_thing(user_id: str = Depends(require_user)) -> UserProfileDetail:
    """Return the user's anchor Thing (created at sign-up) with resolved relationships."""
    with db() as conn:
        uf_sql, uf_params = user_filter(user_id)
        row = conn.execute(
            "SELECT * FROM things WHERE surface = 0 AND type_hint = 'person'" + uf_sql,
            uf_params,
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User profile Thing not found")

        thing = _row_to_thing(row)
        thing_id = thing.id

        # Fetch relationships with resolved titles
        rel_rows = conn.execute(
            "SELECT r.*, "
            "  CASE WHEN r.from_thing_id = ? THEN t_to.title ELSE t_from.title END AS related_title,"
            "  CASE WHEN r.from_thing_id = ? THEN t_to.id ELSE t_from.id END AS related_id,"
            "  CASE WHEN r.from_thing_id = ? THEN 'outgoing' ELSE 'incoming' END AS direction"
            " FROM thing_relationships r"
            " LEFT JOIN things t_from ON r.from_thing_id = t_from.id"
            " LEFT JOIN things t_to ON r.to_thing_id = t_to.id"
            " WHERE r.from_thing_id = ? OR r.to_thing_id = ?",
            (thing_id, thing_id, thing_id, thing_id, thing_id),
        ).fetchall()

        relationships = [
            UserProfileRelationship(
                id=r["id"],
                relationship_type=r["relationship_type"],
                direction=r["direction"],
                related_thing_id=r["related_id"] or "",
                related_thing_title=r["related_title"] or "Unknown",
            )
            for r in rel_rows
        ]

    return UserProfileDetail(thing=thing, relationships=relationships)


@router.get("/open-questions", response_model=list[Thing], summary="List Things with open questions")
def get_open_questions(
    limit: int = Query(50, ge=1, le=200, description="Maximum number of results"),
    user_id: str = Depends(require_user),
) -> list[Thing]:
    """Return active Things that have non-empty open_questions arrays, ordered by priority then recency."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        rows = conn.execute(
            f"""SELECT * FROM things
               WHERE active = 1
                 AND open_questions IS NOT NULL
                 AND open_questions != '[]'{uf_sql}
               ORDER BY priority ASC, updated_at DESC
               LIMIT ?""",
            [*uf_params, limit],
        ).fetchall()
    return [_row_to_thing(r) for r in rows]


@router.get("/search", response_model=list[Thing], summary="Search Things across the full graph")
def search_things(
    q: str = Query("", description="Free-text search query matched against title, data, type_hint, and relationships"),
    active_only: bool = Query(False, description="Filter to active Things only"),
    type_hint: str | None = Query(None, description="Filter by type_hint (e.g. 'task', 'project', 'person')"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of results"),
    user_id: str = Depends(require_user),
) -> list[Thing]:
    """Search Things by text query across title, data, type_hint, and related Things."""
    if not q.strip():
        return []

    pattern = f"%{q}%"
    with db() as conn:
        # Build a WHERE filter applied to all branches of the UNION
        filters = ""
        filter_params: list[str | int] = []
        uf_sql, uf_params = user_filter(user_id, "t")
        filters += uf_sql
        filter_params.extend(uf_params)
        if active_only:
            filters += " AND t.active = 1"
        if type_hint:
            filters += " AND t.type_hint = ?"
            filter_params.append(type_hint)

        # Direct matches on title, data, or type_hint
        direct_params: list[str | int] = [pattern, pattern, pattern, *filter_params]
        direct_sql = (
            "SELECT t.*, 1 AS _rank FROM things t"
            " WHERE (t.title LIKE ? OR t.data LIKE ? OR t.type_hint LIKE ?)" + filters
        )

        # Things connected via relationships to directly matching Things,
        # or connected by a relationship whose type matches the query
        rel_sql = (
            "SELECT t.*, 2 AS _rank FROM things t"
            " WHERE t.id IN ("
            "   SELECT r.to_thing_id FROM thing_relationships r"
            "   JOIN things m ON r.from_thing_id = m.id"
            "   WHERE m.title LIKE ? OR m.data LIKE ?"
            "   UNION"
            "   SELECT r.from_thing_id FROM thing_relationships r"
            "   JOIN things m ON r.to_thing_id = m.id"
            "   WHERE m.title LIKE ? OR m.data LIKE ?"
            "   UNION"
            "   SELECT r.from_thing_id FROM thing_relationships r"
            "   WHERE r.relationship_type LIKE ?"
            "   UNION"
            "   SELECT r.to_thing_id FROM thing_relationships r"
            "   WHERE r.relationship_type LIKE ?"
            " )" + filters
        )
        rel_params: list[str | int] = [pattern, pattern, pattern, pattern, pattern, pattern, *filter_params]

        # Combine with deduplication: direct matches first, then related
        sql = (
            "SELECT * FROM ("
            f"  {direct_sql}"
            f"  UNION ALL"
            f"  {rel_sql}"
            ") sub"
            " GROUP BY sub.id"
            " ORDER BY MIN(sub._rank), sub.updated_at DESC"
            " LIMIT ?"
        )
        params = [*direct_params, *rel_params, limit]
        rows = conn.execute(sql, params).fetchall()

    return [_row_to_thing(r) for r in rows]


@router.get("", response_model=list[Thing], summary="List Things")
def list_things(
    active_only: bool = Query(True, description="Filter to active Things only"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    user_id: str = Depends(require_user),
) -> list[Thing]:
    """List all Things with optional filtering and pagination. Projects include child counts."""
    with db() as conn:
        where = "WHERE 1=1"
        params: list[str | int] = []
        uf_sql, uf_params = user_filter(user_id)
        where += uf_sql
        params.extend(uf_params)
        if active_only:
            where += " AND active = 1"
        params.extend([limit, offset])
        rows = conn.execute(
            f"SELECT * FROM things {where} ORDER BY checkin_date ASC, priority ASC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        things = [_row_to_thing(r) for r in rows]

        # Compute child stats for project-type things
        project_ids = [t.id for t in things if t.type_hint == "project"]
        if project_ids:
            placeholders = ",".join("?" * len(project_ids))
            child_rows = conn.execute(
                f"SELECT parent_id,"
                f" COUNT(*) as children_count,"
                f" SUM(CASE WHEN active = 0 THEN 1 ELSE 0 END) as completed_count"
                f" FROM things WHERE parent_id IN ({placeholders})"
                f" GROUP BY parent_id",
                project_ids,
            ).fetchall()
            stats = {r["parent_id"]: (r["children_count"], r["completed_count"]) for r in child_rows}
            for t in things:
                if t.type_hint == "project":
                    counts = stats.get(t.id, (0, 0))
                    t.children_count = counts[0]
                    t.completed_count = counts[1]

    return things


@router.get("/graph", response_model=GraphResponse, summary="Get Things as a graph of nodes and edges")
def get_graph(user_id: str = Depends(require_user)) -> GraphResponse:
    """Return all active Things and relationships as nodes and edges, avoiding N+1 queries."""
    with db() as conn:
        uf_sql, uf_params = user_filter(user_id, "t")
        node_rows = conn.execute(
            "SELECT t.id, t.title, t.type_hint, tt.icon"
            " FROM things t"
            " LEFT JOIN thing_types tt ON t.type_hint = tt.name"
            " WHERE t.active = 1" + uf_sql,
            uf_params,
        ).fetchall()
        edge_rows = conn.execute(
            "SELECT r.id, r.from_thing_id, r.to_thing_id, r.relationship_type"
            " FROM thing_relationships r"
            " JOIN things t ON r.from_thing_id = t.id"
            " WHERE t.active = 1" + uf_sql,
            uf_params,
        ).fetchall()

    nodes = [GraphNode(id=r["id"], title=r["title"], type_hint=r["type_hint"], icon=r["icon"]) for r in node_rows]
    active_ids = {n.id for n in nodes}
    edges = [
        GraphEdge(
            id=r["id"], source=r["from_thing_id"], target=r["to_thing_id"], relationship_type=r["relationship_type"]
        )
        for r in edge_rows
        if r["to_thing_id"] in active_ids
    ]
    return GraphResponse(nodes=nodes, edges=edges)


@router.post("", response_model=Thing, status_code=status.HTTP_201_CREATED, summary="Create a Thing")
def create_thing(body: ThingCreate, background_tasks: BackgroundTasks, user_id: str = Depends(require_user)) -> Thing:
    """Create a new Thing and index it for vector search."""
    thing_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    data_json = json.dumps(body.data) if body.data is not None else None
    checkin = body.checkin_date.isoformat() if body.checkin_date else None
    oq_json = json.dumps(body.open_questions) if body.open_questions is not None else None

    if body.parent_id:
        with db() as conn:
            parent = conn.execute("SELECT id FROM things WHERE id = ?", (body.parent_id,)).fetchone()
        if not parent:
            raise HTTPException(status_code=404, detail=f"Parent thing '{body.parent_id}' not found")

    with db() as conn:
        conn.execute(
            "INSERT INTO things"
            " (id, title, type_hint, parent_id, checkin_date, priority, active, surface, data,"
            " open_questions, created_at, updated_at, user_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                thing_id,
                body.title,
                body.type_hint,
                body.parent_id,
                checkin,
                body.priority,
                int(body.active),
                int(body.surface),
                data_json,
                oq_json,
                now,
                now,
                user_id or None,
            ),
        )
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
    background_tasks.add_task(upsert_thing, dict(row))
    return _row_to_thing(row)


# ── Merge history ────────────────────────────────────────────────────────────


@router.get(
    "/merge-history",
    response_model=list[MergeHistoryRecord],
    summary="List merge history",
)
def list_merge_history(
    thing_id: str | None = Query(None, description="Filter by kept Thing ID"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of results"),
    user_id: str = Depends(require_user),
) -> list[MergeHistoryRecord]:
    """Return merge history records, newest first. Optionally filter by the kept Thing."""
    uf_sql, uf_params = user_filter(user_id, "mh")
    where = "WHERE 1=1" + uf_sql
    params: list[str | int] = list(uf_params)
    if thing_id:
        where += " AND mh.keep_id = ?"
        params.append(thing_id)
    params.append(limit)
    with db() as conn:
        rows = conn.execute(
            f"SELECT mh.* FROM merge_history mh {where} ORDER BY mh.created_at DESC LIMIT ?",
            params,
        ).fetchall()
    results = []
    for r in rows:
        md = r["merged_data"]
        if isinstance(md, str) and md:
            try:
                md = json.loads(md)
            except (json.JSONDecodeError, ValueError):
                md = None
        results.append(
            MergeHistoryRecord(
                id=r["id"],
                keep_id=r["keep_id"],
                remove_id=r["remove_id"],
                keep_title=r["keep_title"],
                remove_title=r["remove_title"],
                merged_data=md,
                triggered_by=r["triggered_by"],
                user_id=r["user_id"],
                created_at=_parse_dt(r["created_at"]) or datetime.min,
            )
        )
    return results


@router.get("/{thing_id}", response_model=Thing, summary="Get a Thing")
def get_thing(thing_id: str, user_id: str = Depends(require_user)) -> Thing:
    """Retrieve a single Thing by ID."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        row = conn.execute(f"SELECT * FROM things WHERE id = ?{uf_sql}", [thing_id, *uf_params]).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Thing '{thing_id}' not found")
    return _row_to_thing(row)


@router.patch("/{thing_id}", response_model=Thing, summary="Update a Thing")
def update_thing(
    thing_id: str, body: ThingUpdate, background_tasks: BackgroundTasks, user_id: str = Depends(require_user)
) -> Thing:
    """Partially update a Thing. Only provided fields are changed."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        row = conn.execute(f"SELECT * FROM things WHERE id = ?{uf_sql}", [thing_id, *uf_params]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Thing '{thing_id}' not found")

        if body.parent_id is not None:
            if body.parent_id == thing_id:
                raise HTTPException(status_code=422, detail="A Thing cannot be its own parent")
            parent = conn.execute("SELECT id FROM things WHERE id = ?", (body.parent_id,)).fetchone()
            if not parent:
                raise HTTPException(status_code=404, detail=f"Parent thing '{body.parent_id}' not found")

        fields: dict[str, Any] = {}
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
        if body.open_questions is not None:
            fields["open_questions"] = json.dumps(body.open_questions)
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [thing_id]
        conn.execute(f"UPDATE things SET {set_clause} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
    background_tasks.add_task(upsert_thing, dict(row))
    return _row_to_thing(row)


@router.delete("/{thing_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a Thing")
def delete_thing(thing_id: str, background_tasks: BackgroundTasks, user_id: str = Depends(require_user)) -> None:
    """Delete a Thing and remove it from the vector index."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        row = conn.execute(f"SELECT id FROM things WHERE id = ?{uf_sql}", [thing_id, *uf_params]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Thing '{thing_id}' not found")
        conn.execute(f"DELETE FROM things WHERE id = ?{uf_sql}", [thing_id, *uf_params])
    background_tasks.add_task(vs_delete, thing_id)


@router.post("/reindex", summary="Re-embed all Things with the current embedding model")
def reindex_things(user_id: str = Depends(require_user)) -> dict[str, int]:
    """Rebuild the vector search index for all Things. Returns the count of re-indexed items."""
    count = reindex_all()
    return {"reindexed": count}


class PreferenceFeedback(BaseModel):
    positive: bool


@router.patch("/{thing_id}/preference-feedback", response_model=Thing, summary="Update preference confidence via feedback")
def preference_feedback(
    thing_id: str,
    body: PreferenceFeedback,
    user_id: str = Depends(require_user),
) -> Thing:
    """Adjust a preference Thing's confidence up (positive) or down (negative)."""
    uf_sql, uf_params = user_filter(user_id)
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        row = conn.execute(
            f"SELECT * FROM things WHERE id = ? AND type_hint = 'preference'{uf_sql}",
            [thing_id, *uf_params],
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Preference Thing '{thing_id}' not found")

        thing = _row_to_thing(row)
        data = dict(thing.data) if thing.data else {}
        current = float(data.get("confidence", 0.5))
        if body.positive:
            data["confidence"] = min(1.0, current + 0.15)
        else:
            data["confidence"] = max(0.0, current - 0.3)

        # Track feedback in evidence
        evidence = list(data.get("evidence", []))
        if isinstance(evidence, list):
            evidence.append({"feedback": "positive" if body.positive else "negative", "at": now})
        data["evidence"] = evidence
        data["updated_at"] = now

        conn.execute(
            "UPDATE things SET data = ?, updated_at = ? WHERE id = ?",
            (json.dumps(data), now, thing_id),
        )
        updated_row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
    return _row_to_thing(updated_row)


# ── Merge suggestions & execution ───────────────────────────────────────────


def _normalize(title: str) -> str:
    """Lowercase, strip articles and possessives for comparison."""
    t = title.lower().strip()
    for prefix in ("my ", "the ", "a ", "an "):
        if t.startswith(prefix):
            t = t[len(prefix) :]
    return t


def _titles_similar(a: str, b: str) -> str | None:
    """Return a reason string if two titles look like duplicates, else None."""
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return None
    # Exact match after normalization
    if na == nb:
        return f'Same name: "{a}" and "{b}"'
    # One is a prefix/substring of the other (for short names)
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) >= 3 and shorter in longer:
        return f'Similar names: "{a}" and "{b}"'
    return None


@router.get(
    "/merge-suggestions",
    response_model=list[MergeSuggestion],
    summary="Detect potential duplicate Things",
)
def get_merge_suggestions(
    limit: int = Query(10, ge=1, le=50, description="Maximum suggestions to return"),
    user_id: str = Depends(require_user),
) -> list[MergeSuggestion]:
    """Find pairs of active Things with similar titles that may be duplicates."""
    with db() as conn:
        uf_sql, uf_params = user_filter(user_id)
        rows = conn.execute(
            "SELECT id, title, type_hint FROM things WHERE active = 1" + uf_sql + " ORDER BY title",
            uf_params,
        ).fetchall()

    # Also check shared relationships between pairs
    suggestions: list[MergeSuggestion] = []
    seen_pairs: set[tuple[str, str]] = set()

    things_list = [(r["id"], r["title"], r["type_hint"]) for r in rows]

    for i, (id_a, title_a, type_a) in enumerate(things_list):
        for j in range(i + 1, len(things_list)):
            id_b, title_b, type_b = things_list[j]
            reason = _titles_similar(title_a, title_b)
            if reason is None:
                continue
            pair = (min(id_a, id_b), max(id_a, id_b))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            # Boost reason if same type
            if type_a and type_a == type_b:
                reason += f" (both {type_a})"
            suggestions.append(
                MergeSuggestion(
                    thing_a=MergeSuggestionThing(id=id_a, title=title_a, type_hint=type_a),
                    thing_b=MergeSuggestionThing(id=id_b, title=title_b, type_hint=type_b),
                    reason=reason,
                )
            )
            if len(suggestions) >= limit:
                break
        if len(suggestions) >= limit:
            break

    return suggestions


@router.post(
    "/merge",
    response_model=MergeResult,
    summary="Merge two Things",
)
def merge_things(
    body: MergeRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(require_user),
) -> MergeResult:
    """Merge remove_id into keep_id: transfer relationships, merge data, delete duplicate."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        keep_row = conn.execute(f"SELECT * FROM things WHERE id = ?{uf_sql}", [body.keep_id, *uf_params]).fetchone()
        remove_row = conn.execute(f"SELECT * FROM things WHERE id = ?{uf_sql}", [body.remove_id, *uf_params]).fetchone()
        if not keep_row:
            raise HTTPException(status_code=404, detail=f"Thing '{body.keep_id}' not found")
        if not remove_row:
            raise HTTPException(status_code=404, detail=f"Thing '{body.remove_id}' not found")
        if body.keep_id == body.remove_id:
            raise HTTPException(status_code=422, detail="Cannot merge a Thing with itself")

        now = datetime.now(timezone.utc).isoformat()

        # 1. Merge data dicts
        existing_data = keep_row["data"]
        try:
            old_data = json.loads(existing_data) if isinstance(existing_data, str) and existing_data else {}
        except (json.JSONDecodeError, ValueError):
            old_data = {}
        remove_data_raw = remove_row["data"]
        try:
            remove_data = json.loads(remove_data_raw) if isinstance(remove_data_raw, str) and remove_data_raw else {}
        except (json.JSONDecodeError, ValueError):
            remove_data = {}
        if remove_data:
            combined = {**remove_data, **old_data}  # keep_row data takes priority
            conn.execute(
                "UPDATE things SET data = ?, updated_at = ? WHERE id = ?",
                (json.dumps(combined), now, body.keep_id),
            )

        # 2. Transfer open_questions
        keep_oq_raw = keep_row["open_questions"]
        remove_oq_raw = remove_row["open_questions"]
        try:
            keep_oq = json.loads(keep_oq_raw) if isinstance(keep_oq_raw, str) and keep_oq_raw else []
        except (json.JSONDecodeError, ValueError):
            keep_oq = []
        try:
            remove_oq = json.loads(remove_oq_raw) if isinstance(remove_oq_raw, str) and remove_oq_raw else []
        except (json.JSONDecodeError, ValueError):
            remove_oq = []
        if remove_oq:
            existing_set = set(keep_oq)
            for q in remove_oq:
                if q not in existing_set:
                    keep_oq.append(q)
                    existing_set.add(q)
            conn.execute(
                "UPDATE things SET open_questions = ?, updated_at = ? WHERE id = ?",
                (json.dumps(keep_oq), now, body.keep_id),
            )

        # 3. Re-point relationships
        conn.execute(
            "UPDATE thing_relationships SET from_thing_id = ? WHERE from_thing_id = ?",
            (body.keep_id, body.remove_id),
        )
        conn.execute(
            "UPDATE thing_relationships SET to_thing_id = ? WHERE to_thing_id = ?",
            (body.keep_id, body.remove_id),
        )
        # Clean up self-referential relationships
        conn.execute(
            "DELETE FROM thing_relationships WHERE from_thing_id = ? AND to_thing_id = ?",
            (body.keep_id, body.keep_id),
        )

        # 4. Re-parent children of the removed thing
        conn.execute(
            "UPDATE things SET parent_id = ? WHERE parent_id = ?",
            (body.keep_id, body.remove_id),
        )

        # 5. Delete the duplicate
        conn.execute("DELETE FROM things WHERE id = ?", (body.remove_id,))

        keep_title = keep_row["title"]
        remove_title = remove_row["title"]

        # 6. Record merge history
        existing_data_raw = keep_row["data"]
        try:
            keep_data = (
                json.loads(existing_data_raw) if isinstance(existing_data_raw, str) and existing_data_raw else {}
            )
        except (json.JSONDecodeError, ValueError):
            keep_data = {}
        remove_data_raw = remove_row["data"]
        try:
            rem_data = json.loads(remove_data_raw) if isinstance(remove_data_raw, str) and remove_data_raw else {}
        except (json.JSONDecodeError, ValueError):
            rem_data = {}
        merged_snapshot = {**rem_data, **keep_data}
        conn.execute(
            "INSERT INTO merge_history (id, keep_id, remove_id, keep_title, remove_title,"
            " merged_data, triggered_by, user_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                body.keep_id,
                body.remove_id,
                keep_title,
                remove_title,
                json.dumps(merged_snapshot) if merged_snapshot else None,
                "api",
                user_id or None,
                now,
            ),
        )

        # 7. Re-embed the kept thing
        updated = conn.execute("SELECT * FROM things WHERE id = ?", (body.keep_id,)).fetchone()

    background_tasks.add_task(vs_delete, body.remove_id)
    if updated:
        background_tasks.add_task(upsert_thing, dict(updated))

    return MergeResult(
        keep_id=body.keep_id,
        remove_id=body.remove_id,
        keep_title=keep_title,
        remove_title=remove_title,
    )


# ── Orphan relationship management ──────────────────────────────────────────


@router.get(
    "/relationships/orphans",
    response_model=list[Relationship],
    summary="Find orphan relationships",
)
def get_orphan_relationships(user_id: str = Depends(require_user)) -> list[Relationship]:
    """Return relationships where from_thing_id or to_thing_id doesn't exist in the things table."""
    with db() as conn:
        rows = conn.execute(
            "SELECT r.* FROM thing_relationships r"
            " WHERE r.from_thing_id NOT IN (SELECT id FROM things)"
            "    OR r.to_thing_id NOT IN (SELECT id FROM things)"
        ).fetchall()
    return [_parse_rel_row(r) for r in rows]


@router.post(
    "/relationships/cleanup",
    response_model=OrphanCleanupResult,
    summary="Delete orphan relationships",
)
def cleanup_orphan_relationships(user_id: str = Depends(require_user)) -> OrphanCleanupResult:
    """Delete all relationships where from_thing_id or to_thing_id doesn't exist."""
    deleted_count, deleted_ids = clean_orphan_relationships()
    return OrphanCleanupResult(deleted_count=deleted_count, deleted_ids=deleted_ids)


# ── Relationships ────────────────────────────────────────────────────────────


def _parse_rel_row(row: sqlite3.Row) -> Relationship:
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
        created_at=_parse_dt(row["created_at"]) or datetime.min,
    )


@router.get("/{thing_id}/relationships", response_model=list[Relationship], summary="List relationships for a Thing")
def list_relationships(thing_id: str, user_id: str = Depends(require_user)) -> list[Relationship]:
    """List all relationships where the given Thing is either the source or target."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        row = conn.execute(f"SELECT id FROM things WHERE id = ?{uf_sql}", [thing_id, *uf_params]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Thing '{thing_id}' not found")
        rows = conn.execute(
            "SELECT * FROM thing_relationships WHERE from_thing_id = ? OR to_thing_id = ?",
            (thing_id, thing_id),
        ).fetchall()
    return [_parse_rel_row(r) for r in rows]


@router.post(
    "/relationships", response_model=Relationship, status_code=status.HTTP_201_CREATED, summary="Create a relationship"
)
def create_relationship(body: RelationshipCreate, user_id: str = Depends(require_user)) -> Relationship:
    """Create a typed relationship between two Things."""
    rel_id = str(uuid.uuid4())
    meta_json = json.dumps(body.metadata) if body.metadata is not None else None
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        # Validate both things exist and belong to this user
        for tid, label in [(body.from_thing_id, "from"), (body.to_thing_id, "to")]:
            if not conn.execute(f"SELECT id FROM things WHERE id = ?{uf_sql}", [tid, *uf_params]).fetchone():
                raise HTTPException(status_code=404, detail=f"{label}_thing_id '{tid}' not found")
        if body.from_thing_id == body.to_thing_id:
            raise HTTPException(status_code=422, detail="A Thing cannot have a relationship with itself")
        conn.execute(
            "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type, metadata)"
            " VALUES (?, ?, ?, ?, ?)",
            (rel_id, body.from_thing_id, body.to_thing_id, body.relationship_type, meta_json),
        )
        row = conn.execute("SELECT * FROM thing_relationships WHERE id = ?", (rel_id,)).fetchone()
    return _parse_rel_row(row)


@router.delete("/relationships/{rel_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a relationship")
def delete_relationship(rel_id: str) -> None:
    """Delete a relationship by ID."""
    with db() as conn:
        row = conn.execute("SELECT id FROM thing_relationships WHERE id = ?", (rel_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Relationship '{rel_id}' not found")
        conn.execute("DELETE FROM thing_relationships WHERE id = ?", (rel_id,))
