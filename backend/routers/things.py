"""CRUD endpoints for Things."""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlmodel import Session, or_, select

import backend.db_engine as _engine_mod

from ..auth import require_user
from ..db_engine import get_session, user_filter_clause, user_filter_text
from ..db_models import MergeHistoryRecord as MergeHistoryDBRecord
from ..db_models import ThingRecord, ThingRelationshipRecord
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
_logger = logging.getLogger(__name__)


def _parse_dt(val: str | None) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    return datetime.fromisoformat(val)


def _record_to_thing(record: ThingRecord) -> Thing:
    """Convert a ThingRecord (SQLModel) to a Thing (Pydantic response model)."""
    # Handle data: SQLAlchemy JSON type auto-deserializes, but may have edge cases
    data = record.data
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            data = None

    open_questions = record.open_questions
    if isinstance(open_questions, str):
        try:
            oq = json.loads(open_questions)
            open_questions = oq if isinstance(oq, list) else None
        except (json.JSONDecodeError, ValueError):
            open_questions = None

    return Thing(
        id=record.id,
        title=record.title,
        type_hint=record.type_hint,
        checkin_date=record.checkin_date,
        importance=record.importance,
        active=bool(record.active),
        surface=bool(record.surface) if record.surface is not None else True,
        data=data if isinstance(data, dict) else None,
        created_at=record.created_at or datetime.min,
        updated_at=record.updated_at or datetime.min,
        last_referenced=record.last_referenced,
        open_questions=open_questions if isinstance(open_questions, list) else None,
    )


# Keep _row_to_thing for backward compat (imported by other modules)
def _row_to_thing(row: Any) -> Thing:
    """Convert a sqlite3.Row to a Thing response model. Legacy compat wrapper."""
    if isinstance(row, ThingRecord):
        return _record_to_thing(row)
    # Legacy sqlite3.Row handling
    data = row.data
    while isinstance(data, str) and data:
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            break
    if isinstance(data, str):
        data = None
    surface = True
    try:
        surface = bool(row.surface) if row.surface is not None else True
    except (IndexError, KeyError):
        pass
    last_referenced = None
    try:
        last_referenced = _parse_dt(row.last_referenced)
    except (IndexError, KeyError):
        pass
    open_questions = None
    try:
        raw_oq = row.open_questions
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
        id=row.id,
        title=row.title,
        type_hint=row.type_hint,
        checkin_date=_parse_dt(row.checkin_date),
        importance=row.importance,
        active=bool(row.active),
        surface=surface,
        data=data,
        created_at=_parse_dt(row.created_at) or datetime.min,
        updated_at=_parse_dt(row.updated_at) or datetime.min,
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
    direction: str
    related_thing_id: str
    related_thing_title: str


class UserProfileDetail(BaseModel):
    """The user's anchor Thing with resolved relationships."""
    thing: Thing
    relationships: list[UserProfileRelationship]


