"""Shared tool implementations for Reli — used by both MCP server and reasoning agent.

Each function takes explicit parameters, hits the DB directly, and returns plain dicts.
No side-effect tracking (applied/fetched_context) — callers handle that themselves.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from .auth import user_filter
from .database import db
from .vector_store import delete_thing as vs_delete
from .vector_store import upsert_thing

logger = logging.getLogger(__name__)

# Entity type_hints that default to surface=false
_ENTITY_TYPES = {"person", "place", "event", "concept", "reference", "preference"}


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

    with db() as conn:
        if search_queries:
            things = _fetch_relevant_things(
                conn,
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
                conn,
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
            ph = ",".join("?" for _ in ids)
            rel_rows = conn.execute(
                f"SELECT from_thing_id, to_thing_id, relationship_type "
                f"FROM thing_relationships "
                f"WHERE from_thing_id IN ({ph}) OR to_thing_id IN ({ph})",
                ids + ids,
            ).fetchall()
            relationships = [dict(r) for r in rel_rows]

        # Update last_referenced timestamp
        if results:
            now = datetime.now(timezone.utc).isoformat()
            ids = [t["id"] for t in results]
            ph = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE things SET last_referenced = ? WHERE id IN ({ph})",
                [now] + ids,
            )

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

    with db() as conn:
        if cross_session and user_id:
            # Search across all sessions for this user
            if search_query and search_query.strip():
                rows = conn.execute(
                    "SELECT role, content, timestamp, session_id FROM chat_history"
                    " WHERE user_id = ? AND content LIKE ?"
                    " ORDER BY id DESC LIMIT ?",
                    (user_id, f"%{search_query.strip()}%", n),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT role, content, timestamp, session_id FROM chat_history"
                    " WHERE user_id = ?"
                    " ORDER BY id DESC LIMIT ?",
                    (user_id, n),
                ).fetchall()
        else:
            # Search within a single session
            if search_query and search_query.strip():
                rows = conn.execute(
                    "SELECT role, content, timestamp FROM chat_history"
                    " WHERE session_id = ? AND content LIKE ?"
                    " ORDER BY id DESC LIMIT ?",
                    (session_id, f"%{search_query.strip()}%", n),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT role, content, timestamp FROM chat_history"
                    " WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                    (session_id, n),
                ).fetchall()

    # Reverse to chronological order
    messages = [dict(r) for r in reversed(rows)]

    return {"messages": messages, "count": len(messages)}


# ---------------------------------------------------------------------------
# create_thing
# ---------------------------------------------------------------------------


def create_thing(
    title: str,
    type_hint: str = "",
    priority: int = 3,
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

    now = datetime.now(timezone.utc).isoformat()

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

    with db() as conn:
        # Deduplicate: if a Thing with the same title exists, convert to update
        existing = conn.execute(
            "SELECT * FROM things WHERE LOWER(title) = LOWER(?) AND active = 1 LIMIT 1",
            (title,),
        ).fetchone()

        if existing:
            logger.info(
                "Dedup: converting create for '%s' into update on %s",
                title,
                existing["id"],
            )
            merge_fields: dict[str, Any] = {}
            if data:
                try:
                    old = (
                        json.loads(existing["data"])
                        if isinstance(existing["data"], str) and existing["data"]
                        else {}
                    )
                except (ValueError, TypeError):
                    old = {}
                merged = {**old, **data}
                merge_fields["data"] = json.dumps(merged)
            if open_questions:
                merge_fields["open_questions"] = json.dumps(open_questions)
            if checkin_date and not existing["checkin_date"]:
                merge_fields["checkin_date"] = checkin_date
            if merge_fields:
                merge_fields["updated_at"] = now
                set_clause = ", ".join(f"{k} = ?" for k in merge_fields)
                values = list(merge_fields.values()) + [existing["id"]]
                conn.execute(f"UPDATE things SET {set_clause} WHERE id = ?", values)
            updated_row = conn.execute("SELECT * FROM things WHERE id = ?", (existing["id"],)).fetchone()
            if updated_row:
                row_dict = dict(updated_row)
                row_dict["deduplicated"] = True
                upsert_thing(row_dict)
                return row_dict
            return {"id": existing["id"], "title": title, "deduplicated": True}

        # Create new Thing
        thing_id = str(uuid.uuid4())
        data_str = json.dumps(data) if isinstance(data, dict) else str(data)
        effective_surface = surface
        if type_hint in _ENTITY_TYPES:
            effective_surface = False
        oq_json = json.dumps(open_questions) if open_questions else None

        conn.execute(
            """INSERT INTO things
               (id, title, type_hint, parent_id, checkin_date, priority,
                active, surface, data, open_questions, created_at,
                updated_at, user_id)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)""",
            (
                thing_id,
                title,
                type_hint or None,
                None,
                checkin_date or None,
                priority,
                int(effective_surface),
                data_str,
                oq_json,
                now,
                now,
                user_id or None,
            ),
        )
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
        if row:
            row_dict = dict(row)
            upsert_thing(row_dict)
            return row_dict
        return {"id": thing_id, "title": title}


# ---------------------------------------------------------------------------
# update_thing
# ---------------------------------------------------------------------------


def update_thing(
    thing_id: str,
    title: str = "",
    active: bool | None = None,
    checkin_date: str = "",
    priority: int | None = None,
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

    now = datetime.now(timezone.utc).isoformat()

    with db() as conn:
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
        if not row:
            return {"error": f"Thing {thing_id} not found"}

        fields: dict[str, Any] = {}
        if title:
            fields["title"] = title
        if active is not None:
            fields["active"] = int(bool(active))
        if checkin_date:
            fields["checkin_date"] = checkin_date
        if priority is not None:
            fields["priority"] = priority
        if type_hint:
            fields["type_hint"] = type_hint
        if surface is not None:
            fields["surface"] = int(bool(surface))
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
                try:
                    old_data = json.loads(row["data"]) if isinstance(row["data"], str) and row["data"] else {}
                except (ValueError, TypeError):
                    old_data = {}
                merged = {**old_data, **new_data}
                fields["data"] = json.dumps(merged)
        if open_questions_json:
            try:
                oq = json.loads(open_questions_json)
                fields["open_questions"] = json.dumps(oq) if oq else None
            except json.JSONDecodeError:
                pass

        if not fields:
            return {"error": "no fields to update"}

        fields["updated_at"] = now
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [thing_id]
        conn.execute(f"UPDATE things SET {set_clause} WHERE id = ?", values)

        updated_row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
        if updated_row:
            row_dict = dict(updated_row)
            upsert_thing(row_dict)
            return row_dict
        return {"error": "update failed"}


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

    with db() as conn:
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
        if not row:
            return {"error": f"Thing {thing_id} not found"}
        conn.execute("DELETE FROM things WHERE id = ?", (thing_id,))
        vs_delete(thing_id)
    return {"deleted": thing_id, "title": row["title"]}


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

    now = datetime.now(timezone.utc).isoformat()
    try:
        merged_data = json.loads(merged_data_json) if merged_data_json else {}
        if not isinstance(merged_data, dict):
            return {
                "error": f"merged_data_json must be a JSON object, got {type(merged_data).__name__}. "
                'Use {"key": "value"} format.'
            }
    except (json.JSONDecodeError, TypeError) as exc:
        return {"error": f"merged_data_json is not valid JSON: {exc}"}

    with db() as conn:
        keep_row = conn.execute("SELECT * FROM things WHERE id = ?", (keep_id,)).fetchone()
        remove_row = conn.execute("SELECT * FROM things WHERE id = ?", (remove_id,)).fetchone()
        if not keep_row or not remove_row:
            return {"error": "one or both Things not found"}

        # 1. Merge data
        mf: dict[str, Any] = {}
        try:
            old_data = (
                json.loads(keep_row["data"]) if isinstance(keep_row["data"], str) and keep_row["data"] else {}
            )
        except (ValueError, TypeError):
            old_data = {}
        if merged_data or old_data:
            mf["data"] = json.dumps({**old_data, **merged_data})

        # 2. Transfer open_questions
        try:
            keep_oq = (
                json.loads(keep_row["open_questions"])
                if isinstance(keep_row["open_questions"], str) and keep_row["open_questions"]
                else []
            )
        except (ValueError, TypeError):
            keep_oq = []
        try:
            remove_oq = (
                json.loads(remove_row["open_questions"])
                if isinstance(remove_row["open_questions"], str) and remove_row["open_questions"]
                else []
            )
        except (ValueError, TypeError):
            remove_oq = []
        if remove_oq:
            existing_set = set(keep_oq)
            for q in remove_oq:
                if q not in existing_set:
                    keep_oq.append(q)
                    existing_set.add(q)
            mf["open_questions"] = json.dumps(keep_oq)

        if mf:
            mf["updated_at"] = now
            set_clause = ", ".join(f"{k} = ?" for k in mf)
            values = list(mf.values()) + [keep_id]
            conn.execute(f"UPDATE things SET {set_clause} WHERE id = ?", values)

        # 3. Re-point relationships
        conn.execute(
            "UPDATE thing_relationships SET from_thing_id = ? WHERE from_thing_id = ?",
            (keep_id, remove_id),
        )
        conn.execute(
            "UPDATE thing_relationships SET to_thing_id = ? WHERE to_thing_id = ?",
            (keep_id, remove_id),
        )
        conn.execute(
            "DELETE FROM thing_relationships WHERE from_thing_id = ? AND to_thing_id = ?",
            (keep_id, keep_id),
        )

        # 4. Delete duplicate
        conn.execute("DELETE FROM things WHERE id = ?", (remove_id,))
        vs_delete(remove_id)

        # 5. Record merge history
        try:
            _rem_data = (
                json.loads(remove_row["data"]) if isinstance(remove_row["data"], str) and remove_row["data"] else {}
            )
        except (ValueError, TypeError):
            _rem_data = {}
        _merged_snapshot = {**_rem_data, **merged_data} if (merged_data or _rem_data) else None
        conn.execute(
            "INSERT INTO merge_history (id, keep_id, remove_id, keep_title,"
            " remove_title, merged_data, triggered_by, user_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                keep_id,
                remove_id,
                keep_row["title"],
                remove_row["title"],
                json.dumps(_merged_snapshot) if _merged_snapshot else None,
                "agent",
                user_id or None,
                now,
            ),
        )

        # 6. Re-embed
        updated_keep = conn.execute("SELECT * FROM things WHERE id = ?", (keep_id,)).fetchone()
        if updated_keep:
            upsert_thing(dict(updated_keep))
            return {
                "keep_id": keep_id,
                "remove_id": remove_id,
                "keep_title": updated_keep["title"],
                "remove_title": remove_row["title"],
            }

    return {"error": "merge failed"}


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

    with db() as conn:
        # Skip duplicate
        dup = conn.execute(
            "SELECT id FROM thing_relationships"
            " WHERE from_thing_id = ? AND to_thing_id = ? AND relationship_type = ? LIMIT 1",
            (from_id, to_id, rel_type),
        ).fetchone()
        if dup:
            return {"status": "duplicate", "relationship_type": rel_type}

        # Verify both things exist
        from_row = conn.execute("SELECT id FROM things WHERE id = ?", (from_id,)).fetchone()
        to_row = conn.execute("SELECT id FROM things WHERE id = ?", (to_id,)).fetchone()
        if not from_row or not to_row:
            missing = []
            if not from_row:
                missing.append(f"from={from_id}")
            if not to_row:
                missing.append(f"to={to_id}")
            return {"error": f"Thing(s) not found: {', '.join(missing)}"}

        rel_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO thing_relationships"
            " (id, from_thing_id, to_thing_id, relationship_type, metadata)"
            " VALUES (?, ?, ?, ?, ?)",
            (rel_id, from_id, to_id, rel_type, None),
        )
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
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        row = conn.execute(
            f"SELECT * FROM things WHERE id = ?{uf_sql}",
            [thing_id, *uf_params],
        ).fetchone()
    if not row:
        return {"error": f"Thing {thing_id} not found"}
    return dict(row)


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

    Returns a list of Thing dicts.
    """
    if not query.strip():
        return []

    pattern = f"%{query}%"
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

    return [dict(r) for r in rows]


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
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM thing_relationships"
            " WHERE from_thing_id = ? OR to_thing_id = ?",
            (thing_id, thing_id),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# delete_relationship
