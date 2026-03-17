"""Sweep reasoning agent — runs the reasoning pipeline against the full graph.

Unlike the chat reasoning agent, the sweep agent:
- Processes the FULL graph of Things and relationships (not just relevant ones)
- Has restricted tools: create_thing, update_thing, create_relationship only
  (NO delete_thing, NO merge_things — guard rails)
- Uses a powerful model for deep analysis
- Generates sweep_findings for proposals that need user approval
- Runs per-user with logged runs
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from google.adk.agents import LlmAgent

from .agents import REQUESTY_REASONING_MODEL, UsageStats
from .context_agent import _make_litellm_model, _run_agent_for_text
from .database import db
from .vector_store import upsert_thing

logger = logging.getLogger(__name__)

# Entity type_hints that default to surface=false
_ENTITY_TYPES = {"person", "place", "event", "concept", "reference"}

# ---------------------------------------------------------------------------
# System prompt for sweep reasoning
# ---------------------------------------------------------------------------

SWEEP_AGENT_SYSTEM = """\
You are the Sweep Agent for Reli, an AI personal information manager.
You are running a scheduled background sweep of the user's full knowledge graph.
There is NO user message — you are analyzing the graph proactively.

Your job: examine all Things and their relationships to find opportunities for
improvement. Think like a thoughtful personal assistant reviewing someone's
life dashboard.

You have tools to modify the database:
- create_thing — create a new Thing (returns the created Thing with its ID)
- update_thing — update fields on an existing Thing
- create_relationship — create a typed link between two Things
- create_finding — propose something for the user's attention (shown in briefing)

IMPORTANT GUARD RAILS:
- You CANNOT delete Things. If something should be removed, create a finding
  suggesting it to the user.
- You CANNOT merge Things. If you spot duplicates, create a finding proposing
  the merge to the user.
- Only make changes you are CONFIDENT about. When in doubt, create a finding
  (proposal) instead of making a direct change.

