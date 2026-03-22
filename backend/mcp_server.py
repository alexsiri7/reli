"""Reli MCP server — knowledge graph tools wrapping the REST API.

Exposes Things, Relationships, briefing, and conflict detection as MCP tools
over stdio transport.  Connects to a running Reli API instance via HTTP.

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
        "goals) and the typed relationships between them. "
        "Use get_briefing to see what needs attention today (checkin-due items and "
        "sweep findings). Use get_conflicts to detect blockers, schedule overlaps, "
        "and deadline conflicts."
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
# Server-side intelligence tools
# ---------------------------------------------------------------------------


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
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server over stdio."""
    if not RELI_API_TOKEN:
        print("Warning: RELI_API_TOKEN not set. Auth will be skipped if server has no SECRET_KEY.", file=sys.stderr)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