# ---------------------------------------------------------------------------


def delete_relationship(relationship_id: str, user_id: str = "") -> dict[str, Any]:
    """Delete a relationship between two Things.

    Returns {"ok": True} on success, or an error dict.
    """
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM thing_relationships WHERE id = ?",
            (relationship_id,),
        ).fetchone()
        if not row:
            return {"error": f"Relationship {relationship_id} not found"}
        conn.execute("DELETE FROM thing_relationships WHERE id = ?", (relationship_id,))
    return {"ok": True}


# ---------------------------------------------------------------------------
# get_briefing
# ---------------------------------------------------------------------------


def get_briefing(
    as_of: str | None = None,
    user_id: str = "",
) -> dict[str, Any]:
    """Get daily briefing — checkin-due Things and active sweep findings.

    Returns dict with 'date', 'checkin_items', 'findings', and 'total'.
    """
    import json as _json

    target = date.fromisoformat(as_of) if as_of else date.today()
    cutoff = datetime.combine(target, datetime.max.time()).isoformat()
    now = datetime.utcnow().isoformat()

    uf_sql, uf_params = user_filter(user_id)
    sf_uf_sql, sf_uf_params = user_filter(user_id, "sf")

    with db() as conn:
        # Things with checkin_date due today or earlier
        thing_rows = conn.execute(
            f"""SELECT * FROM things
               WHERE active = 1
                 AND checkin_date IS NOT NULL
                 AND checkin_date <= ?{uf_sql}
               ORDER BY checkin_date ASC, priority ASC""",
            [cutoff, *uf_params],
        ).fetchall()

        # Active (not dismissed, not expired, not snoozed) sweep findings
        finding_rows = conn.execute(
            f"""SELECT sf.*
               FROM sweep_findings sf
               WHERE sf.dismissed = 0
                 AND (sf.expires_at IS NULL OR sf.expires_at > ?)
                 AND (sf.snoozed_until IS NULL OR sf.snoozed_until <= ?){sf_uf_sql}
               ORDER BY sf.priority ASC, sf.created_at DESC""",
            [now, now, *sf_uf_params],
        ).fetchall()

    checkin_items = [dict(r) for r in thing_rows]
    findings = [dict(r) for r in finding_rows]

    return {
        "date": target.isoformat(),
        "checkin_items": checkin_items,
        "findings": findings,
        "total": len(checkin_items) + len(findings),
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
    return [dict(r) for r in rows]


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
