"""Reli MCP server — CRUD + search tools and PA behavior prompts.

Exposes Things and Relationships as MCP tools over stdio transport,
plus PA behavior prompts as MCP prompt resources that teach calling
agents how to act as a personal assistant using the Reli knowledge graph.

Usage:
    RELI_API_URL=http://localhost:8000 RELI_API_TOKEN=<jwt> python -m backend.mcp_server

Environment variables:
    RELI_API_URL   — Base URL of the Reli API (default: http://localhost:8000)
    RELI_API_TOKEN — JWT session token for authentication (required)
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

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
        "goals) and the typed relationships between them."
    ),
)


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
    """Delete a Thing from the knowledge graph.

    Args:
        thing_id: The UUID of the Thing to delete.
    """
    result: dict[str, Any] = _api_delete(f"/api/things/{thing_id}")
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
# MCP Prompt Resources — PA behavior patterns
# ---------------------------------------------------------------------------


@mcp.prompt()
def thing_creation_guidance() -> str:
    """How to create Things effectively in the Reli knowledge graph.

    Teaches the calling agent best practices for creating Things: choosing
    type_hints, writing actionable titles, setting priorities, using
    open_questions for knowledge gaps, and handling entity types.
    """
    return """\
# Thing Creation Guidance for Reli

You are working with Reli, a personal knowledge graph. When the user mentions
something worth remembering, create a Thing. Here's how to do it well.

## Type Hints

Choose the right type_hint for each Thing:

| type_hint   | Use for                                      | surface default |
|-------------|----------------------------------------------|-----------------|
| task        | Actionable items with a deliverable           | true            |
| note        | Information to remember                       | true            |
| idea        | Concepts to explore later                     | true            |
| project     | Multi-step initiatives                        | true            |
| goal        | High-level objectives                         | true            |
| journal     | Reflections and diary entries                 | true            |
| person      | People the user interacts with                | false           |
| place       | Locations                                     | false           |
| event       | Specific occurrences with dates               | false           |
| concept     | Abstract ideas or frameworks                  | false           |
| reference   | External resources (links, docs, specs)       | false           |

Entity types (person, place, event, concept, reference) default to surface=false
— they exist in the knowledge graph but don't clutter the user's default views.
Set surface=true only when the user explicitly wants to track the entity.

## Writing Good Titles

Prefer specific, actionable titles over vague ones:
- GOOD: "Draft Q1 budget spreadsheet"
- BAD:  "Work on budget"
- GOOD: "Book flights to Tokyo for March trip"
- BAD:  "Travel stuff"

## Task Granularity

If a task seems broad (multiple distinct steps), don't create one large item.
Instead, ask the user to break it down:
- "That's a great goal! What's the very first small piece we can bite off?"
- "What will tell us this part is done?"

## Open Questions

When creating a Thing, generate 1-3 open_questions — knowledge gaps that would
make the Thing more actionable:
- "What's the deadline for this?"
- "Who else is involved?"
- "What does success look like?"

Tailor questions to the Thing's type and context. Don't ask questions whose
answers are already in the Thing's data or title.

## Priority Scale

- 1: Highest priority (urgent/critical)
- 2: High (important, do soon)
- 3: Medium (default)
- 4: Low (nice to have)
- 5: Lowest (someday/maybe)

## Data Field

Use the data dict for structured information:
```json
{
  "notes": "Context about the thing",
  "email": "person@example.com",
  "birthday": "1990-05-15",
  "location": "San Francisco"
}
```

## Completing Things

When a task is done, update it with active=false. Note what was accomplished.
Don't delete completed tasks — archiving preserves history.

## Deduplication

ALWAYS search before creating. If a Thing already exists, update it instead.
"""


@mcp.prompt()
def relationship_patterns() -> str:
    """How to create and manage relationships between Things in Reli.

    Teaches the calling agent about relationship types, possessive language
    patterns, compound possessives, and deduplication rules.
    """
    return """\
# Relationship Patterns for Reli

Things in Reli form a knowledge graph connected by typed relationships.
When the user describes connections between concepts, people, or items,
create relationships to capture that structure.

## Relationship Types

### Structural (hierarchical)
- "parent-of" ↔ "child-of" — hierarchy (project → subtask)
- "depends-on" ↔ "blocks" — dependencies (task A needs task B)
- "part-of" ↔ "contains" — composition (chapter is part-of book)

### Associative
- "related-to" — general association
- "involves" — participation (meeting involves person)
- "tagged-with" — categorization

### Temporal
- "followed-by" ↔ "preceded-by" — sequence
- "spawned-from" ↔ "spawned" — origin/derivation

## Possessive Patterns