What to look for:
1. **Missing relationships**: Things that should be linked but aren't
   (e.g., a person mentioned in a project's notes but not connected)
2. **Stale items**: Tasks or projects that haven't been updated and may
   need attention or archival
3. **Orphan Things**: Items with no connections that may need linking
4. **Missing context**: Things that would benefit from additional data
   fields or open_questions
5. **Completed work**: Projects where all children are done but project
   is still active
6. **Pattern insights**: Recurring themes, priorities that seem wrong,
   deadlines clustering
7. **Knowledge gaps**: Important open_questions that haven't been answered

When creating findings:
- finding_type should be "llm_insight"
- Write messages for the USER, not for a system
- Be warm, specific, and actionable
- Priority: 0=critical, 1=high, 2=medium, 3=low

After making all tool calls, output a JSON summary:
{
  "reasoning_summary": "Brief description of what you analyzed and changed.",
  "findings_count": <number>,
  "changes_count": <number>
}

Be conservative with direct changes. Prefer findings (proposals) for anything
the user should decide on. Direct changes are appropriate for:
- Adding obvious missing relationships
- Updating stale metadata
- Adding open_questions to Things that clearly need them
"""


# ---------------------------------------------------------------------------
# Tool factory — creates sweep-specific tools (restricted)
# ---------------------------------------------------------------------------


def _make_sweep_tools(
    user_id: str,
) -> tuple[list[Callable[..., Any]], dict[str, list[Any]]]:
    """Create sweep-specific tools bound to the given user context.

    Returns (tools_list, applied_changes_dict).  Only exposes safe operations:
    create_thing, update_thing, create_relationship, and create_finding.
    """
    applied: dict[str, list[Any]] = {
        "created": [],
        "updated": [],
        "relationships_created": [],
        "findings_created": [],
    }

    # ------------------------------------------------------------------
    def create_thing(
        title: str,
        type_hint: str = "",
        priority: int = 3,
        checkin_date: str = "",
        surface: bool = True,
        data_json: str = "{}",
        open_questions_json: str = "[]",
    ) -> dict[str, Any]:
        """Create a new Thing in the database.

        Args:
            title: The Thing's title (required).
            type_hint: Category — task, note, idea, project, goal, journal,
                       person, place, event, concept, reference.
            priority: 1 (highest) to 5 (lowest), default 3.
            checkin_date: ISO-8601 date string for check-in reminder, or empty.
            surface: Whether to show in sidebar. Entity types (person, place,
                     event, concept, reference) default to false.
            data_json: JSON string with arbitrary key-value data.
            open_questions_json: JSON string with list of knowledge-gap questions.

        Returns:
            The created Thing dict including its generated 'id'.
        """
        title = title.strip()
        if not title:
            return {"error": "title is required"}

        now = datetime.now(timezone.utc).isoformat()

        try:
            data = json.loads(data_json) if data_json else {}
        except json.JSONDecodeError:
            data = {}
        try:
            open_questions = json.loads(open_questions_json) if open_questions_json else []
        except json.JSONDecodeError:
            open_questions = []

        with db() as conn:
            # Deduplicate: if a Thing with the same title exists, skip
            existing = conn.execute(
                "SELECT id, title FROM things WHERE LOWER(title) = LOWER(?) AND active = 1 LIMIT 1",
                (title,),
            ).fetchone()
            if existing:
                return {"status": "already_exists", "id": existing["id"], "title": existing["title"]}

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
            row = conn.execute(
                "SELECT * FROM things WHERE id = ?", (thing_id,)
            ).fetchone()
            if row:
                row_dict = dict(row)
                applied["created"].append(row_dict)
                upsert_thing(row_dict)
                return row_dict
            return {"id": thing_id, "title": title}

    # ------------------------------------------------------------------
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
    ) -> dict[str, Any]:
        """Update an existing Thing's fields.

        Args:
            thing_id: UUID of the Thing to update (required).
            title: New title, or empty to keep current.
            active: Set to false to mark a task as done.
            checkin_date: New check-in date (ISO-8601), or empty to keep.
            priority: New priority (1-5), or null to keep.
            type_hint: New type_hint, or empty to keep.
            surface: New surface flag, or null to keep.
            data_json: JSON string with data fields to merge into existing data.
            open_questions_json: JSON string with updated open_questions list.

        Returns:
            The updated Thing dict, or an error dict.
        """
        thing_id = thing_id.strip()
        if not thing_id:
            return {"error": "thing_id is required"}

        now = datetime.now(timezone.utc).isoformat()

        with db() as conn:
            row = conn.execute(
                "SELECT * FROM things WHERE id = ?", (thing_id,)
            ).fetchone()
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
                except json.JSONDecodeError:
                    new_data = {}
                if new_data:
                    try:
                        old_data = (
                            json.loads(row["data"])
                            if isinstance(row["data"], str) and row["data"]
                            else {}
                        )
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

            updated_row = conn.execute(
                "SELECT * FROM things WHERE id = ?", (thing_id,)
            ).fetchone()
            if updated_row:
                row_dict = dict(updated_row)
                applied["updated"].append(row_dict)
                upsert_thing(row_dict)
                return row_dict
            return {"error": "update failed"}

    # ------------------------------------------------------------------
    def create_relationship(
        from_thing_id: str,
        to_thing_id: str,
        relationship_type: str,
    ) -> dict[str, Any]:
        """Create a typed relationship link between two Things.

        Args:
            from_thing_id: UUID of the source Thing.
            to_thing_id: UUID of the target Thing.
            relationship_type: The relationship type, e.g. "parent-of",
                               "depends-on", "involves", "related-to".

        Returns:
            The created relationship dict, or an error dict.
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

            from_row = conn.execute(
                "SELECT id FROM things WHERE id = ?", (from_id,)
            ).fetchone()
            to_row = conn.execute(
                "SELECT id FROM things WHERE id = ?", (to_id,)
            ).fetchone()
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
            rel_info = {
                "id": rel_id,
                "from_thing_id": from_id,
                "to_thing_id": to_id,
                "relationship_type": rel_type,
            }
            applied["relationships_created"].append(rel_info)
            return rel_info

    # ------------------------------------------------------------------
    def create_finding(
        message: str,
        priority: int = 2,
        thing_id: str = "",
        expires_in_days: int = 7,
    ) -> dict[str, Any]:
        """Create a sweep finding (proposal) for the user's attention.

        Use this when you want to SUGGEST an action rather than take it directly.
        Findings appear in the user's daily briefing.

        Args:
            message: Human-readable finding message for the user. Be warm and specific.
            priority: 0=critical, 1=high, 2=medium, 3=low.
            thing_id: UUID of a related Thing, or empty for general observations.
            expires_in_days: How long this finding stays relevant (1-30).

        Returns:
            The created finding dict.
        """
        message = message.strip()
        if not message:
            return {"error": "message is required"}

        now = datetime.now(timezone.utc)
        expires_in_days = max(1, min(30, expires_in_days))
        expires_at = (now + timedelta(days=expires_in_days)).isoformat()

        finding_id = f"sf-{uuid.uuid4().hex[:8]}"
        tid = thing_id.strip() if thing_id else None

        with db() as conn:
            # Validate thing_id if provided
            if tid:
                row = conn.execute("SELECT id FROM things WHERE id = ?", (tid,)).fetchone()
                if not row:
                    tid = None

            conn.execute(
                """INSERT INTO sweep_findings
                   (id, thing_id, finding_type, message, priority, dismissed,
                    created_at, expires_at, user_id)
                   VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)""",
                (finding_id, tid, "llm_insight", message, priority,
                 now.isoformat(), expires_at, user_id or None),
            )

        finding = {
            "id": finding_id,
            "thing_id": tid,
            "finding_type": "llm_insight",
            "message": message,
            "priority": priority,
            "expires_at": expires_at,
        }
        applied["findings_created"].append(finding)
        return finding

    tools = [create_thing, update_thing, create_relationship, create_finding]
    return tools, applied


# ---------------------------------------------------------------------------
# Graph loading
# ---------------------------------------------------------------------------


def _load_full_graph(user_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load all active Things and relationships for a user.

    Returns (things, relationships).
    """
    from .auth import user_filter

    uf_sql, uf_params = user_filter(user_id)

    with db() as conn:
        things_rows = conn.execute(
            f"SELECT * FROM things WHERE active = 1{uf_sql} ORDER BY updated_at DESC",
            uf_params,
        ).fetchall()
        things = [dict(row) for row in things_rows]

        # Get all relationships between active things
        thing_ids = {t["id"] for t in things}
        if thing_ids:
            placeholders = ",".join("?" for _ in thing_ids)
            rel_rows = conn.execute(
                f"""SELECT * FROM thing_relationships
                    WHERE from_thing_id IN ({placeholders})
                       OR to_thing_id IN ({placeholders})""",
                list(thing_ids) + list(thing_ids),
            ).fetchall()
            relationships = [dict(row) for row in rel_rows]
        else:
            relationships = []

    return things, relationships


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_sweep_agent(
    user_id: str,
    model: str | None = None,
    usage_stats: UsageStats | None = None,
) -> dict[str, Any]:
    """Run the sweep reasoning agent against the full graph for a user.

    Returns a dict with:
      - applied_changes: what was created/updated/proposed
      - reasoning_summary: agent's analysis summary
      - thing_count: how many Things were analyzed
      - relationship_count: how many relationships were in the graph
    """
    things, relationships = _load_full_graph(user_id)

    if not things:
        logger.info("Sweep agent: no active Things for user %s, skipping", user_id)
        return {
            "applied_changes": {"created": [], "updated": [], "relationships_created": [], "findings_created": []},
            "reasoning_summary": "No active Things to analyze.",
            "thing_count": 0,
            "relationship_count": 0,
        }

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d (%A)")

    # Format Things compactly for the prompt
    things_summary = []
    for t in things:
        entry: dict[str, Any] = {
            "id": t["id"],
            "title": t["title"],
            "type": t.get("type_hint", ""),
            "priority": t.get("priority", 3),
            "updated": t.get("updated_at", ""),
        }
        if t.get("checkin_date"):
            entry["checkin"] = t["checkin_date"]
        if t.get("data") and t["data"] != "{}":
            try:
                data = json.loads(t["data"]) if isinstance(t["data"], str) else t["data"]
                if data:
                    entry["data"] = data
            except (json.JSONDecodeError, TypeError):
                pass
        if t.get("open_questions") and t["open_questions"] != "[]":
            try:
                oq = json.loads(t["open_questions"]) if isinstance(t["open_questions"], str) else t["open_questions"]
                if oq:
                    entry["open_questions"] = oq
            except (json.JSONDecodeError, TypeError):
                pass
        if t.get("parent_id"):
            entry["parent_id"] = t["parent_id"]
        things_summary.append(entry)

    # Format relationships compactly
    rels_summary = []
    for r in relationships:
        rels_summary.append({
            "from": r["from_thing_id"],
            "to": r["to_thing_id"],
            "type": r["relationship_type"],
        })

    prompt = (
        f"Today's date: {today}\n\n"
        f"Full graph: {len(things)} Things, {len(relationships)} relationships.\n\n"
        f"Things:\n{json.dumps(things_summary, default=str)}\n\n"
        f"Relationships:\n{json.dumps(rels_summary, default=str)}"
    )

    tools, applied_changes = _make_sweep_tools(user_id)
    sweep_model = model or REQUESTY_REASONING_MODEL

    litellm_model = _make_litellm_model(model=sweep_model)

    agent = LlmAgent(
        name="sweep_agent",
        description="Analyzes the full knowledge graph and makes proactive improvements.",
        model=litellm_model,
        instruction=SWEEP_AGENT_SYSTEM,
        tools=tools,  # type: ignore[arg-type]
    )

    raw = await _run_agent_for_text(agent, prompt, usage_stats)
    logger.info("Sweep agent raw response: %s", raw[:500] if raw else raw)

    # Parse metadata
    try:
        metadata: dict[str, Any] = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        metadata = {}

    return {
        "applied_changes": applied_changes,
        "reasoning_summary": metadata.get("reasoning_summary", ""),
        "thing_count": len(things),
        "relationship_count": len(relationships),
    }
