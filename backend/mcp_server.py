"""Reli MCP server — knowledge graph tools wrapping the REST API.

Exposes Things, Relationships, briefing, conflict detection, and reli_think
reasoning-as-a-service as MCP tools.

Supports two transports:
- Streamable HTTP (primary): mounted at /mcp inside the FastAPI app.
  Protected by MCP_API_TOKEN bearer token.
- stdio (legacy): run via ``python -m backend.mcp_server`` for local clients.

Environment variables (stdio mode):
    RELI_API_URL   — Base URL of the Reli API (default: http://localhost:8000)
    RELI_API_TOKEN — JWT session token for authentication (required)
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RELI_API_URL = os.environ.get("RELI_API_URL", "http://localhost:8000")
RELI_API_TOKEN = os.environ.get("RELI_API_TOKEN", "")


def _base_url() -> str:
    return RELI_API_URL.rstrip("/")


def _cookies() -> dict[str, str]:
    if RELI_API_TOKEN:
        return {"reli_session": RELI_API_TOKEN}
    return {}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _make_client() -> httpx.Client:
    return httpx.Client(base_url=_base_url(), cookies=_cookies(), timeout=30.0)


def _api_get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET request to the Reli API. Returns parsed JSON or raises."""
    with _make_client() as client:
        resp = client.get(path, params=params)
        resp.raise_for_status()
        if resp.status_code == 204:
            return {"ok": True}
        return resp.json()


def _api_post(path: str, json_body: dict[str, Any] | None = None) -> Any:
    """POST request to the Reli API. Returns parsed JSON or raises."""
    with _make_client() as client:
        resp = client.post(path, json=json_body)
        resp.raise_for_status()
        if resp.status_code == 204:
            return {"ok": True}
        return resp.json()


def _api_patch(path: str, json_body: dict[str, Any]) -> Any:
    """PATCH request to the Reli API. Returns parsed JSON or raises."""
    with _make_client() as client:
        resp = client.patch(path, json=json_body)
        resp.raise_for_status()
        return resp.json()


def _api_delete(path: str) -> Any:
    """DELETE request to the Reli API. Returns success indicator."""
    with _make_client() as client:
        resp = client.delete(path)
        resp.raise_for_status()
        return {"ok": True}


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Reli",
    instructions=(
        "Reli is a personal knowledge graph. Use these tools to search, create, "
        "read, update, and delete Things (tasks, notes, projects, people, ideas, "
        "goals) and the typed relationships between them. "
        "Use get_preferences and update_preference to load and record the user's "
        "learned behavioral preferences at session start and end. "
        "Use get_briefing to see what needs attention today (checkin-due items and "
        "sweep findings). Use get_open_questions to find Things with unresolved "
        "knowledge gaps and ask the user proactively. "
        "Use get_conflicts to detect blockers, schedule overlaps, "
        "and deadline conflicts. "
        "Use the prompt resources (thing-creation, relationship-patterns, "
        "proactive-surfacing, pa-behavior) to learn how to act as a Reli-powered PA."
        "Use reli_think for AI-powered reasoning over complex natural language requests."
    ),
)