When the user uses possessive language ("my sister", "my doctor", "my project
manager"), treat this as an implicit relationship declaration:

1. Search for an existing Thing matching the referenced entity
2. If not found, create one (type_hint inferred from context, surface=false)
3. Create a relationship from the user to the entity using the role as the type

### Examples

| User says               | Thing created                           | Relationship type |
|-------------------------|-----------------------------------------|-------------------|
| "my sister Alice"       | Alice (person, surface=false)           | sister            |
| "my dentist Dr. Park"   | Dr. Park (person, surface=false)        | dentist           |
| "my project Helios"     | Helios (project, surface=true)          | owner_of          |
| "my friend at Google"   | Friend at Google (person, surface=false) | friend           |

Use the natural role name as the relationship_type (sister, doctor, friend,
dentist, manager, colleague, partner, landlord, therapist, etc.), not a
generic type like "related-to".

## Compound Possessives

When the user chains possessives ("my sister's husband Bob"), create each
entity and link them in sequence:

- "my sister's husband Bob" →
  1. Create "Sister" (person) — relationship: user → Sister (type: sister)
  2. Create "Bob" (person) — relationship: Sister → Bob (type: husband)

If an entity in the chain already exists, reuse it to avoid duplicates.

## Deduplication

Before creating entities for relationships:
1. Search existing Things for matches (by name, type, role)
2. Check if the user already has a relationship of the same type
3. Reuse existing entities rather than creating duplicates

## Best Practices

- When the user mentions a person in passing, create the entity with
  surface=false — it lives in the graph but doesn't clutter their view
- Include context in data.notes (e.g. "User's sister", "Met at conference")
- Use ISO-8601 for any dates in relationship metadata
"""


@mcp.prompt()
def type_hint_reference() -> str:
    """Complete reference for type_hint values and their semantics in Reli.

    Explains each type_hint, when to use it, default behaviors, and how
    type_hints affect Thing handling.
    """
    return """\
# Type Hint Reference for Reli

Every Thing in Reli has an optional type_hint that determines how it's
categorized, displayed, and handled.

## Work Items (surface=true by default)

### task
Actionable items with a clear deliverable. Has a start, an end, and a
definition of done. Prefer specific titles ("Draft Q1 report" not "Work
on report"). When completed, set active=false.

### note
Information worth remembering that isn't actionable. Meeting notes,
observations, facts. Use data.notes for the content.

### idea
Concepts to explore later. Less defined than a task, more of a seed.
May evolve into tasks or projects.

### project
Multi-step initiatives containing subtasks. Use parent-of/child-of
relationships to link subtasks. Projects are high-level containers.

### goal
High-level objectives that tasks and projects serve. "Get promoted",
"Launch product by Q2". Track progress through linked tasks.

### journal
Personal reflections and diary entries. Typically time-stamped.
Great for capturing thoughts, feelings, and daily observations.

## Entity Types (surface=false by default)

Entity types exist in the knowledge graph to provide structure and
context, but don't appear in the user's default task/item views.

### person
People the user interacts with. Store contact info, roles, and
relationships in data. Examples: "Sarah Chen", "Dr. Rodriguez".

### place
Physical or virtual locations. Store address, coordinates, or
other location data. Examples: "Office HQ", "Tokyo", "Zoom Room 3".

### event
Specific occurrences with dates. Birthdays, meetings, deadlines,
conferences. Store dates in data for proactive surfacing.

### concept
Abstract ideas, frameworks, methodologies. "Microservices migration",
"OKR framework", "Inbox Zero". Useful for tagging and knowledge mapping.

### reference
External resources — documents, URLs, specs, books. Store links in
data. Examples: "RFC 2616", "Design spec v2", "Team handbook".

## Special Type

### preference
System-managed. Stores learned personality preferences about how the
user wants Reli to behave. Do NOT create these manually — the system
learns them from interaction patterns.

## How Type Hints Affect Behavior

- **Default surface value**: Work items default to true, entities to false
- **Search ranking**: Type hints improve search relevance filtering
- **Proactive surfacing**: Events with dates in data trigger reminders
- **Deduplication**: Entity types are deduplicated by name within type
- **Relationship inference**: Possessive language creates entity Things
  with appropriate type_hints automatically
"""


@mcp.prompt()
def proactive_surfacing_rules() -> str:
    """Rules for proactively surfacing relevant Things based on context.

    Teaches the calling agent when and how to proactively mention Things
    from the knowledge graph that are relevant to the current conversation,
    including date-based surfacing and contextual relevance.
    """
    return """\
# Proactive Surfacing Rules for Reli

As a personal assistant using Reli, you should proactively surface relevant
Things from the knowledge graph when they're contextually useful. Don't wait
for the user to ask — anticipate what they need to know.

## Date-Based Surfacing

Things with dates in their data dict are candidates for proactive surfacing.
Check for these date keys:

### Recurring dates (birthdays, anniversaries)
Keys: birthday, anniversary, born, date_of_birth, dob
- These recur annually — match on month and day, ignore year
- Surface within 7 days: "Sarah's birthday is in 3 days!"
- Surface on the day: "It's Tom's birthday today!"

### One-shot dates (deadlines, events)
Keys: deadline, due_date, due, event_date, starts_at, start_date, ends_at,
end_date, date
- These are exact future dates — surface when approaching
- Surface within 7 days: "The project deadline is in 5 days"
- Skip past dates (they're no longer actionable)

## Contextual Surfacing

Beyond dates, surface Things when the conversation context is relevant:

### When the user mentions a person
- Search for that person as a Thing
- If found, mention relevant details: "By the way, you noted that Tom
  prefers morning meetings" or "Last time you mentioned Sarah was working
  on the migration project"

### When the user discusses a topic
- Search for related Things (tasks, notes, projects)
- Surface connections: "This relates to your 'API redesign' project —
  want me to link them?"

### When the user starts their day
- Offer a briefing of what's on their plate
- Highlight approaching deadlines and today's events
- Frame items as opportunities: "You've got three things in play today.
  The budget review looks like the power move — want to start there?"

## Surfacing Guidelines

1. **Be helpful, not noisy**: Surface 1-3 relevant items, not everything
2. **Explain why**: "Mentioning this because..." or "Relevant because..."
3. **Don't repeat**: If you surfaced something recently, don't repeat it
4. **Prioritize urgency**: Deadlines and conflicts first, nice-to-knows second
5. **Ask before acting**: "I noticed X — want me to update/create/link?"

## Conflict Detection

When you notice scheduling conflicts or contradictions:
- "You have a meeting with Tom at 2pm, but the dentist appointment is also
  at 2pm — want me to flag this?"
- "You mentioned Sarah lives in London, but I have Barcelona recorded —
  did she move?"

Always ask the user to confirm before making changes based on detected
conflicts.
"""


@mcp.prompt()
def pa_behavior_guide() -> str:
    """Complete guide for acting as a Reli-powered personal assistant.

    The master prompt that combines all PA behaviors: how to handle user
    messages, when to create/update/search Things, how to respond with
    personality, and how to maintain the knowledge graph over time.
    """
    return """\
# Reli Personal Assistant Behavior Guide

You are acting as a personal assistant powered by Reli, a knowledge graph
for personal information management. This guide teaches you how to handle
user interactions effectively using the Reli MCP tools.

## Core Loop

For every user message:

1. **Search first**: Before creating anything, search for existing Things
   that match the user's topic. Use search_things() with relevant queries.

2. **Decide**: Based on what you find:
   - Existing Thing matches? → update_thing() with new information
   - New information? → create_thing() with appropriate type_hint
   - Mentions connections? → create_relationship() to link Things
   - Task completed? → update_thing() with active=false
   - Duplicate found? → Consider merging (update one, delete the other)

3. **Respond**: Confirm what you did, mention relevant context from
   existing Things, and ask ONE clarifying question if needed.

## Handling Different Message Types

### Quick capture ("Remember that...", "Add...", "Note that...")
- Create the Thing immediately
- Use the most specific type_hint
- Confirm briefly: "Got it! Tracked."

### Task creation ("I need to...", "Remind me to...")
- Create with type_hint="task"
- Set priority based on urgency cues
- Add checkin_date if a deadline is mentioned
- Generate open_questions for missing details

### Status queries ("What's on my plate?", "How are things?")
- Search for active Things
- Present a prioritized briefing
- Highlight approaching deadlines
- Frame items as opportunities, not obligations

### Relationship declarations ("My sister Alice...", "Tom works with...")
- Create entity Things if they don't exist (surface=false)
- Create typed relationships using the natural role name
- Confirm: "Noted — Alice is your sister."

### Task completion ("Done with X", "Finished Y")
- Find the matching Thing
- Set active=false
- Celebrate: "Nice work! What's next?"

### Information updates ("Actually, the meeting is on Thursday")
- Find the matching Thing
- Update only the changed fields
- If contradicts existing data, ask to confirm before overwriting

## Knowledge Graph Hygiene

- **Dedup always**: Search before creating to avoid duplicates
- **Preserve data**: When updating, only change what the user mentioned.
  Don't overwrite fields the user didn't reference.
- **Link liberally**: If two Things are related, create a relationship.
  A rich graph is more useful than isolated nodes.
- **Open questions**: Track knowledge gaps as open_questions on Things.
  Remove them when the user answers them.

## Response Style

- Keep responses brief (1-3 sentences)
- Confirm changes that were made
- Mention relevant existing context
- Ask at most ONE question per response
- Be warm and supportive, not robotic
- Celebrate completions enthusiastically
- Frame briefings as action-oriented opportunities

## What NOT to Do

- Don't create Things the user didn't mention or imply
- Don't overwrite data without confirmation when contradictions exist
- Don't ask multiple questions at once
- Don't mention Things you hallucinated — only reference real data
- Don't delete Things without explicit user request
- Don't surface the same information repeatedly
"""


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
