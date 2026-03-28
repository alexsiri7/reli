"""Shared tool implementations for Reli agents and MCP server.

Provides the core DB-level operations used by both the reasoning agent
(inline tool calling) and the MCP server (exposed as @mcp.tool() functions).

Design principles:
- All functions take ``user_id`` as an explicit parameter (no closures).
- No side-effect tracking — callers handle their own accounting
  (e.g. ``applied_changes`` in the reasoning agent).
- ``chat_history_tool`` accepts an optional ``session_id``; when omitted it
  searches across ALL of the user's sessions (suitable for MCP clients).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from .database import db
from .vector_store import delete_thing as vs_delete
from .vector_store import upsert_thing

logger = logging.getLogger(__name__)

# Entity type_hints that default to surface=false
ENTITY_TYPES: frozenset[str] = frozenset({"person", "place", "event", "concept", "reference", "preference"})


# ---------------------------------------------------------------------------
# fetch_context
# ---------------------------------------------------------------------------


def fetch_context(
    user_id: str,
    search_queries: list[str],
    fetch_ids: list[str],
    active_only: bool = True,
    type_hint: str | None = None,
) -> dict[str, Any]:
    """Search the Things database for relevant context.

    Returns a dict with ``things``, ``relationships``, and ``count``.
    Updates ``last_referenced`` on matched Things.
    """
    from .pipeline import _fetch_relevant_things, _fetch_with_family

    if not search_queries and not fetch_ids:
        return {"things": [], "relationships": [], "count": 0}

    filter_params: dict[str, Any] = {"active_only": active_only, "type_hint": type_hint}

    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []

    with db() as conn:
        if search_queries:
            things = _fetch_relevant_things(conn, search_queries, filter_params, user_id=user_id)
            for t in things:
                if t["id"] not in seen_ids:
                    seen_ids.add(t["id"])
                    results.append(t)

        if fetch_ids:
            id_things = _fetch_with_family(conn, [tid for tid in fetch_ids if tid not in seen_ids])
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

    return {"things": results, "relationships": relationships, "count": len(results)}


# ---------------------------------------------------------------------------
# chat_history_tool
# ---------------------------------------------------------------------------


def chat_history_tool(
    n: int = 10,
    search_query: str = "",
    session_id: str = "",
    user_id: str = "",
) -> dict[str, Any]:
    """Retrieve chat history messages.

    When ``session_id`` is provided, returns messages from that session only
    (agent behaviour).  When omitted (or empty), searches across ALL sessions
    owned by ``user_id`` (MCP behaviour).

    Returns a dict with ``messages`` (list of {role, content, timestamp})
    and ``count``.
    """
    n = max(1, min(n, 50))

    with db() as conn:
        if session_id:
            # Session-scoped (reasoning agent)
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
        else:
            # Cross-session (MCP)
            if search_query and search_query.strip():
                if user_id:
                    rows = conn.execute(
                        "SELECT role, content, timestamp FROM chat_history"
                        " WHERE (user_id = ? OR user_id IS NULL)"
                        " AND content LIKE ?"
                        " ORDER BY id DESC LIMIT ?",
                        (user_id, f"%{search_query.strip()}%", n),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT role, content, timestamp FROM chat_history"
                        " WHERE content LIKE ?"
                        " ORDER BY id DESC LIMIT ?",
                        (f"%{search_query.strip()}%", n),
                    ).fetchall()
            else:
                if user_id:
                    rows = conn.execute(
                        "SELECT role, content, timestamp FROM chat_history"
                        " WHERE (user_id = ? OR user_id IS NULL)"
                        " ORDER BY id DESC LIMIT ?",
                        (user_id, n),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT role, content, timestamp FROM chat_history"
                        " ORDER BY id DESC LIMIT ?",
                        (n,),
                    ).fetchall()

    messages = [
        {"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]}
        for r in reversed(rows)
    ]
    return {"messages": messages, "count": len(messages)}


# ---------------------------------------------------------------------------
# create_thing
# ---------------------------------------------------------------------------


def create_thing(
    user_id: str,
    title: str,
    type_hint: str = "",
    priority: int = 3,
    checkin_date: str = "",
    surface: bool = True,
    data_json: str = "{}",
    open_questions_json: str = "[]",
) -> dict[str, Any]:
    """Create a new Thing in the database, with deduplication.

    Returns the created (or updated-on-dedup) Thing dict.
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
        existing = conn.execute(
            "SELECT * FROM things WHERE LOWER(title) = LOWER(?) AND active = 1 LIMIT 1",
            (title,),
        ).fetchone()

        if existing:
            logger.info("Dedup: converting create for '%s' into update on %s", title, existing["id"])
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
                merge_fields["data"] = json.dumps({**old, **data})
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
                upsert_thing(row_dict)
                # Internal marker so callers can distinguish dedup-update from fresh create.
                # Strip this before returning to the AI.
                row_dict["_was_dedup"] = True
                return row_dict
            return {"id": existing["id"], "title": title, "deduplicated": True, "_was_dedup": True}

        thing_id = str(uuid.uuid4())
        data_str = json.dumps(data) if isinstance(data, dict) else str(data)
        effective_surface = surface
        if type_hint in ENTITY_TYPES:
            effective_surface = False
        oq_json = json.dumps(open_questions) if open_questions else None

        conn.execute(
            """INSERT INTO things
               (id, title, type_hint, parent_id, checkin_date, priority,
                active, surface, data, open_questions, created_at,
                updated_at, user_id)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)""",
            (
                thing_id, title, type_hint or None, None,
                checkin_date or None, priority, int(effective_surface),
                data_str, oq_json, now, now, user_id or None,
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
    user_id: str,
    thing_id: str,
    title: str = "",
    active: bool | None = None,
    checkin_date: str = "",
    priority: int | None = None,
    type_hint: str = "",
    surface: bool | None = None,
    data_json: str = "",
    open_questions_json: str = "",
) -> dict[str, Any]:
    """Update an existing Thing's fields.

    Returns the updated Thing dict or an error dict.
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
                fields["data"] = json.dumps({**old_data, **new_data})
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


def delete_thing(user_id: str, thing_id: str) -> dict[str, Any]:
    """Hard-delete a Thing by ID.

    Returns a confirmation dict ``{"deleted": thing_id, "title": title}``.
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
    user_id: str,
    keep_id: str,
    remove_id: str,
    merged_data_json: str = "{}",
) -> dict[str, Any]:
    """Merge a duplicate Thing into a primary Thing.

    Transfers relationships, consolidates data and open_questions, deletes
    the duplicate, records merge history.
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

        mf: dict[str, Any] = {}
        try:
            old_data = (
                json.loads(keep_row["data"]) if isinstance(keep_row["data"], str) and keep_row["data"] else {}
            )
        except (ValueError, TypeError):
            old_data = {}
        if merged_data or old_data:
            mf["data"] = json.dumps({**old_data, **merged_data})

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

        conn.execute("DELETE FROM things WHERE id = ?", (remove_id,))
        vs_delete(remove_id)

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
                str(uuid.uuid4()), keep_id, remove_id,
                keep_row["title"], remove_row["title"],
                json.dumps(_merged_snapshot) if _merged_snapshot else None,
                "agent", user_id or None, now,
            ),
        )

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
) -> dict[str, Any]:
    """Create a typed relationship link between two Things.

    Returns the created relationship dict or an error/duplicate dict.
    """
    from_id = from_thing_id.strip()
    to_id = to_thing_id.strip()
    rel_type = relationship_type.strip()
    if not from_id or not to_id or not rel_type:
        return {"error": "from_thing_id, to_thing_id, and relationship_type are required"}
    if from_id == to_id:
        return {"error": "cannot create self-referential relationship"}

    with db() as conn:
        dup = conn.execute(
            "SELECT id FROM thing_relationships"
            " WHERE from_thing_id = ? AND to_thing_id = ? AND relationship_type = ? LIMIT 1",
            (from_id, to_id, rel_type),
        ).fetchone()
        if dup:
            return {"status": "duplicate", "relationship_type": rel_type}

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