# ---------------------------------------------------------------------------
# CRUD + Search Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def search_things(
    query: str,
    active_only: bool = False,
    type_hint: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search Things by text query across titles, data, types, and relationships.

    Args:
        query: Free-text search query.
        active_only: If true, only return active (non-archived) Things.
        type_hint: Filter by type (e.g. 'task', 'project', 'person').
        limit: Maximum results to return (1-200, default 20).
    """
    params: dict[str, Any] = {"q": query, "limit": limit}
    if active_only:
        params["active_only"] = True
    if type_hint:
        params["type_hint"] = type_hint
    result: list[dict[str, Any]] = _api_get("/api/things/search", params=params)
    return result


@mcp.tool()
def get_thing(thing_id: str) -> dict[str, Any]:
    """Get a single Thing by its ID, including all fields.

    Args:
        thing_id: The UUID of the Thing to retrieve.
    """
    result: dict[str, Any] = _api_get(f"/api/things/{thing_id}")
    return result


@mcp.tool()
def create_thing(
    title: str,
    type_hint: str | None = None,
    data: dict[str, Any] | None = None,
    priority: int = 3,
    parent_id: str | None = None,
    checkin_date: str | None = None,
    active: bool = True,
    surface: bool = True,
    open_questions: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new Thing in the knowledge graph.

    Args:
        title: Short descriptive title (required).
        type_hint: Category like 'task', 'note', 'project', 'person', 'idea', 'goal', 'event', 'place', 'concept'.
        data: Arbitrary JSON data (e.g. {"email": "...", "birthday": "..."}).
        priority: 1 (highest) to 5 (lowest), default 3.
        parent_id: ID of a parent Thing for hierarchical nesting.
        checkin_date: ISO 8601 date when this Thing should surface in the briefing.
        active: Whether the Thing is active (true) or completed/archived (false).
        surface: Whether to show in default views.
        open_questions: List of unresolved questions about this Thing.
    """
    body: dict[str, Any] = {"title": title, "priority": priority, "active": active, "surface": surface}
    if type_hint is not None:
        body["type_hint"] = type_hint
    if data is not None:
        body["data"] = data
    if parent_id is not None:
        body["parent_id"] = parent_id
    if checkin_date is not None:
        body["checkin_date"] = checkin_date
    if open_questions is not None:
        body["open_questions"] = open_questions
    result: dict[str, Any] = _api_post("/api/things", json_body=body)
    return result


@mcp.tool()
def update_thing(
    thing_id: str,
    title: str | None = None,
    type_hint: str | None = None,
    data: dict[str, Any] | None = None,
    priority: int | None = None,
    parent_id: str | None = None,
    checkin_date: str | None = None,
    active: bool | None = None,
    surface: bool | None = None,
    open_questions: list[str] | None = None,
) -> dict[str, Any]:
    """Update an existing Thing. Only provided fields are changed.

    Args:
        thing_id: The UUID of the Thing to update.
        title: New title.
        type_hint: New category.
        data: New arbitrary JSON data (replaces existing data dict).
        priority: New priority (1-5).
        parent_id: New parent Thing ID.
        checkin_date: New checkin date (ISO 8601).
        active: Set active/archived status.
        surface: Set visibility in default views.
        open_questions: New list of unresolved questions.
    """
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if type_hint is not None:
        body["type_hint"] = type_hint
    if data is not None:
        body["data"] = data
    if priority is not None:
        body["priority"] = priority
    if parent_id is not None:
        body["parent_id"] = parent_id
    if checkin_date is not None:
        body["checkin_date"] = checkin_date
    if active is not None:
        body["active"] = active
    if surface is not None:
        body["surface"] = surface
    if open_questions is not None:
        body["open_questions"] = open_questions
    if not body:
        return {"error": "No fields provided to update"}
    result: dict[str, Any] = _api_patch(f"/api/things/{thing_id}", json_body=body)
    return result


@mcp.tool()
def delete_thing(thing_id: str) -> dict[str, Any]:
    """Soft-delete a Thing by marking it inactive (active=false).

    The Thing record is preserved in the knowledge graph — MCP clients cannot
    permanently destroy data. Returns the deactivated Thing so the client can
    confirm what was deleted.

    Args:
        thing_id: The UUID of the Thing to deactivate.
    """
    result: dict[str, Any] = _api_patch(f"/api/things/{thing_id}", json_body={"active": False})
    return result


@mcp.tool()
def merge_things(keep_id: str, remove_id: str) -> dict[str, Any]:
    """Merge two Things into one, removing the duplicate.

    Transfers all relationships from remove_id to keep_id, merges data dicts,
    re-parents children, records merge history, and updates the vector index.
    The remove_id Thing is permanently deleted; keep_id is the canonical record.

    Args:
        keep_id: UUID of the Thing to keep (the canonical record).
        remove_id: UUID of the Thing to merge into keep_id and remove.

    Returns:
        Dict with keep_id, remove_id, keep_title, remove_title.
    """
    result: dict[str, Any] = _api_post(
        "/api/things/merge",
        json_body={"keep_id": keep_id, "remove_id": remove_id},
    )
    return result


