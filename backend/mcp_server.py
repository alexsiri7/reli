"""Reli MCP server — CRUD + search tools wrapping the REST API.

Exposes Things and Relationships as MCP tools over stdio transport,
plus PA behavior prompts as MCP prompt resources.

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
        "goals) and the typed relationships between them. Use the prompt resources "
        "to adopt Reli's PA behavior patterns when interacting with the user."
    ),
)


# ---------------------------------------------------------------------------
# Tools — Phase 1: CRUD + Search
# ---------------------------------------------------------------------------


@mcp.tool()
def search_things(
    query: str,
    active_only: bool | None = None,
    type_hint: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search for Things in the knowledge graph by text query.

    Args:
        query: Text to search for in Thing titles and data.
        active_only: If true, only return active (non-archived) Things.
        type_hint: Filter by category (task, note, idea, project, goal, journal,
                   person, place, event, concept, reference).
        limit: Maximum results to return (default 20).
    """
    params: dict[str, Any] = {"q": query, "limit": limit}
    if active_only is not None:
        params["active_only"] = active_only
    if type_hint is not None:
        params["type_hint"] = type_hint
    result: list[dict[str, Any]] = _api_get("/api/things/search", params=params)
    return result


@mcp.tool()
def get_thing(thing_id: str) -> dict[str, Any]:
    """Get a single Thing by its UUID, including all fields and relationships.

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
    checkin_date: str | None = None,
    open_questions: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new Thing in the knowledge graph.

    Args:
        title: Human-readable title (prefer specific over vague).
        type_hint: Category — one of task, note, idea, project, goal, journal,
                   person, place, event, concept, reference.
        data: Arbitrary JSON data (notes, location, budget, etc.).
        priority: 1 (highest) to 5 (lowest), default 3.
        checkin_date: Optional ISO-8601 date for reminders.
        open_questions: Knowledge gaps — questions that would make this Thing
                        more actionable.
    """
    body: dict[str, Any] = {
        "title": title,
        "priority": priority,
        "active": True,
        "surface": True,
    }
    if type_hint is not None:
        body["type_hint"] = type_hint
    if data is not None:
        body["data"] = data
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
    """Update fields on an existing Thing.

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
# Prompt Resources — Phase 2: PA Behavior Prompts
# ---------------------------------------------------------------------------

_THING_CREATION_GUIDANCE = """\
You are helping a user manage their personal knowledge graph in Reli.
When creating Things, follow these patterns:

## Titles
- Use specific, actionable titles: "Draft Q1 budget spreadsheet" not "Work on budget"
- For tasks, start with a verb: "Call dentist", "Review PR #42", "Book flights to Tokyo"
- For people, use their name: "Sarah Chen", "Dr. Martinez"

## Type Hints
Choose the most appropriate type_hint for each Thing:
- **task**: Actionable work item with a clear "done" state
- **project**: Collection of related tasks toward a larger goal
- **goal**: Aspirational outcome (may not have concrete steps yet)
- **note**: Information to remember, no action needed
- **idea**: Something to explore or develop later
- **journal**: Personal reflection or log entry
- **person**: A contact or relationship
- **place**: A location relevant to the user
- **event**: A time-bound occurrence
- **concept**: An abstract idea or topic
- **reference**: External resource, link, or document

## Priority (1-5)
- **1**: Urgent/critical — blocking other work or time-sensitive
- **2**: High — important but not urgent
- **3**: Normal (default) — standard priority
- **4**: Low — nice to have, do when free
- **5**: Backlog — someday/maybe

## Open Questions (Knowledge Gaps)
When creating a Thing, identify 1-3 knowledge gaps that would make it more actionable:
- "What's the deadline?" (for tasks without dates)
- "Who else is involved?" (for collaborative work)
- "What does success look like?" (for vague goals)
- "What's the budget?" (for projects with costs)
Don't ask questions whose answers are already in the Thing's data.

## Checkin Dates
Set checkin_date (ISO 8601) for Things that need follow-up:
- Tasks with deadlines: set to a few days before the deadline
- People: set to next expected interaction
- Events: set to event date
- Goals: set to next review date

## Data Field
Store structured metadata in the data dict:
- {"notes": "..."} for additional context
- {"location": "..."} for places or events
- {"url": "..."} for references
- {"birthday": "1990-05-15"} for recurring date surfacing
- {"deadline": "2026-04-01"} for proactive deadline alerts

## Task Granularity
If a task seems broad ("plan vacation", "get healthier"), break it down:
1. Create the broad item as a project or goal
2. Ask the user: "What's the very first small piece we can bite off?"
3. Create specific sub-tasks as children of the project
"""

_RELATIONSHIP_PATTERNS = """\
You are helping a user build a personal knowledge graph in Reli.
Use relationships to create meaningful connections between Things.

## Relationship Types
- **works_with**: Person-to-person professional connection
- **depends_on**: Task/project dependency (A depends_on B = A needs B done first)
- **related_to**: General association between any two Things
- **belongs_to**: Membership or containment (task belongs_to project)
- **works_on**: Person works on a project/task
- **lives_in** / **located_at**: Person or thing at a place
- **reports_to**: Organizational hierarchy
- **blocked_by**: Like depends_on but for active blockers
- **inspired_by**: Idea or goal inspired by another Thing

## When to Create Relationships
- When the user mentions connections: "Sarah works with Tom", "this is part of Project X"
- When creating sub-tasks: link child tasks to parent project via belongs_to
- When tracking dependencies: "I can't do X until Y is done" → X depends_on Y
- When the user associates people with projects: person works_on project

