"""Reli MCP server — CRUD + search tools and reli_think reasoning-as-a-service.

Exposes Things and Relationships as MCP tools over stdio transport,
plus `reli_think` for reasoning-as-a-service: send natural language,
get structured instructions back (what to create/update/link/delete).

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
        "goals) and the typed relationships between them. For complex requests, "
        "use reli_think to get AI-powered reasoning about what changes to make."
    ),
)


# ---------------------------------------------------------------------------
# CRUD + Search Tools (Phase 1)
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
# Reasoning-as-a-service: reli_think (Phase 3)
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
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server over stdio."""
    if not RELI_API_TOKEN:
        print("Warning: RELI_API_TOKEN not set. Auth will be skipped if server has no SECRET_KEY.", file=sys.stderr)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