@router.get("/me", response_model=UserProfileDetail, summary="Get the current user's profile Thing")
def get_user_thing(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> UserProfileDetail:
    """Return the user's anchor Thing (created at sign-up) with resolved relationships."""
    stmt = select(ThingRecord).where(
        ThingRecord.surface == False,
        ThingRecord.type_hint == "person",
        user_filter_clause(ThingRecord.user_id, user_id),
    )
    record = session.exec(stmt).first()
    if not record:
        raise HTTPException(status_code=404, detail="User profile Thing not found")

    thing = _record_to_thing(record)
    thing_id = thing.id

    # Fetch relationships with resolved titles using raw SQL for the complex JOIN
    rel_rows = session.execute(
        text(
            "SELECT r.id, r.relationship_type, r.from_thing_id, r.to_thing_id, "
            "  CASE WHEN r.from_thing_id = :tid THEN t_to.title ELSE t_from.title END AS related_title, "
            "  CASE WHEN r.from_thing_id = :tid THEN t_to.id ELSE t_from.id END AS related_id, "
            "  CASE WHEN r.from_thing_id = :tid THEN 'outgoing' ELSE 'incoming' END AS direction "
            " FROM thing_relationships r "
            " LEFT JOIN things t_from ON r.from_thing_id = t_from.id "
            " LEFT JOIN things t_to ON r.to_thing_id = t_to.id "
            " WHERE r.from_thing_id = :tid OR r.to_thing_id = :tid"
        ),
        {"tid": thing_id},
    ).fetchall()

    relationships = [
        UserProfileRelationship(
            id=r.id,
            relationship_type=r.relationship_type,
            direction=r.direction,
            related_thing_id=r.related_id or "",
            related_thing_title=r.related_title or "Unknown",
        )
        for r in rel_rows
    ]

    return UserProfileDetail(thing=thing, relationships=relationships)


@router.get("/open-questions", response_model=list[Thing], summary="List Things with open questions")
def get_open_questions(
    limit: int = Query(50, ge=1, le=200, description="Maximum number of results"),
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> list[Thing]:
    """Return active Things that have non-empty open_questions arrays."""
    stmt = select(ThingRecord).where(
        ThingRecord.active == True,
        ThingRecord.open_questions.is_not(None),  # type: ignore[union-attr]
        user_filter_clause(ThingRecord.user_id, user_id),
    ).order_by(
        ThingRecord.importance.asc(),  # type: ignore[attr-defined]
        ThingRecord.updated_at.desc(),  # type: ignore[attr-defined]
    ).limit(limit)
    records = session.exec(stmt).all()
    return [_record_to_thing(r) for r in records if r.open_questions]


@router.get("/search", response_model=list[Thing], summary="Search Things across the full graph")
def search_things(
    q: str = Query("", description="Free-text search query"),
    active_only: bool = Query(False, description="Filter to active Things only"),
    type_hint: str | None = Query(None, description="Filter by type_hint"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of results"),
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> list[Thing]:
    """Search Things by text query across title, data, type_hint, and related Things.

    Uses a two-phase approach: first searches direct matches on title/type_hint/data,
    then searches relationship-connected Things. This avoids a single expensive UNION
    query that can time out on larger datasets.
    """
    if not q.strip():
        return []

    pattern = f"%{q}%"
    uf_frag, uf_p = user_filter_text(user_id, "t")
    filters = uf_frag
    params: dict[str, Any] = {**uf_p, "pattern": pattern, "qlimit": limit}
    if active_only:
        filters += " AND t.active = true"
    if type_hint:
        filters += " AND t.type_hint = :type_hint"
        params["type_hint"] = type_hint

    with Session(_engine_mod.engine) as sess:
        # Phase 1: Direct matches on title, type_hint, and data
        direct_sql = text(
            "SELECT t.* FROM things t"
            " WHERE (t.title LIKE :pattern OR t.type_hint LIKE :pattern"
            "        OR CAST(t.data AS TEXT) LIKE :pattern)"
            + filters +
            " ORDER BY t.updated_at DESC"
            " LIMIT :qlimit"
        )
        direct_rows = sess.execute(direct_sql, params).fetchall()
        seen_ids = {r.id for r in direct_rows}
        results = [(r, 1) for r in direct_rows]

        # Phase 2: Relationship-connected matches (only if we need more results)
        remaining = limit - len(results)
        if remaining > 0:
            rel_params = {**params, "qlimit": remaining}
            # Find Things connected via relationships where the *other* Thing or
            # the relationship_type matches the query.  Split into two directed
            # EXISTS clauses so SQLite can use idx_rel_from / idx_rel_to instead
            # of scanning with an OR + CASE expression (fixes #319 timeout).
            rel_sql = text(
                "SELECT t.* FROM things t"
                " WHERE ("
                "   EXISTS ("
                "     SELECT 1 FROM thing_relationships r"
                "     JOIN things m ON m.id = r.to_thing_id"
                "     WHERE r.from_thing_id = t.id"
                "       AND (r.relationship_type LIKE :pattern"
                "            OR m.title LIKE :pattern"
                "            OR CAST(m.data AS TEXT) LIKE :pattern)"
                "   )"
                "   OR EXISTS ("
                "     SELECT 1 FROM thing_relationships r"
                "     JOIN things m ON m.id = r.from_thing_id"
                "     WHERE r.to_thing_id = t.id"
                "       AND (r.relationship_type LIKE :pattern"
                "            OR m.title LIKE :pattern"
                "            OR CAST(m.data AS TEXT) LIKE :pattern)"
                "   )"
                " )"
                + filters +
                " ORDER BY t.updated_at DESC"
                " LIMIT :qlimit"
            )
            rel_rows = sess.execute(rel_sql, rel_params).fetchall()
            for r in rel_rows:
                if r.id not in seen_ids:
                    seen_ids.add(r.id)
                    results.append((r, 2))

    # Sort: rank ascending (direct matches first), newest first within each rank
    results.sort(key=lambda x: x[0].updated_at, reverse=True)
    results.sort(key=lambda x: x[1])

    return [_row_to_thing(r) for r, _rank in results[:limit]]


@router.get("", response_model=list[Thing], summary="List Things")
def list_things(
    active_only: bool = Query(True, description="Filter to active Things only"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> list[Thing]:
    """List all Things with optional filtering and pagination."""
    stmt = select(ThingRecord).where(
        user_filter_clause(ThingRecord.user_id, user_id),
    )
    if active_only:
        stmt = stmt.where(ThingRecord.active == True)
    stmt = stmt.order_by(
        ThingRecord.checkin_date.asc(),  # type: ignore[union-attr, attr-defined]
        ThingRecord.importance.asc(),  # type: ignore[attr-defined]
    ).limit(limit).offset(offset)
    records = session.exec(stmt).all()
    things = [_record_to_thing(r) for r in records]

    # Compute child stats and parent_ids from parent-of relationships
    thing_ids = [t.id for t in things]
    if thing_ids:
        from collections import defaultdict

        from sqlalchemy import case as sa_case

        # Fetch all parent-of relationships involving these Things
        parent_of_rels = session.exec(
            select(
                ThingRelationshipRecord.from_thing_id,
                ThingRelationshipRecord.to_thing_id,
            ).where(
                ThingRelationshipRecord.relationship_type == "parent-of",
                or_(
                    ThingRelationshipRecord.from_thing_id.in_(thing_ids),  # type: ignore[union-attr]
                    ThingRelationshipRecord.to_thing_id.in_(thing_ids),  # type: ignore[union-attr]
                ),
            )
        ).all()

        # Build parent_ids map (child_id -> list of parent_ids)
        parent_map: dict[str, list[str]] = defaultdict(list)
        for from_id, to_id in parent_of_rels:
            parent_map[to_id].append(from_id)

        for t in things:
            if t.id in parent_map:
                t.parent_ids = parent_map[t.id]

        # Compute child stats for project-type things
        project_ids = [t.id for t in things if t.type_hint == "project"]
        if project_ids:
            child_stmt = (
                select(
                    ThingRelationshipRecord.from_thing_id.label("project_id"),
                    func.count().label("children_count"),
                    func.sum(sa_case((ThingRecord.active == False, 1), else_=0)).label("completed_count"),
                )
                .join(ThingRecord, ThingRecord.id == ThingRelationshipRecord.to_thing_id)
                .where(
                    ThingRelationshipRecord.from_thing_id.in_(project_ids),  # type: ignore[union-attr]
                    ThingRelationshipRecord.relationship_type == "parent-of",
                )
                .group_by(ThingRelationshipRecord.from_thing_id)
            )
            child_rows = session.execute(child_stmt).fetchall()
            stats = {r.project_id: (r.children_count, r.completed_count or 0) for r in child_rows}
            for t in things:
                if t.type_hint == "project":
                    counts = stats.get(t.id, (0, 0))
                    t.children_count = counts[0]
                    t.completed_count = counts[1]

    return things


@router.get("/graph", response_model=GraphResponse, summary="Get Things as a graph")
def get_graph(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> GraphResponse:
    """Return all active Things and relationships as nodes and edges."""
    # Complex JOIN with thing_types -- use text() for the LEFT JOIN
    uf_frag, uf_p = user_filter_text(user_id, "t")
    with Session(_engine_mod.engine) as session:
        node_rows = session.execute(
            text(
                "SELECT t.id, t.title, t.type_hint, tt.icon"
                " FROM things t"
                " LEFT JOIN thing_types tt ON t.type_hint = tt.name"
                " WHERE t.active = true" + uf_frag
            ),
            uf_p,
        ).fetchall()
        edge_rows = session.execute(
            text(
                "SELECT r.id, r.from_thing_id, r.to_thing_id, r.relationship_type"
                " FROM thing_relationships r"
                " JOIN things t ON r.from_thing_id = t.id"
                " WHERE t.active = true" + uf_frag
            ),
            uf_p,
        ).fetchall()

    nodes = [GraphNode(id=r.id, title=r.title, type_hint=r.type_hint, icon=r.icon) for r in node_rows]
    active_ids = {n.id for n in nodes}
    edges = [
        GraphEdge(
            id=r.id, source=r.from_thing_id, target=r.to_thing_id, relationship_type=r.relationship_type
        )
        for r in edge_rows
        if r.to_thing_id in active_ids
    ]
    return GraphResponse(nodes=nodes, edges=edges)


@router.post("", response_model=Thing, status_code=status.HTTP_201_CREATED, summary="Create a Thing")
def create_thing(
    body: ThingCreate,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Thing:
    """Create a new Thing and index it for vector search."""
    now = datetime.now(timezone.utc)

    record = ThingRecord(
        title=body.title,
        type_hint=body.type_hint,
        checkin_date=body.checkin_date,
        importance=body.importance,
        active=body.active,
        surface=body.surface,
        data=body.data,
        open_questions=body.open_questions,
        created_at=now,
        updated_at=now,
        user_id=user_id or None,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    background_tasks.add_task(upsert_thing, record.model_dump())
    return _record_to_thing(record)


# -- Merge history --

@router.get(
    "/merge-history",
    response_model=list[MergeHistoryRecord],
    summary="List merge history",
)
def list_merge_history(
    thing_id: str | None = Query(None, description="Filter by kept Thing ID"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of results"),
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> list[MergeHistoryRecord]:
    """Return merge history records, newest first."""
    stmt = select(MergeHistoryDBRecord).where(
        user_filter_clause(MergeHistoryDBRecord.user_id, user_id),
    )
    if thing_id:
        stmt = stmt.where(MergeHistoryDBRecord.keep_id == thing_id)
    stmt = stmt.order_by(MergeHistoryDBRecord.created_at.desc()).limit(limit)  # type: ignore[union-attr, attr-defined]
    records = session.exec(stmt).all()
    return [
        MergeHistoryRecord(
            id=r.id,
            keep_id=r.keep_id,
            remove_id=r.remove_id,
            keep_title=r.keep_title,
            remove_title=r.remove_title,
            merged_data=r.merged_data,
            triggered_by=r.triggered_by,
            user_id=r.user_id,
            created_at=r.created_at or datetime.min,
        )
        for r in records
    ]


@router.get("/{thing_id}", response_model=Thing, summary="Get a Thing")
def get_thing(
    thing_id: str,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Thing:
    """Retrieve a single Thing by ID."""
    stmt = select(ThingRecord).where(
        ThingRecord.id == thing_id,
        user_filter_clause(ThingRecord.user_id, user_id),
    )
    record = session.exec(stmt).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Thing '{thing_id}' not found")
    return _record_to_thing(record)


@router.patch("/{thing_id}", response_model=Thing, summary="Update a Thing")
def update_thing(
    thing_id: str,
    body: ThingUpdate,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Thing:
    """Partially update a Thing. Only provided fields are changed."""
    stmt = select(ThingRecord).where(
        ThingRecord.id == thing_id,
        user_filter_clause(ThingRecord.user_id, user_id),
    )
    record = session.exec(stmt).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Thing '{thing_id}' not found")

    if body.title is not None:
        record.title = body.title
    if body.type_hint is not None:
        record.type_hint = body.type_hint
    if body.checkin_date is not None:
        record.checkin_date = body.checkin_date
    if body.importance is not None:
        record.importance = body.importance
    if body.active is not None:
        record.active = body.active
    if body.surface is not None:
        record.surface = body.surface
    if body.data is not None:
        record.data = body.data
    if body.open_questions is not None:
        record.open_questions = body.open_questions
    record.updated_at = datetime.now(timezone.utc)

    session.add(record)
    session.commit()
    session.refresh(record)
    background_tasks.add_task(upsert_thing, record.model_dump())
    return _record_to_thing(record)


@router.delete("/{thing_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a Thing")
def delete_thing(
    thing_id: str,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> None:
    """Delete a Thing and remove it from the vector index."""
    stmt = select(ThingRecord).where(
        ThingRecord.id == thing_id,
        user_filter_clause(ThingRecord.user_id, user_id),
    )
    record = session.exec(stmt).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Thing '{thing_id}' not found")
    session.delete(record)
    session.commit()
    background_tasks.add_task(vs_delete, thing_id)


@router.post("/reindex", summary="Re-embed all Things with the current embedding model")
def reindex_things(user_id: str = Depends(require_user)) -> dict[str, int]:
    """Rebuild the vector search index for all Things."""
    count = reindex_all()
    return {"reindexed": count}


# -- Merge suggestions & execution --

def _normalize(title: str) -> str:
    t = title.lower().strip()
    for prefix in ("my ", "the ", "a ", "an "):
        if t.startswith(prefix):
            return t[len(prefix):]
    return t


def _titles_similar(a: str, b: str) -> str | None:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return None
    if na == nb:
        return f'Same name: "{a}" and "{b}"'
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
    limit: int = Query(10, ge=1, le=50),
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> list[MergeSuggestion]:
    """Find pairs of active Things with similar titles."""
    stmt = select(ThingRecord).where(
        ThingRecord.active == True,
        user_filter_clause(ThingRecord.user_id, user_id),
    ).order_by(ThingRecord.title)
    records = session.exec(stmt).all()

    suggestions: list[MergeSuggestion] = []
    seen_pairs: set[tuple[str, str]] = set()
    things_list = [(r.id, r.title, r.type_hint) for r in records]

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


@router.post("/merge", response_model=MergeResult, summary="Merge two Things")
def merge_things(
    body: MergeRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> MergeResult:
    """Merge remove_id into keep_id."""
    keep_rec = session.exec(
        select(ThingRecord).where(
            ThingRecord.id == body.keep_id,
            user_filter_clause(ThingRecord.user_id, user_id),
        )
    ).first()
    remove_rec = session.exec(
        select(ThingRecord).where(
            ThingRecord.id == body.remove_id,
            user_filter_clause(ThingRecord.user_id, user_id),
        )
    ).first()
    if not keep_rec:
        raise HTTPException(status_code=404, detail=f"Thing '{body.keep_id}' not found")
    if not remove_rec:
        raise HTTPException(status_code=404, detail=f"Thing '{body.remove_id}' not found")
    if body.keep_id == body.remove_id:
        raise HTTPException(status_code=422, detail="Cannot merge a Thing with itself")

    now = datetime.now(timezone.utc)
    keep_title = keep_rec.title
    remove_title = remove_rec.title

    # 1. Merge data dicts
    old_data = keep_rec.data if isinstance(keep_rec.data, dict) else {}
    remove_data = remove_rec.data if isinstance(remove_rec.data, dict) else {}
    if remove_data:
        keep_rec.data = {**remove_data, **old_data}

    # 2. Transfer open_questions
    keep_oq = keep_rec.open_questions if isinstance(keep_rec.open_questions, list) else []
    remove_oq = remove_rec.open_questions if isinstance(remove_rec.open_questions, list) else []
    if remove_oq:
        existing_set = set(keep_oq)
        for q in remove_oq:
            if q not in existing_set:
                keep_oq.append(q)
                existing_set.add(q)
        keep_rec.open_questions = keep_oq

    keep_rec.updated_at = now

    # 3. Re-point relationships
    for rel in session.exec(select(ThingRelationshipRecord).where(ThingRelationshipRecord.from_thing_id == body.remove_id)).all():
        rel.from_thing_id = body.keep_id
    for rel in session.exec(select(ThingRelationshipRecord).where(ThingRelationshipRecord.to_thing_id == body.remove_id)).all():
        rel.to_thing_id = body.keep_id
    for rel in session.exec(select(ThingRelationshipRecord).where(
        ThingRelationshipRecord.from_thing_id == body.keep_id,
        ThingRelationshipRecord.to_thing_id == body.keep_id,
    )).all():
        session.delete(rel)

    # 4. Delete the duplicate
    session.delete(remove_rec)

    # 5. Record merge history
    merged_snapshot = {**remove_data, **(keep_rec.data if isinstance(keep_rec.data, dict) else {})}
    merge_record = MergeHistoryDBRecord(
        id=str(uuid.uuid4()),
        keep_id=body.keep_id,
        remove_id=body.remove_id,
        keep_title=keep_title,
        remove_title=remove_title,
        merged_data=merged_snapshot if merged_snapshot else None,
        triggered_by="api",
        user_id=user_id or None,
        created_at=now,
    )
    session.add(merge_record)
    session.commit()
    session.refresh(keep_rec)

    background_tasks.add_task(vs_delete, body.remove_id)
    background_tasks.add_task(upsert_thing, keep_rec.model_dump())

    return MergeResult(
        keep_id=body.keep_id,
        remove_id=body.remove_id,
        keep_title=keep_title,
        remove_title=remove_title,
    )


# -- Orphan relationship management --

@router.get("/relationships/orphans", response_model=list[Relationship], summary="Find orphan relationships")
def get_orphan_relationships(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> list[Relationship]:
    """Return relationships where from_thing_id or to_thing_id doesn't exist."""
    thing_ids = select(ThingRecord.id).where(
        user_filter_clause(ThingRecord.user_id, user_id)
    )
    stmt = select(ThingRelationshipRecord).where(
        or_(
            ThingRelationshipRecord.from_thing_id.not_in(thing_ids),  # type: ignore[union-attr]
            ThingRelationshipRecord.to_thing_id.not_in(thing_ids),  # type: ignore[union-attr]
        )
    )
    rows = session.exec(stmt).all()
    return [_record_to_rel(r) for r in rows]


@router.post("/relationships/cleanup", response_model=OrphanCleanupResult, summary="Delete orphan relationships")
def cleanup_orphan_relationships(
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> OrphanCleanupResult:
    """Delete all orphan relationships where from/to thing no longer exists."""
    thing_ids_subq = select(ThingRecord.id).where(
        user_filter_clause(ThingRecord.user_id, user_id)
    )
    orphans = session.exec(
        select(ThingRelationshipRecord).where(
            or_(
                ThingRelationshipRecord.from_thing_id.notin_(thing_ids_subq),  # type: ignore[union-attr]
                ThingRelationshipRecord.to_thing_id.notin_(thing_ids_subq),  # type: ignore[union-attr]
            )
        )
    ).all()
    orphan_ids = [r.id for r in orphans]
    for r in orphans:
        session.delete(r)
    if orphan_ids:
        session.commit()
        _logger.info("Cleaned %d orphan relationship(s): %s", len(orphan_ids), orphan_ids)
    return OrphanCleanupResult(deleted_count=len(orphan_ids), deleted_ids=orphan_ids)


# -- Relationships --

def _parse_rel_row(row: Any) -> Relationship:
    """Convert a Row or SQLModel record to a Relationship response model."""
    meta = getattr(row, "metadata_", None) or getattr(row, "metadata", None)
    if isinstance(meta, str) and meta:
        try:
            meta = json.loads(meta)
        except (json.JSONDecodeError, ValueError):
            meta = None
    if isinstance(meta, str):
        meta = None
    created_at = getattr(row, "created_at", None)
    return Relationship(
        id=row.id,
        from_thing_id=row.from_thing_id,
        to_thing_id=row.to_thing_id,
        relationship_type=row.relationship_type,
        metadata=meta,
        created_at=_parse_dt(created_at) if isinstance(created_at, str) else (created_at or datetime.min),  # type: ignore[arg-type]
    )


def _record_to_rel(record: ThingRelationshipRecord) -> Relationship:
    """Convert a ThingRelationshipRecord to a Relationship response model."""
    return Relationship(
        id=record.id,
        from_thing_id=record.from_thing_id,
        to_thing_id=record.to_thing_id,
        relationship_type=record.relationship_type,
        metadata=record.metadata_,
        created_at=record.created_at or datetime.min,
    )


@router.get("/{thing_id}/relationships", response_model=list[Relationship], summary="List relationships for a Thing")
def list_relationships(
    thing_id: str,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> list[Relationship]:
    """List all relationships where the given Thing is either the source or target."""
    # Verify thing exists
    thing = session.exec(
        select(ThingRecord).where(
            ThingRecord.id == thing_id,
            user_filter_clause(ThingRecord.user_id, user_id),
        )
    ).first()
    if not thing:
        raise HTTPException(status_code=404, detail=f"Thing '{thing_id}' not found")

    records = session.exec(
        select(ThingRelationshipRecord).where(
            or_(
                ThingRelationshipRecord.from_thing_id == thing_id,
                ThingRelationshipRecord.to_thing_id == thing_id,
            )
        )
    ).all()
    return [_record_to_rel(r) for r in records]


@router.post(
    "/relationships", response_model=Relationship, status_code=status.HTTP_201_CREATED, summary="Create a relationship"
)
def create_relationship(
    body: RelationshipCreate,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Relationship:
    """Create a typed relationship between two Things."""
    uf = user_filter_clause(ThingRecord.user_id, user_id)
    for tid, label in [(body.from_thing_id, "from"), (body.to_thing_id, "to")]:
        if not session.exec(select(ThingRecord).where(ThingRecord.id == tid, uf)).first():
            raise HTTPException(status_code=404, detail=f"{label}_thing_id '{tid}' not found")
    if body.from_thing_id == body.to_thing_id:
        raise HTTPException(status_code=422, detail="A Thing cannot have a relationship with itself")

    record = ThingRelationshipRecord(
        from_thing_id=body.from_thing_id,
        to_thing_id=body.to_thing_id,
        relationship_type=body.relationship_type,
        metadata_=body.metadata,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return _record_to_rel(record)


@router.delete("/relationships/{rel_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a relationship")
def delete_relationship(
    rel_id: str,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> None:
    """Delete a relationship by ID."""
    record = session.get(ThingRelationshipRecord, rel_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Relationship '{rel_id}' not found")
    from_thing = session.get(ThingRecord, record.from_thing_id)
    to_thing = session.get(ThingRecord, record.to_thing_id)
    if not (
        (from_thing and from_thing.user_id == user_id)
        or (to_thing and to_thing.user_id == user_id)
    ):
        raise HTTPException(status_code=404, detail=f"Relationship '{rel_id}' not found")
    session.delete(record)
    session.commit()