## Relationship Direction
The direction matters: from_thing → relationship_type → to_thing
- "Sarah works_with Tom": from=Sarah, to=Tom
- "Task A depends_on Task B": from=A, to=B (A needs B)
- "Bug report belongs_to Project X": from=Bug, to=Project

## Metadata
Add metadata to relationships when there's additional context:
- {"role": "tech lead"} on a works_on relationship
- {"priority": "critical"} on a depends_on relationship
- {"since": "2024-01"} on a works_with relationship

## Merging Duplicates
If two Things represent the same real-world entity:
1. Identify which has more data (the "primary")
2. Use the merge operation to combine them
3. All relationships from the duplicate are transferred to the primary
"""

_TYPE_HINT_USAGE = """\
You are helping a user categorize Things in their Reli knowledge graph.
Choose the right type_hint to enable proper filtering, surfacing, and behavior.

## Type Hint Reference

| Type | When to Use | Example |
|------|-------------|---------|
| task | Has a clear "done" state, actionable | "Buy groceries", "File taxes" |
| project | Groups related tasks toward a goal | "Kitchen renovation", "Q1 launch" |
| goal | Aspirational outcome, may be ongoing | "Get healthier", "Learn Spanish" |
| note | Information storage, no action needed | "Meeting notes 2026-03-15" |
| idea | Explore later, not yet actionable | "App idea: meal planner" |
| journal | Personal reflection, time-stamped | "Weekly reflection: good progress" |
| person | A contact or relationship | "Sarah Chen", "Dr. Martinez" |
| place | A physical location | "Coffee shop on 5th", "Mom's house" |
| event | Time-bound occurrence | "Team offsite March 28" |
| concept | Abstract topic or category | "Machine learning", "Stoicism" |
| reference | External resource or document | "API docs for Stripe" |
| preference | User personality/behavior pattern | "Communication preferences" |

## Behavioral Differences by Type

### Tasks & Projects
- Show in active task lists when active=true
- Can have priority (1-5) for ordering
- Completing a task (active=false) triggers celebration in responses
- Projects can have child tasks via parent_id

### People
- Date fields like "birthday" trigger proactive surfacing
- Relationships (works_with, reports_to) build the social graph
- Store contact info in data: {"email": "...", "phone": "..."}

### Events
- Date fields trigger proactive surfacing ("Event in 3 days")
- Store time/location in data for quick reference

### Preferences
- Special type used by the personality system
- Stored as patterns with confidence levels
- Automatically loaded to customize response behavior

## Date-Based Proactive Surfacing
Certain data keys trigger automatic reminders:
- **Recurring** (month/day match each year): birthday, anniversary, dob
- **One-shot** (exact date match): deadline, due_date, event_date, start_date, end_date
Set these in the data dict to get proactive alerts.
"""

_PROACTIVE_SURFACING_RULES = """\
You are helping a user set up Things in Reli for automatic proactive surfacing.
Reli can automatically alert users about approaching dates.

## How Proactive Surfacing Works
Things with date values in their data dict are automatically scanned.
When a date falls within the look-ahead window (default 7 days), it surfaces
in the UI sidebar and can be included in briefings.

## Recurring Dates (repeat every year)
These date keys match on month/day, ignoring year:
- **birthday**: "1990-05-15" → surfaces every May 15
- **anniversary**: "2020-06-01" → surfaces every June 1
- **born** / **date_of_birth** / **dob**: aliases for birthday

Example Thing data for a person:
```json
{"birthday": "1990-05-15", "notes": "Likes chocolate cake"}
```
→ Surfaces: "Birthday in 3 days" each year

## One-Shot Dates (exact date, future only)
These date keys match the exact date (past dates are ignored):
- **deadline**: Project or task due date
- **due_date** / **due**: Alternative deadline keys
- **event_date**: When an event occurs
- **starts_at** / **start_date**: When something begins
- **ends_at** / **end_date**: When something ends
- **date**: Generic date key

Example Thing data for a task:
```json
{"deadline": "2026-04-15", "notes": "Submit Q1 report"}
```
→ Surfaces: "Deadline in 5 days" (then disappears after the date passes)

## Setting Up Surfacing for New Things
When creating Things that have time relevance:
1. Store the date in the data dict using one of the recognized keys
2. Use ISO 8601 format: "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS"
3. Set a checkin_date a few days before for the user's own reminder
4. For people, always ask about birthdays/anniversaries

## Briefing Integration
When briefing_mode is active, proactively surfaced items should be
woven into the briefing naturally:
- "Heads up — Sarah's birthday is Thursday! 🎂"
- "The Q1 report deadline is in 3 days. Want to review progress?"
"""


@mcp.prompt()
def thing_creation_guidance() -> str:
    """Best practices for creating Things in Reli — titles, type hints,
    priorities, open questions, checkin dates, and data fields."""
    return _THING_CREATION_GUIDANCE


@mcp.prompt()
def relationship_patterns() -> str:
    """How to create and use typed relationships between Things —
    relationship types, direction, metadata, and merging duplicates."""
    return _RELATIONSHIP_PATTERNS


@mcp.prompt()
def type_hint_usage() -> str:
    """Complete reference for Reli type_hint values — when to use each type,
    behavioral differences, and date-based proactive surfacing triggers."""
    return _TYPE_HINT_USAGE


@mcp.prompt()
def proactive_surfacing_rules() -> str:
    """How to set up Things for automatic date-based proactive surfacing —
    recurring dates (birthdays), one-shot dates (deadlines), and briefing
    integration."""
    return _PROACTIVE_SURFACING_RULES


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server over stdio."""
    if not RELI_API_TOKEN:
        print(
            "Warning: RELI_API_TOKEN not set. Auth will be skipped if server has no SECRET_KEY.",
            file=sys.stderr,
        )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