@mcp.tool()
def list_relationships(thing_id: str) -> list[dict[str, Any]]:
    """List all relationships where a Thing is source or target.

    Args:
        thing_id: The UUID of the Thing whose relationships to retrieve.
    """
    result: list[dict[str, Any]] = _api_get(f"/api/things/{thing_id}/relationships")
    return result


@mcp.tool()
def create_relationship(
    from_thing_id: str,
    to_thing_id: str,
    relationship_type: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a typed relationship (edge) between two Things.

    Args:
        from_thing_id: Source Thing UUID.
        to_thing_id: Target Thing UUID.
        relationship_type: Label like 'works_with', 'depends_on', 'related_to', 'belongs_to'.
        metadata: Optional JSON metadata for the relationship.
    """
    body: dict[str, Any] = {
        "from_thing_id": from_thing_id,
        "to_thing_id": to_thing_id,
        "relationship_type": relationship_type,
    }
    if metadata is not None:
        body["metadata"] = metadata
    result: dict[str, Any] = _api_post("/api/things/relationships", json_body=body)
    return result


@mcp.tool()
def delete_relationship(relationship_id: str) -> dict[str, Any]:
    """Delete a relationship between two Things.

    Args:
        relationship_id: The UUID of the relationship to delete.
    """
    result: dict[str, Any] = _api_delete(f"/api/things/relationships/{relationship_id}")
    return result


# ---------------------------------------------------------------------------
# Server-side intelligence tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_preferences() -> list[dict[str, Any]]:
    """Get all preference Things — the user's learned behavioral preferences.

    Returns Things with type_hint='preference'. Each preference Thing has a
    patterns array in its data field describing how the user wants the PA to
    behave (communication style, proactivity level, question frequency, etc.).

    Should be called at session start alongside get_user_profile to load the
    user's behavioral configuration.
    """
    result: list[dict[str, Any]] = _api_get("/api/things/preferences")
    return result


@mcp.tool()
def update_preference(
    thing_id: str,
    patterns: list[dict[str, Any]],
) -> dict[str, Any]:
    """Update the patterns array on a preference Thing.

    Replaces the patterns array in the Thing's data field without touching
    other fields. Use this to record behavioral signals observed during
    a conversation.

    Args:
        thing_id: UUID of the preference Thing to update.
        patterns: List of pattern dicts, each with:
            - pattern (str): Description of the observed preference pattern.
            - confidence (str): One of 'emerging' (1 obs), 'moderate' (2-3), 'strong' (4+).
            - observations (int): Number of times this pattern was observed.
    """
    result: dict[str, Any] = _api_patch(
        f"/api/things/{thing_id}/preferences",
        json_body={"patterns": patterns},
    )
    return result


@mcp.tool()
def get_briefing(as_of: str | None = None) -> dict[str, Any]:
    """Get today's daily briefing — checkin-due Things and active sweep findings.

    Returns items that need attention: Things with approaching checkin dates,
    stale items, open questions, and other sweep findings from Reli's
    server-side intelligence.

    Args:
        as_of: Optional ISO 8601 date (YYYY-MM-DD) to get the briefing for.
               Defaults to today.
    """
    params: dict[str, Any] = {}
    if as_of:
        params["as_of"] = as_of
    result: dict[str, Any] = _api_get("/api/briefing", params=params)
    return result


@mcp.tool()
def get_open_questions(limit: int = 50) -> list[dict[str, Any]]:
    """Get Things that have unresolved open questions, ordered by priority then recency.

    Returns active Things with non-empty open_questions arrays. The calling agent
    can use these to proactively ask the user clarifying questions during conversation.

    Args:
        limit: Maximum number of Things to return (1-200, default 50).
    """
    params: dict[str, Any] = {"limit": min(max(limit, 1), 200)}
    result: list[dict[str, Any]] = _api_get("/api/things/open-questions", params=params)
    return result


@mcp.tool()
def get_conflicts(window: int = 14) -> list[dict[str, Any]]:
    """Detect blockers, schedule overlaps, and deadline conflicts among Things.

    Scans the knowledge graph for real-time conflict alerts:
    - Blocking chains: Thing A blocks Thing B which has an approaching deadline.
    - Schedule overlaps: Two related Things with overlapping date ranges.
    - Deadline conflicts: A dependency's deadline is after the dependent's deadline.

    Args:
        window: Look-ahead window in days for deadline detection (1-90, default 14).
    """
    params: dict[str, Any] = {"window": min(max(window, 1), 90)}
    result: list[dict[str, Any]] = _api_get("/api/conflicts", params=params)
    return result


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# MCP Prompt Resources — PA behavior guidance for calling agents
# ---------------------------------------------------------------------------


@mcp.prompt(
    name="thing-creation",
    description=(
        "Guidance for creating Things in the Reli knowledge graph. "
        "Covers type hints, open questions, entity types, and best practices."
    ),
)
def thing_creation_guide() -> str:
    """How a calling agent should create Things in Reli."""
    return """\
# Thing Creation Guide

When the user mentions something worth tracking, create a Thing in Reli.

## Type Hints

Assign a `type_hint` to categorize each Thing:

| type_hint   | Use when                                    | surface default |
|-------------|---------------------------------------------|-----------------|
| task        | Actionable work item with a clear outcome   | true            |
| note        | Freeform information or observation          | true            |
| idea        | Something to explore or brainstorm           | true            |
| project     | Container for related tasks/notes            | true            |
| goal        | High-level objective (parent of tasks)       | true            |
| journal     | Reflective or diary-style entry              | true            |
| person      | A person the user interacts with             | false           |
| place       | A location                                   | false           |
| event       | A specific occurrence or meeting             | false           |
| concept     | An abstract idea or topic                    | false           |
| reference   | An external resource (URL, book, etc.)       | false           |

Entity types (person, place, event, concept, reference) default to `surface=false` \
— they exist in the knowledge graph for relationships but don't clutter default views. \
Set `surface=true` only for entities the user explicitly wants to track.

## Best Practices

- **Specific titles**: "Draft Q1 budget spreadsheet" not "Work on budget"
- **Open questions**: Include 1-3 knowledge gaps that would make the Thing more \
actionable. Examples: "What's the deadline?", "Who else is involved?", \
"What does success look like?"
- **Don't duplicate**: Before creating, search for existing Things that match. \
Update instead of creating duplicates.
- **Context in data**: When the user provides background info, store it in the \
`data` dict (e.g. `{"notes": "Mentioned during team standup", "email": "..."}`).
- **Priority**: 1 = highest urgency, 5 = lowest. Default to 3 unless the user \
indicates urgency.
- **Check-in dates**: Set `checkin_date` (ISO 8601) for Things that need to \
surface in the daily briefing at a specific time.
- **Hierarchies**: Use `parent_id` to nest tasks under projects or goals.

## Task Granularity

When a user creates a broad task (e.g. "plan my vacation"), don't just store it \
as-is. Ask clarifying questions to break it down into actionable sub-tasks. \
Store suggested breakdowns as `open_questions` on the Thing.

## Completing Things

When the user finishes a task ("done with X", "finished Y"), update it with \
`active=false`. Do NOT delete it — completed Things remain in the knowledge graph \
for history and patterns.
"""


@mcp.prompt(
    name="relationship-patterns",
    description=(
        "How to create and use typed relationships between Things. "
        "Covers relationship types, possessive patterns, and compound links."
    ),
)
def relationship_patterns_guide() -> str:
    """How a calling agent should link Things together."""
    return """\
# Relationship Patterns

Things in Reli form a knowledge graph connected by typed relationships.

## Relationship Types

| Category   | Types (with semantic opposites)                                        |
|------------|------------------------------------------------------------------------|
| Structural | parent-of / child-of, depends-on / blocks, part-of / contains         |
| Associative| related-to, involves, tagged-with                                      |
| Temporal   | followed-by / preceded-by, spawned-from / spawned                      |

Use the most specific type that fits. "related-to" is the fallback when nothing \
else applies.

## When to Create Relationships

Create relationships when the user's message implies a connection:
- "Meeting with Sarah about the budget project" → Sarah involves Budget Project
- "This task depends on the API redesign" → Task depends-on API Redesign
- "Add this note to Project X" → Note part-of Project X

## Possessive Patterns

When the user uses possessive language ("my sister", "my doctor"), treat it as \
an implicit relationship:

1. The user has a personal Thing in the database (their profile). Use it as the \
source for possessive relationships.
2. Search for an existing Thing matching the entity before creating a new one.
3. Create the relationship with the possessive role as the type (e.g. "sister", \
"doctor").
4. If the user provides a name ("my sister Alice"), use the name as the title \
and include the role in `data.notes`.

## Compound Possessives

"My sister's husband Bob" creates a chain:
1. Create "Sister" (type_hint: person, surface: false)
2. Create "Bob" (type_hint: person, surface: false, data: {"notes": "Sister's husband"})
3. Link user → Sister (relationship_type: "sister")
4. Link Sister → Bob (relationship_type: "husband")

## Merging Duplicates

If you recognize two Things refer to the same entity, merge them. Keep the one \
with more data, history, or relationships. If uncertain, ask the user first.
"""


@mcp.prompt(
    name="proactive-surfacing",
    description=(
        "Rules for proactively surfacing relevant Things to the user. "
        "Covers date-based triggers, context matching, and open questions."
    ),
)
def proactive_surfacing_guide() -> str:
    """When and how to proactively bring Things to the user's attention."""
    return """\
# Proactive Surfacing Rules

A good PA doesn't just respond to commands — it proactively surfaces relevant \
information at the right moment.

## Date-Based Surfacing

Things with dates in their `data` field automatically surface in the daily briefing:

**Recurring dates** (match month/day yearly):
- birthday, anniversary, born, date_of_birth, dob

**One-shot dates** (match exactly, future only):
- deadline, due_date, due, event_date, starts_at, start_date, ends_at, \
end_date, date

Store dates in ISO 8601 format in the Thing's `data` dict:
```json
{"birthday": "1990-03-15", "deadline": "2025-06-01"}
```

## Context-Based Surfacing

When the user's message references a topic, search for related Things and \
surface them:
- User mentions a person → surface that person's Thing and related items
- User discusses a project → surface its child tasks and status
- User asks "what's on my plate" → briefing mode, surface all active items

## Open Questions as Prompts

Things have an `open_questions` field — knowledge gaps that need answers. When \
you surface a Thing, check its open questions. If any are relevant to the current \
conversation, ask them naturally.

When the user answers an open question, update the Thing: remove the question \
from `open_questions` and store the answer in `data`.

## Contradiction Detection

If the user says something that conflicts with existing Thing data (e.g. a new \
deadline that conflicts with another Thing's date), flag it. Do NOT silently \
overwrite — let the user confirm which is correct.

## Briefing Mode

When the user asks "how are things?", "what's on my plate?", or similar:
- Surface all active Things with approaching check-in dates
- Lead with what's urgent or exciting
- Frame items as opportunities, not obligations
- Group by project or priority for clarity
"""


@mcp.prompt(
    name="pa-behavior",
    description=(
        "Complete PA behavior guide combining all patterns: thing creation, "
        "relationships, proactive surfacing, and interaction style. "
        "Use this as the primary reference for acting as a Reli-powered PA."
    ),
)
def pa_behavior_guide() -> str:
    """Comprehensive guide for acting as a personal assistant using Reli."""
    return """\
# Reli PA Behavior Guide

You are acting as a personal assistant powered by Reli, a structured knowledge \
graph. Your role is to help the user manage their life by tracking Things \
(tasks, people, projects, notes, events) and the relationships between them.

## Core Principles

1. **Things as State**: Your knowledge comes from the Reli database. Don't \
invent or assume information not stored in Things.
2. **Search Before Creating**: Always check if a Thing already exists before \
creating a new one. Duplicates degrade the knowledge graph.
3. **Context First**: When discussing a Thing, briefly summarize what you know \
(title, type, priority, check-in date, notes) so the user has context.
4. **One Question at a Time**: If you need clarification, ask one focused \
question per response.
5. **Strict Grounding**: Only mention changes that actually occurred. Never \
hallucinate Things or changes that don't exist in the database.

## When the User Mentions Something

1. **Search** for relevant existing Things using `search_things`
2. **If found**: Reference the existing Thing, update if the user provided new info
3. **If not found**: Create a new Thing with an appropriate type_hint
4. **Link**: Create relationships to connect the new/existing Thing to related items

## Type Hint Quick Reference

- Tasks, notes, ideas, projects, goals, journals → `surface=true` (user tracks these)
- People, places, events, concepts, references → `surface=false` (graph entities)

## Relationship Quick Reference

- Structural: parent-of/child-of, depends-on/blocks, part-of/contains
- Associative: related-to, involves, tagged-with
- Temporal: followed-by/preceded-by, spawned-from/spawned
- Possessive: Use the role as type (sister, doctor, manager, etc.)

## Open Questions

Every Thing can have `open_questions` — knowledge gaps. When creating or \
updating Things:
- Add 1-3 relevant questions that would make the Thing more actionable
- Don't ask questions whose answers are already in the Thing's data
- When the user answers a question, remove it and store the answer

## Proactive Behaviors

- Surface Things with approaching dates (deadlines, birthdays, check-ins)
- When the user mentions a person/project, surface related context
- Detect contradictions between user statements and stored data
- Notice patterns (deferred tasks, missing deadlines) and gently flag them
- In briefing mode, lead with urgent/exciting items

## Personality & Interaction Style

The default personality is warm, proactive, and supportive (think "highly \
competent executive assistant"). Key defaults:

- Brief responses (1-3 sentences) with warmth
- Celebrate task completion enthusiastically
- Guide users to break broad tasks into actionable steps
- Ask clarifying questions when tasks are vague
- Nudge about deferred or approaching items proactively

These defaults are **overridable** by learned user preferences. If the user's \
stored preference Things indicate a different style (e.g. "concise, no emoji, \
factual"), honor those preferences over the defaults.

**Resolution order** (highest wins):
1. Explicit user correction in current session
2. Learned preferences with confidence "strong"
3. Learned preferences with confidence "moderate" or "emerging"
4. Default personality (warm, proactive, supportive)
5. Fixed constraints (always active: grounding, no hallucination, one question)

## Completing Work

- When a task is done: `update_thing(id, active=false)` — don't delete
- Celebrate completions with personality
- After completing, suggest what to tackle next based on priorities

## Data Model Reference

A Thing has:
- `title` (string) — short descriptive name
- `type_hint` (string) — category for filtering and display
- `data` (object) — arbitrary JSON for custom fields, notes, dates
- `priority` (1-5) — urgency ranking
- `active` (bool) — true=active, false=completed/archived
- `surface` (bool) — show in default UI views
- `parent_id` (string?) — hierarchical nesting
- `checkin_date` (ISO 8601?) — when to surface in briefing
- `open_questions` (string[]?) — knowledge gaps

A Relationship has:
- `from_thing_id`, `to_thing_id` — the connected Things
- `relationship_type` — label describing the connection
- `metadata` (object?) — optional extra data about the link
"""


@mcp.prompt(
    name="thing-schema",
    description=(
        "Complete reference for the Reli Thing data model: all fields, valid values, "
        "type hints, relationship naming conventions, open_questions, and preference "
        "confidence tracking. Use this to understand what data to store and how."
    ),
)
def thing_schema_reference() -> str:
    """Detailed data model reference for Things and Relationships in Reli."""
    return """\
# Reli Thing Schema Reference

## Thing Fields

| Field          | Type            | Default | Description                                    |
|----------------|-----------------|---------|------------------------------------------------|
| id             | string (UUID)   | auto    | Unique identifier                              |
| title          | string          | —       | Short descriptive name (1–500 chars, required) |
| type_hint      | string or null  | null    | Category for filtering and display             |
| parent_id      | string or null  | null    | Parent Thing UUID for hierarchical nesting     |
| checkin_date   | ISO 8601 or null| null    | When to surface this Thing in the daily briefing |
| priority       | int (1–5)       | 3       | 1 = highest urgency, 5 = lowest                |
| active         | bool            | true    | false = completed/archived (never hard-delete) |
| surface        | bool            | true    | false = graph entity, hide from default views  |
| data           | object or null  | null    | Arbitrary JSON for custom fields and notes     |
| open_questions | string[] or null| null    | Unresolved knowledge gaps about this Thing     |
| created_at     | ISO 8601        | auto    | Creation timestamp                             |
| updated_at     | ISO 8601        | auto    | Last-modified timestamp                        |

## Type Hints

| type_hint   | Meaning                                            | surface default |
|-------------|---------------------------------------------------|-----------------|
| task        | Actionable work item with a clear outcome          | true            |
| note        | Freeform information or observation                | true            |
| idea        | Something to explore or brainstorm                 | true            |
| project     | Container for related tasks and notes              | true            |
| goal        | High-level objective (parent of tasks)             | true            |
| journal     | Reflective or diary-style entry                    | true            |
| preference  | Learned user preference pattern (see below)        | false           |
| person      | A person the user interacts with                   | false           |
| place       | A physical or virtual location                     | false           |
| event       | A specific occurrence or meeting                   | false           |
| concept     | An abstract idea or recurring topic                | false           |
| reference   | An external resource (URL, book, document, etc.)   | false           |

Entity types (person, place, event, concept, reference, preference) default to \
`surface=false` — they exist in the knowledge graph but don't clutter default views.

## Relationship Types

| Category    | Types                                                         |
|-------------|---------------------------------------------------------------|
| Structural  | parent-of / child-of, depends-on / blocks, part-of / contains |
| Associative | related-to, involves, tagged-with                             |
| Temporal    | followed-by / preceded-by, spawned-from / spawned             |
| Possessive  | Use the role as type (sister, doctor, manager, colleague, etc.) |

Relationships are directed: `from_thing_id` → `to_thing_id` with a `relationship_type` label. \
Prefer semantic opposites (parent-of/child-of) over creating both directions.

## open_questions

`open_questions` is an array of strings representing knowledge gaps:

- Add 1–3 questions when creating a Thing if important context is missing
- Example: `["What is the deadline?", "Who else is involved?"]`
- When the user answers a question, remove it from the array and store the \
answer in `data`
- Do NOT re-ask questions whose answers are already in `data`

## Preference Things and Confidence Tracking

Personality preferences are stored as `type_hint: "preference"` Things. \
The `data` field holds a `patterns` array:

```json
{
  "title": "How the user wants Reli to communicate",
  "type_hint": "preference",
  "surface": false,
  "data": {
    "patterns": [
      {
        "pattern": "Prefers concise responses",
        "confidence": "strong",
        "observations": 12,
        "last_observed": "2025-06-01"
      }
    ]
  }
}
```

**Confidence levels** (based on observation count):
- `emerging` — 1 observation (tentative signal, may be noise)
- `moderate` — 2–3 observations (consistent pattern)
- `strong` — 4+ observations (reliable, override defaults)

**Resolution order** (highest wins):
1. Explicit user correction in current session
2. Strong confidence preferences
3. Moderate / emerging preferences
4. Default personality (warm, proactive, supportive)
5. Fixed constraints (grounding, no hallucination, one question at a time)

## Well-Formed Thing Examples

### Task
```json
{
  "title": "Draft Q1 budget spreadsheet",
  "type_hint": "task",
  "priority": 2,
  "checkin_date": "2025-03-31",
  "data": {"notes": "Due before board meeting"},
  "open_questions": ["Who needs to review it before submission?"]
}
```

### Person
```json
{
  "title": "Alice Chen",
  "type_hint": "person",
  "surface": false,
  "data": {"email": "alice@example.com", "notes": "Engineering manager, met at AWS re:Invent"},
  "open_questions": ["What team does she manage?"]
}
```

### Project
```json
{
  "title": "Website Redesign",
  "type_hint": "project",
  "priority": 1,
  "data": {"deadline": "2025-09-01", "stakeholder": "Marketing team"}
}
```

### Preference
```json
{
  "title": "How Alex wants Reli to communicate",
  "type_hint": "preference",
  "surface": false,
  "data": {
    "patterns": [
      {"pattern": "No emoji", "confidence": "strong", "observations": 5},
      {"pattern": "Bullet points over prose", "confidence": "moderate", "observations": 3}
    ]
  }
}
```

### Event
```json
{
  "title": "Q2 Planning Offsite",
  "type_hint": "event",
  "surface": false,
  "data": {"event_date": "2025-04-15", "location": "San Francisco", "attendees": "Leadership team"}
}
```

## Naming Conventions

- **Titles**: Specific and descriptive ("Draft Q1 budget" not "Work on budget")
- **Relationship types**: Lowercase hyphen-separated ("depends-on", "parent-of")
- **Data keys**: snake_case (e.g. `due_date`, `event_date`, `last_contacted`)
- **Dates in data**: ISO 8601 format (`YYYY-MM-DD`) for date-based surfacing to work
"""


# ---------------------------------------------------------------------------
# Reasoning-as-a-service: reli_think
# ---------------------------------------------------------------------------


@mcp.tool()
def reli_think(
    message: str,
    context: str | None = None,
) -> dict[str, Any]:
    """Analyze a natural language message and return structured instructions.

    This is reasoning-as-a-service: send natural language describing what
    the user wants, and get back structured instructions for what to
    create, update, delete, or link in the knowledge graph. You then
    execute those instructions using the CRUD tools above.

    This is useful when:
    - The user's request is complex (multiple entities, relationships)
    - You want AI-powered analysis of what changes are needed
    - You're unsure how to map natural language to CRUD operations

    The returned instructions use the same parameter names as the CRUD
    tools, so you can execute them directly.

    Args:
        message: Natural language message to analyze (e.g. "I'm meeting
            Tom for coffee next Tuesday at Blue Bottle").
        context: Optional additional context to help reasoning (e.g.
            recently discussed topics, user preferences).

    Returns:
        Dict with:
        - instructions: list of {action, params, ref?} dicts
        - questions_for_user: clarifying questions if intent is ambiguous
        - reasoning_summary: explanation of the reasoning
        - context: Things found during analysis
    """
    body: dict[str, Any] = {"message": message}
    if context:
        body["context"] = context
    result: dict[str, Any] = _api_post("/api/think", json_body=body)
    return result


# ---------------------------------------------------------------------------
# Streamable HTTP transport (for mounting inside FastAPI)
# ---------------------------------------------------------------------------


class _TokenAuthMiddleware:
    """ASGI middleware that enforces Bearer token authentication on /mcp.

    Accepts two token forms:
    1. Static API token (``MCP_API_TOKEN``) — legacy; compared as-is.
    2. JWT issued by the OAuth flow — validated via ``jwt.decode``.

    If neither ``MCP_API_TOKEN`` nor ``SECRET_KEY`` is configured, all requests
    are allowed (dev mode).
    """

    def __init__(self, app: ASGIApp, mcp_api_token: str) -> None:
        self._app = app
        self._static_token = mcp_api_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        from .config import settings as _settings

        secret_key = _settings.SECRET_KEY
        static_token = self._static_token

        # Dev mode: no auth configured
        if not static_token and not secret_key:
            await self._app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()

        authorized = False

        if auth_header.startswith("Bearer "):
            provided = auth_header[7:]

            # 1. Static token match (legacy / backward compat)
            if static_token and provided == static_token:
                authorized = True

            # 2. JWT validation (OAuth flow)
            if not authorized and secret_key:
                try:
                    import jwt as _jwt

                    _jwt.decode(provided, secret_key, algorithms=["HS256"])
                    authorized = True
                except Exception:
                    pass

        if not authorized:
            response = Response(
                content='{"detail":"Unauthorized"}',
                status_code=401,
                media_type="application/json",
                headers={"WWW-Authenticate": 'Bearer realm="reli"'},
            )
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)


def create_mcp_asgi_app(mcp_api_token: str = "") -> ASGIApp:
    """Return the MCP Streamable HTTP ASGI app, wrapped with token auth.

    Mount this at ``/mcp`` in the FastAPI app:

        from backend.mcp_server import create_mcp_asgi_app
        app.mount("/mcp", create_mcp_asgi_app(settings.MCP_API_TOKEN))

    Args:
        mcp_api_token: Required Bearer token. Empty string disables auth (dev mode).
    """
    starlette_app = mcp.streamable_http_app()
    return _TokenAuthMiddleware(starlette_app, mcp_api_token)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server over stdio."""
    if not RELI_API_TOKEN:
        print("Warning: RELI_API_TOKEN not set. Auth will be skipped if server has no SECRET_KEY.", file=sys.stderr)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
