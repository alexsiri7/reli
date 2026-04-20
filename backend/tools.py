"""Shared tool implementations for Reli -- used by both MCP server and reasoning agent.

Each function takes explicit parameters, hits the DB directly, and returns plain dicts.
No side-effect tracking (applied/fetched_context) -- callers handle that themselves.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, or_, select

import backend.db_engine as _engine_mod

from .db_engine import user_filter_clause
from .db_models import ChatHistoryRecord, ScheduledTaskRecord, ThingRecord, ThingRelationshipRecord
from .db_models import MergeHistoryRecord as MergeHistoryDBRecord
from .vector_store import delete_thing as vs_delete
from .vector_store import upsert_thing

logger = logging.getLogger(__name__)

# type_hints that default to surface=false. Advisory only — any type_hint string is valid.
_NONSURFACE_TYPES = {"person", "place", "event", "concept", "reference", "preference"}


def _thing_to_dict(record: ThingRecord) -> dict[str, Any]:
    """Convert a ThingRecord to a plain dict matching the legacy sqlite3.Row format."""
    d = record.model_dump()
    # Legacy code expects 'priority' key
    d.setdefault("priority", record.priority)
    return d


def _rel_to_dict(record: ThingRelationshipRecord) -> dict[str, Any]:
    """Convert a ThingRelationshipRecord to a plain dict."""
    return {
        "id": record.id,
        "from_thing_id": record.from_thing_id,
        "to_thing_id": record.to_thing_id,
        "relationship_type": record.relationship_type,
        "metadata": record.metadata_,
        "created_at": record.created_at,
    }


# ---------------------------------------------------------------------------
# fetch_context
# ---------------------------------------------------------------------------


def fetch_context(
    search_queries_json: str = "[]",
    fetch_ids_json: str = "[]",
    active_only: bool = True,
    type_hint: str = "",
    user_id: str = "",
) -> dict[str, Any]:
    """Search the Things database for relevant context.

    Returns dict with 'things', 'relationships', and 'count'.
    """
    from .pipeline import _fetch_relevant_things, _fetch_with_family

    try:
        search_queries = json.loads(search_queries_json)
        if not isinstance(search_queries, list):
            search_queries = [str(search_queries)]
    except (json.JSONDecodeError, TypeError):
        search_queries = [search_queries_json] if search_queries_json else []

    try:
        fetch_ids = json.loads(fetch_ids_json)
        if not isinstance(fetch_ids, list):
            fetch_ids = [str(fetch_ids)]
    except (json.JSONDecodeError, TypeError):
        fetch_ids = []

    if not search_queries and not fetch_ids:
        return {"things": [], "relationships": [], "count": 0}

    filter_params = {"active_only": active_only, "type_hint": type_hint or None}

    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []

    with Session(_engine_mod.engine) as session:
        if search_queries:
            things = _fetch_relevant_things(
                session,
                search_queries,
                filter_params,
                user_id=user_id,
            )
            for t in things:
                if t["id"] not in seen_ids:
                    seen_ids.add(t["id"])
                    results.append(t)

        if fetch_ids:
            id_things = _fetch_with_family(
                session,
                [tid for tid in fetch_ids if tid not in seen_ids],
            )
            for t in id_things:
                if t["id"] not in seen_ids:
                    seen_ids.add(t["id"])
                    results.append(t)

        # Fetch relationships between found Things
        relationships: list[dict[str, Any]] = []
        if results:
            ids = [t["id"] for t in results]
            rel_stmt = select(ThingRelationshipRecord).where(
                or_(
                    ThingRelationshipRecord.from_thing_id.in_(ids),  # type: ignore[union-attr]
                    ThingRelationshipRecord.to_thing_id.in_(ids),  # type: ignore[union-attr]
                )
            )
            rel_rows = session.exec(rel_stmt).all()
            relationships = [
                {
                    "from_thing_id": r.from_thing_id,
                    "to_thing_id": r.to_thing_id,
                    "relationship_type": r.relationship_type,
                }
                for r in rel_rows
            ]

        # Update last_referenced timestamp
        if results:
            now = datetime.now(timezone.utc)
            ids = [t["id"] for t in results]
            for thing_rec in session.exec(
                select(ThingRecord).where(ThingRecord.id.in_(ids))  # type: ignore[union-attr]
            ).all():
                thing_rec.last_referenced = now
                session.add(thing_rec)

    return {
        "things": results,
        "relationships": relationships,
        "count": len(results),
    }


# ---------------------------------------------------------------------------
# chat_history
# ---------------------------------------------------------------------------


def chat_history(
    n: int = 10,
    search_query: str = "",
    session_id: str = "",
    user_id: str = "",
    cross_session: bool = False,
) -> dict[str, Any]:
    """Retrieve messages from conversation history.

    When cross_session=True, searches across ALL sessions for the given user_id.
    Otherwise, searches within the given session_id only.

    Returns dict with 'messages' and 'count'.
    """
    if not cross_session and not session_id:
        return {"messages": [], "count": 0, "error": "No session context available"}

    n = max(1, min(n, 50))

    with Session(_engine_mod.engine) as session:
        stmt = select(ChatHistoryRecord)

        if cross_session and user_id:
            stmt = stmt.where(ChatHistoryRecord.user_id == user_id)
            if search_query and search_query.strip():
                stmt = stmt.where(ChatHistoryRecord.content.contains(search_query.strip()))  # type: ignore[attr-defined]
        else:
            stmt = stmt.where(ChatHistoryRecord.session_id == session_id)
            if search_query and search_query.strip():
                stmt = stmt.where(ChatHistoryRecord.content.contains(search_query.strip()))  # type: ignore[attr-defined]

        stmt = stmt.order_by(ChatHistoryRecord.id.desc()).limit(n)  # type: ignore[union-attr]
        rows = session.exec(stmt).all()

    # Reverse to chronological order
    messages = []
    for r in reversed(rows):
        msg: dict[str, Any] = {
            "role": r.role,
            "content": r.content,
            "timestamp": r.timestamp,
        }
        if cross_session and user_id:
            msg["session_id"] = r.session_id
        messages.append(msg)

    return {"messages": messages, "count": len(messages)}


# ---------------------------------------------------------------------------
# create_thing
# ---------------------------------------------------------------------------


def create_thing(
    title: str,
    type_hint: str = "",
    importance: int = 2,
    checkin_date: str = "",
    surface: bool = True,
    data_json: str = "{}",
    open_questions_json: str = "[]",
    user_id: str = "",
) -> dict[str, Any]:
    """Create a new Thing in the database.

    Returns the created Thing dict including its generated 'id'.
    If a Thing with the same title exists, converts to an update (deduplication).
    """
    title = title.strip()
    if not title:
        return {"error": "title is required"}

    now = datetime.now(timezone.utc)

    try:
        data = json.loads(data_json) if data_json else {}
        if not isinstance(data, dict):
            return {
                "error": f"data_json must be a JSON object, got {type(data).__name__}. "
                'Wrap your data in curly braces: {"key": "value"}'
            }
    except (json.JSONDecodeError, TypeError) as exc:
        return {"error": f"data_json is not valid JSON: {exc}"}
    try:
        open_questions = json.loads(open_questions_json) if open_questions_json else []
    except json.JSONDecodeError:
        open_questions = []

    with Session(_engine_mod.engine) as session:
        # Deduplicate: if a Thing with the same title exists, convert to update
        from sqlalchemy import func
        stmt = select(ThingRecord).where(
            func.lower(ThingRecord.title) == func.lower(title),
            ThingRecord.active == True,
        ).limit(1)
        existing = session.exec(stmt).first()

        if existing:
            logger.info(
                "Dedup: converting create for '%s' into update on %s",
                title,
                existing.id,
            )
            if data:
                old = existing.data if isinstance(existing.data, dict) else {}
                existing.data = {**old, **data}
            if open_questions:
                existing.open_questions = open_questions
            if checkin_date and not existing.checkin_date:
                existing.checkin_date = datetime.fromisoformat(checkin_date) if isinstance(checkin_date, str) else checkin_date
            existing.updated_at = now
            session.add(existing)
            session.commit()
            session.refresh(existing)
            row_dict = _thing_to_dict(existing)
            row_dict["deduplicated"] = True
            upsert_thing(row_dict)
            return row_dict

        # Create new Thing
        thing_id = str(uuid.uuid4())
        effective_surface = surface
        # Custom types (not in _NONSURFACE_TYPES) default to surface=true
        if type_hint in _NONSURFACE_TYPES:
            effective_surface = False
        oq = open_questions if open_questions else None

        record = ThingRecord(
            id=thing_id,
            title=title,
            type_hint=type_hint or None,
            checkin_date=datetime.fromisoformat(checkin_date) if checkin_date else None,
            importance=importance,
            active=True,
            surface=effective_surface,
            data=data if data else None,
            open_questions=oq,
            created_at=now,
            updated_at=now,
            user_id=user_id or None,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        row_dict = _thing_to_dict(record)
        upsert_thing(row_dict)
        return row_dict


# ---------------------------------------------------------------------------
# update_thing
# ---------------------------------------------------------------------------


def update_thing(
    thing_id: str,
    title: str = "",
    active: bool | None = None,
    checkin_date: str = "",
    importance: int | None = None,
    type_hint: str = "",
    surface: bool | None = None,
    data_json: str = "",
    open_questions_json: str = "",
    user_id: str = "",
) -> dict[str, Any]:
    """Update an existing Thing's fields.

    Returns the updated Thing dict, or an error dict.
    """
    thing_id = thing_id.strip()
    if not thing_id:
        return {"error": "thing_id is required"}

    now = datetime.now(timezone.utc)

    with Session(_engine_mod.engine) as session:
        record = session.get(ThingRecord, thing_id)
        if not record:
            return {"error": f"Thing {thing_id} not found"}

        if record.user_id and user_id and record.user_id != user_id:
            return {"error": "Unauthorized"}

        changed = False
        if title:
            record.title = title
            changed = True
        if active is not None:
            record.active = bool(active)
            changed = True
        if checkin_date:
            record.checkin_date = datetime.fromisoformat(checkin_date) if isinstance(checkin_date, str) else checkin_date
            changed = True
        if importance is not None:
            record.importance = importance
            changed = True
        if type_hint:
            record.type_hint = type_hint
            changed = True
        if surface is not None:
            record.surface = bool(surface)
            changed = True
        if data_json:
            try:
                new_data = json.loads(data_json)
                if not isinstance(new_data, dict):
                    return {
                        "error": f"data_json must be a JSON object, got {type(new_data).__name__}. "
                        'Use {"key": "value"} format.'
                    }
            except (json.JSONDecodeError, TypeError) as exc:
                return {"error": f"data_json is not valid JSON: {exc}"}
            if new_data:
                old_data = record.data if isinstance(record.data, dict) else {}
                record.data = {**old_data, **new_data}
                changed = True
        if open_questions_json:
            try:
                oq = json.loads(open_questions_json)
                record.open_questions = oq if oq else None
                changed = True
            except json.JSONDecodeError:
                pass

        if not changed:
            return {"error": "no fields to update"}

        record.updated_at = now
        session.add(record)
        session.commit()
        session.refresh(record)
        row_dict = _thing_to_dict(record)
        upsert_thing(row_dict)
        return row_dict


# ---------------------------------------------------------------------------
# delete_thing
# ---------------------------------------------------------------------------


def delete_thing(thing_id: str, user_id: str = "") -> dict[str, Any]:
    """Delete a Thing by ID (hard delete).

    Returns confirmation dict with the deleted Thing ID.
    """
    thing_id = thing_id.strip()
    if not thing_id:
        return {"error": "thing_id is required"}

    with Session(_engine_mod.engine) as session:
        record = session.get(ThingRecord, thing_id)
        if not record:
            return {"error": f"Thing {thing_id} not found"}

        if record.user_id and user_id and record.user_id != user_id:
            return {"error": "Unauthorized"}

        title = record.title
        session.delete(record)
        session.commit()
        vs_delete(thing_id)
    return {"deleted": thing_id, "title": title}


# ---------------------------------------------------------------------------
# merge_things
# ---------------------------------------------------------------------------


def merge_things(
    keep_id: str,
    remove_id: str,
    merged_data_json: str = "{}",
    user_id: str = "",
) -> dict[str, Any]:
    """Merge a duplicate Thing into a primary Thing.

    Transfers relationships, consolidates data and open_questions, then
    deletes the duplicate.
    """
    keep_id = keep_id.strip()
    remove_id = remove_id.strip()
    if not keep_id or not remove_id or keep_id == remove_id:
        return {"error": "need two distinct Thing IDs"}

    now = datetime.now(timezone.utc)
    try:
        merged_data = json.loads(merged_data_json) if merged_data_json else {}
        if not isinstance(merged_data, dict):
            return {
                "error": f"merged_data_json must be a JSON object, got {type(merged_data).__name__}. "
                'Use {"key": "value"} format.'
            }
    except (json.JSONDecodeError, TypeError) as exc:
        return {"error": f"merged_data_json is not valid JSON: {exc}"}

    with Session(_engine_mod.engine) as session:
        keep_rec = session.get(ThingRecord, keep_id)
        remove_rec = session.get(ThingRecord, remove_id)
        if not keep_rec or not remove_rec:
            return {"error": "one or both Things not found"}

        if keep_rec.user_id and user_id and keep_rec.user_id != user_id:
            return {"error": "Unauthorized"}
        if remove_rec.user_id and user_id and remove_rec.user_id != user_id:
            return {"error": "Unauthorized"}

        remove_title = remove_rec.title

        # 1. Merge data
        old_data = keep_rec.data if isinstance(keep_rec.data, dict) else {}
        if merged_data or old_data:
            keep_rec.data = {**old_data, **merged_data}

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
        session.add(keep_rec)

        # 3. Re-point relationships
        for rel in session.exec(
            select(ThingRelationshipRecord).where(ThingRelationshipRecord.from_thing_id == remove_id)
        ).all():
            rel.from_thing_id = keep_id
            session.add(rel)
        for rel in session.exec(
            select(ThingRelationshipRecord).where(ThingRelationshipRecord.to_thing_id == remove_id)
        ).all():
            rel.to_thing_id = keep_id
            session.add(rel)
        # Delete self-referential
        for rel in session.exec(
            select(ThingRelationshipRecord).where(
                ThingRelationshipRecord.from_thing_id == keep_id,
                ThingRelationshipRecord.to_thing_id == keep_id,
            )
        ).all():
            session.delete(rel)

        # 4. Delete duplicate
        session.delete(remove_rec)
        vs_delete(remove_id)

        # 5. Record merge history
        _rem_data = remove_rec.data if isinstance(remove_rec.data, dict) else {}
        _merged_snapshot = {**_rem_data, **merged_data} if (merged_data or _rem_data) else None
        merge_record = MergeHistoryDBRecord(
            id=str(uuid.uuid4()),
            keep_id=keep_id,
            remove_id=remove_id,
            keep_title=keep_rec.title,
            remove_title=remove_title,
            merged_data=_merged_snapshot,
            triggered_by="agent",
            user_id=user_id or None,
            created_at=now,
        )
        session.add(merge_record)

        session.commit()

        # 6. Re-embed
        session.refresh(keep_rec)
        row_dict = _thing_to_dict(keep_rec)
        upsert_thing(row_dict)
        return {
            "keep_id": keep_id,
            "remove_id": remove_id,
            "keep_title": keep_rec.title,
            "remove_title": remove_title,
        }


# ---------------------------------------------------------------------------
# create_relationship
# ---------------------------------------------------------------------------


def create_relationship(
    from_thing_id: str,
    to_thing_id: str,
    relationship_type: str,
    user_id: str = "",
) -> dict[str, Any]:
    """Create a typed relationship link between two Things.

    Returns the created relationship dict, or an error dict.
    """
    from_id = from_thing_id.strip()
    to_id = to_thing_id.strip()
    rel_type = relationship_type.strip()
    if not from_id or not to_id or not rel_type:
        return {"error": "from_thing_id, to_thing_id, and relationship_type are required"}
    if from_id == to_id:
        return {"error": "cannot create self-referential relationship"}

    with Session(_engine_mod.engine) as session:
        # Skip duplicate
        dup = session.exec(
            select(ThingRelationshipRecord).where(
                ThingRelationshipRecord.from_thing_id == from_id,
                ThingRelationshipRecord.to_thing_id == to_id,
                ThingRelationshipRecord.relationship_type == rel_type,
            ).limit(1)
        ).first()
        if dup:
            return {"status": "duplicate", "relationship_type": rel_type}

        # Verify both things exist
        from_row = session.get(ThingRecord, from_id)
        to_row = session.get(ThingRecord, to_id)
        if not from_row or not to_row:
            missing = []
            if not from_row:
                missing.append(f"from={from_id}")
            if not to_row:
                missing.append(f"to={to_id}")
            return {"error": f"Thing(s) not found: {', '.join(missing)}"}

        # Verify ownership
        if from_row.user_id and user_id and from_row.user_id != user_id:
            return {"error": "Unauthorized"}
        if to_row.user_id and user_id and to_row.user_id != user_id:
            return {"error": "Unauthorized"}

        rel_id = str(uuid.uuid4())
        record = ThingRelationshipRecord(
            id=rel_id,
            from_thing_id=from_id,
            to_thing_id=to_id,
            relationship_type=rel_type,
            metadata_=None,
        )
        session.add(record)
        session.commit()
        return {
            "id": rel_id,
            "from_thing_id": from_id,
            "to_thing_id": to_id,
            "relationship_type": rel_type,
        }


# ---------------------------------------------------------------------------
# get_thing
# ---------------------------------------------------------------------------


def get_thing(
    thing_id: str,
    user_id: str = "",
) -> dict[str, Any]:
    """Get a single Thing by ID.

    Returns the Thing dict, or an error dict if not found.
    """
    with Session(_engine_mod.engine) as session:
        stmt = select(ThingRecord).where(
            ThingRecord.id == thing_id,
            user_filter_clause(ThingRecord.user_id, user_id),
        )
        record = session.exec(stmt).first()
    if not record:
        return {"error": f"Thing {thing_id} not found"}
    return _thing_to_dict(record)


# ---------------------------------------------------------------------------
# search_things
# ---------------------------------------------------------------------------


def search_things(
    query: str,
    active_only: bool = False,
    type_hint: str | None = None,
    limit: int = 20,
    user_id: str = "",
) -> list[dict[str, Any]]:
    """Search Things by text query across titles, data, types, and relationships.

    Uses a two-phase approach to avoid timeout: first searches direct matches,
    then searches relationship-connected Things only if more results are needed.

    Returns a list of Thing dicts.
    """
    if not query.strip():
        return []

    from .db_engine import user_filter_text

    pattern = f"%{query}%"
    with Session(_engine_mod.engine) as session:
        uf_frag, uf_params = user_filter_text(user_id, "t")

        filters = uf_frag
        params: dict[str, Any] = {**uf_params, "pattern": pattern, "lim": limit}
        if active_only:
            filters += " AND t.active = true"
        if type_hint:
            filters += " AND t.type_hint = :type_hint"
            params["type_hint"] = type_hint

        # Phase 1: Direct matches on title, type_hint, and data
        direct_sql = text(
            "SELECT t.* FROM things t"
            " WHERE (t.title LIKE :pattern OR t.type_hint LIKE :pattern"
            "        OR CAST(t.data AS TEXT) LIKE :pattern)"
            + filters +
            " ORDER BY t.updated_at DESC"
            " LIMIT :lim"
        )
        direct_rows = session.execute(direct_sql, params).fetchall()
        seen_ids = {r.id for r in direct_rows}
        results = list(direct_rows)

        # Phase 2: Relationship-connected matches (only if we need more results)
        remaining = limit - len(results)
        if remaining > 0:
            rel_params = {**params, "lim": remaining}
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
                " LIMIT :lim"
            )
            rel_rows = session.execute(rel_sql, rel_params).fetchall()
            for r in rel_rows:
                if r.id not in seen_ids:
                    seen_ids.add(r.id)
                    results.append(r)

    return [dict(r._mapping) for r in results[:limit]]


# ---------------------------------------------------------------------------
# list_relationships
# ---------------------------------------------------------------------------


def list_relationships(
    thing_id: str,
    user_id: str = "",
) -> list[dict[str, Any]]:
    """List all relationships where a Thing is source or target.

    Returns a list of relationship dicts.
    """
    with Session(_engine_mod.engine) as session:
        stmt = select(ThingRelationshipRecord).where(
            or_(
                ThingRelationshipRecord.from_thing_id == thing_id,
                ThingRelationshipRecord.to_thing_id == thing_id,
            )
        )
        records = session.exec(stmt).all()
    return [_rel_to_dict(r) for r in records]


# ---------------------------------------------------------------------------
# delete_relationship
# ---------------------------------------------------------------------------


def delete_relationship(relationship_id: str, user_id: str = "") -> dict[str, Any]:
    """Delete a relationship between two Things.

    Returns {"ok": True} on success, or an error dict.
    """
    with Session(_engine_mod.engine) as session:
        record = session.get(ThingRelationshipRecord, relationship_id)
        if not record:
            return {"error": f"Relationship {relationship_id} not found"}

        # Verify both Things in the relationship belong to the user
        if user_id:
            from_thing = session.get(ThingRecord, record.from_thing_id)
            to_thing = session.get(ThingRecord, record.to_thing_id)
            if from_thing and from_thing.user_id and from_thing.user_id != user_id:
                return {"error": "Unauthorized"}
            if to_thing and to_thing.user_id and to_thing.user_id != user_id:
                return {"error": "Unauthorized"}

        session.delete(record)
        session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# get_briefing
# ---------------------------------------------------------------------------


def get_briefing(
    as_of: str | None = None,
    user_id: str = "",
) -> dict[str, Any]:
    """Get daily briefing using importance x urgency scoring.

    Returns dict with 'the_one_thing', 'secondary', 'parking_lot',
    'findings', 'total', and 'stats'.
    """
    from .urgency import build_blocker_graph, compute_composite_score, compute_urgency

    target = date.fromisoformat(as_of) if as_of else date.today()
    horizon = datetime.combine(target + timedelta(days=14), datetime.max.time())
    now = datetime.now(timezone.utc)

    with Session(_engine_mod.engine) as session:
        # All active things (used for blocker graph AND to derive checkin-due subset)
        all_active_stmt = select(ThingRecord).where(
            ThingRecord.active == True,
            user_filter_clause(ThingRecord.user_id, user_id),
        )
        all_active = session.exec(all_active_stmt).all()

        # Relationships for blocker graph
        rel_stmt = select(ThingRelationshipRecord).where(
            ThingRelationshipRecord.relationship_type.in_(["blocks", "depends-on"])  # type: ignore[attr-defined]
        )
        rel_rows = session.exec(rel_stmt).all()

        # Active sweep findings (exclude findings linked to inactive Things)
        from .db_models import SweepFindingRecord
        finding_stmt = (
            select(SweepFindingRecord)
            .outerjoin(ThingRecord, SweepFindingRecord.thing_id == ThingRecord.id)
            .where(
                SweepFindingRecord.dismissed == False,
                or_(SweepFindingRecord.expires_at.is_(None), SweepFindingRecord.expires_at > now),  # type: ignore[union-attr, operator]
                or_(SweepFindingRecord.snoozed_until.is_(None), SweepFindingRecord.snoozed_until <= now),  # type: ignore[union-attr, operator]
                user_filter_clause(SweepFindingRecord.user_id, user_id),
                or_(SweepFindingRecord.thing_id.is_(None), ThingRecord.active == True),  # type: ignore[union-attr]
            )
            .order_by(SweepFindingRecord.priority.asc(), SweepFindingRecord.created_at.desc())  # type: ignore[union-attr, attr-defined]
        )
        finding_rows = session.exec(finding_stmt).all()

    total_active = len(all_active)

    # Filter checkin-due things from all_active (avoids a separate query)
    thing_rows = sorted(
        [r for r in all_active if r.checkin_date is not None and r.checkin_date <= horizon],
        key=lambda r: r.checkin_date,  # type: ignore[arg-type]
    )

    # Build blocker graph
    all_things_map = {r.id: {"id": r.id, "importance": r.importance, "active": r.active} for r in all_active}
    blocker_graph = build_blocker_graph([
        {
            "from_thing_id": r.from_thing_id,
            "to_thing_id": r.to_thing_id,
            "relationship_type": r.relationship_type,
        }
        for r in rel_rows
    ])

    # Score each checkin-due thing
    scored: list[dict[str, Any]] = []
    for rec in thing_rows:
        thing = _thing_to_dict(rec)
        imp = rec.importance if rec.importance is not None else 2
        urgency, reasons = compute_urgency(thing, target, blocker_graph, all_things_map)
        composite = compute_composite_score(int(imp), urgency)
        scored.append({
            "thing": thing,
            "importance": imp,
            "urgency": round(urgency, 2),
            "score": round(composite, 2),
            "reasons": reasons,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    the_one_thing = scored[0] if scored else None
    secondary = scored[1:6] if len(scored) > 1 else []
    parking_lot = [
        {"thing_id": s["thing"]["id"], "title": s["thing"]["title"],
         "importance": s["importance"], "urgency": s["urgency"]}
        for s in scored[6:]
    ] if len(scored) > 6 else []

    findings = [f.model_dump() for f in finding_rows]
    checkin_due = sum(1 for s in scored if s["urgency"] >= 0.25)

    return {
        "date": target.isoformat(),
        "the_one_thing": the_one_thing,
        "secondary": secondary,
        "parking_lot": parking_lot,
        "findings": findings,
        "total": len(scored) + len(findings),
        "stats": {
            "active_things": total_active,
            "checkin_due": checkin_due,
            "overdue": sum(1 for s in scored if "overdue" in " ".join(s["reasons"]).lower()),
        },
    }


# ---------------------------------------------------------------------------
# get_open_questions
# ---------------------------------------------------------------------------


def get_open_questions(
    limit: int = 50,
    user_id: str = "",
) -> list[dict[str, Any]]:
    """Get active Things that have non-empty open_questions arrays.

    Returns a list of Thing dicts ordered by priority then recency.
    """
    with Session(_engine_mod.engine) as session:
        stmt = select(ThingRecord).where(
            ThingRecord.active == True,
            ThingRecord.open_questions.is_not(None),  # type: ignore[union-attr]
            user_filter_clause(ThingRecord.user_id, user_id),
        ).order_by(
            ThingRecord.importance.asc(),  # type: ignore[union-attr, attr-defined]
            ThingRecord.updated_at.desc(),  # type: ignore[union-attr, attr-defined]
        ).limit(limit)
        records = session.exec(stmt).all()

    # Filter out empty arrays (can't easily do in SQL with JSON)
    results = []
    for r in records:
        if r.open_questions and len(r.open_questions) > 0:
            results.append(_thing_to_dict(r))
    return results


# ---------------------------------------------------------------------------
# get_conflicts
# ---------------------------------------------------------------------------


def get_conflicts(
    window: int = 14,
    user_id: str = "",
) -> list[dict[str, Any]]:
    """Detect blockers, schedule overlaps, and deadline conflicts.

    Thin wrapper around detect_all_conflicts from conflict_detector.py.
    Returns a list of conflict alert dicts.
    """
    from .conflict_detector import detect_all_conflicts

    alerts = detect_all_conflicts(user_id=user_id, window_days=window)
    return [
        {
            "alert_type": a.alert_type,
            "severity": a.severity,
            "message": a.message,
            "thing_ids": a.thing_ids,
            "thing_titles": a.thing_titles,
        }
        for a in alerts
    ]


# ---------------------------------------------------------------------------
# calendar_create_event
# ---------------------------------------------------------------------------


def calendar_create_event(
    thing_id: str,
    summary: str,
    start: str,
    end: str,
    location: str = "",
    description: str = "",
    user_id: str = "",
) -> dict[str, Any]:
    """Create a Google Calendar event and store its ID on the Thing.

    Returns the created event dict (with 'id', 'summary', 'html_link'),
    or an error dict if calendar is not connected or creation fails.
    Note: if thing_id is invalid, the event is still created but the ID
    will not be stored on the Thing.
    """
    from . import google_calendar as gc

    if not gc.is_connected(user_id=user_id):
        return {"error": "Google Calendar not connected"}

    event = gc.create_event(
        summary=summary,
        start=start,
        end=end,
        location=location,
        description=description,
        user_id=user_id,
    )
    if not event:
        return {"error": "Failed to create calendar event"}

    # Store the calendar event ID on the Thing
    calendar_event_id = event.get("id", "")
    if calendar_event_id and thing_id:
        link_result = update_thing(
            thing_id=thing_id,
            data_json=json.dumps({"calendar_event_id": calendar_event_id}),
            user_id=user_id,
        )
        if "error" in link_result:
            logger.warning(
                "calendar_create_event: created calendar event %s but failed to store id on Thing %s: %s",
                calendar_event_id,
                thing_id,
                link_result["error"],
            )

    return event


# ---------------------------------------------------------------------------
# calendar_update_event
# ---------------------------------------------------------------------------


def calendar_update_event(
    thing_id: str,
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
    description: str | None = None,
    user_id: str = "",
) -> dict[str, Any]:
    """Update an existing Google Calendar event linked to a Thing.

    Reads the event_id from Thing's data.calendar_event_id.
    Returns the updated event dict, or an error dict.
    """
    from . import google_calendar as gc

    if not gc.is_connected(user_id=user_id):
        return {"error": "Google Calendar not connected"}

    # Get the Thing to find its linked calendar event ID
    thing = get_thing(thing_id=thing_id, user_id=user_id)
    if "error" in thing:
        return thing

    data = thing.get("data") or {}
    event_id = data.get("calendar_event_id", "")
    if not event_id:
        return {"error": "No calendar_event_id found on this Thing — use calendar_create_event first"}

    event = gc.update_event(
        event_id=event_id,
        summary=summary,
        start=start,
        end=end,
        location=location,
        description=description,
        user_id=user_id,
    )
    if not event:
        return {"error": "Failed to update calendar event"}

    return event


# ---------------------------------------------------------------------------
# create_scheduled_task
# ---------------------------------------------------------------------------


def create_scheduled_task(
    scheduled_at: str,
    task_type: str = "remind",
    thing_id: str = "",
    payload_json: str = "{}",
    user_id: str = "",
) -> dict[str, Any]:
    """Create a scheduled task for autonomous future execution.

    Args:
        scheduled_at: ISO-8601 datetime string (required, must be non-empty).
            Timezone-aware strings are converted to UTC; naive strings are
            treated as UTC.
        task_type: One of "remind", "check", "sweep_concern", "custom".
        thing_id: UUID of a related Thing, or empty string / omit for none.
        payload_json: JSON-encoded dict with task data (e.g. '{"message": "..."}').
        user_id: Owner user ID, or empty string for legacy/no-user context.

    Returns:
        The created task dict (includes generated 'id') on success, or
        {"error": "<message>"} if validation fails.
    """
    if not scheduled_at or not scheduled_at.strip():
        return {"error": "scheduled_at is required"}

    try:
        parsed_at = datetime.fromisoformat(scheduled_at.strip())
    except (ValueError, TypeError) as exc:
        return {"error": f"scheduled_at is not valid ISO-8601: {exc}"}

    # Normalize: if tz-aware, convert to UTC naive; if naive, treat as UTC.
    # SQLite stores datetimes as strings — always keep them UTC-naive so that
    # comparisons against datetime.now(timezone.utc) are correct.
    if parsed_at.tzinfo is not None:
        parsed_at = parsed_at.astimezone(timezone.utc).replace(tzinfo=None)

    try:
        payload = json.loads(payload_json) if payload_json else {}
    except (json.JSONDecodeError, TypeError) as exc:
        return {"error": f"payload_json is not valid JSON: {exc}"}

    with Session(_engine_mod.engine) as session:
        record = ScheduledTaskRecord(
            user_id=user_id or None,
            thing_id=thing_id or None,
            task_type=task_type.strip() or "remind",
            payload=payload if payload else None,
            scheduled_at=parsed_at,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.model_dump()


# ---------------------------------------------------------------------------
# get_due_scheduled_tasks
# ---------------------------------------------------------------------------


def get_due_scheduled_tasks(user_id: str = "") -> list[dict[str, Any]]:
    """Return scheduled tasks that are due (scheduled_at <= now) and not yet executed."""
    now = datetime.now(timezone.utc)

    with Session(_engine_mod.engine) as session:
        stmt = select(ScheduledTaskRecord).where(
            ScheduledTaskRecord.scheduled_at <= now,
            ScheduledTaskRecord.executed_at.is_(None),  # type: ignore[union-attr]
            user_filter_clause(ScheduledTaskRecord.user_id, user_id),
        )
        records = session.exec(stmt).all()
    return [r.model_dump() for r in records]
