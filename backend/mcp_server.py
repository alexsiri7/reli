"""Reli MCP server — knowledge graph tools backed by shared tool implementations.

Exposes Things, Relationships, briefing, conflict detection, chat_history,
and reli_think reasoning-as-a-service as MCP tools.  Tool logic lives in
``backend.tools`` and is shared with the reasoning agent.

Supports two transports:
- Streamable HTTP (primary): mounted at /mcp inside the FastAPI app.
  Protected by MCP_API_TOKEN bearer token.
- stdio (legacy): run via ``python -m backend.mcp_server`` for local clients.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from . import tools as shared_tools

# Context variable holding the authenticated user_id for the current request.
# Set by _TokenAuthMiddleware, read by MCP tool functions.
_current_user_id: contextvars.ContextVar[str] = contextvars.ContextVar("_current_user_id", default="")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

from mcp.server.fastmcp.server import TransportSecuritySettings

# Allow the production host through MCP's DNS rebinding protection.
# Derive from RELI_BASE_URL or GOOGLE_AUTH_REDIRECT_URI.
_RELI_HOST = os.environ.get("RELI_BASE_URL", "").replace("https://", "").replace("http://", "").rstrip("/")
if not _RELI_HOST:
    _redirect_uri = os.environ.get("GOOGLE_AUTH_REDIRECT_URI", "")
    if _redirect_uri:
        _redirect_parts = _redirect_uri.split("/")
        _RELI_HOST = _redirect_parts[2] if len(_redirect_parts) > 2 else ""
_allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
if _RELI_HOST:
    _allowed_hosts.append(_RELI_HOST)

mcp = FastMCP(
    "Reli",
    instructions=(
        "Reli is a personal knowledge graph. Use these tools to search, create, "
        "read, update, and delete Things (tasks, notes, projects, people, ideas, "
        "goals) and the typed relationships between them. "
        "Use get_briefing to see what needs attention today (checkin-due items and "
        "sweep findings). Use get_open_questions to find Things with unresolved "
        "knowledge gaps and ask the user proactively. "
        "Use get_conflicts to detect blockers, schedule overlaps, "
        "and deadline conflicts. "
        "Use the prompt resources (reasoning-agent, context-agent, response-agent) to "
        "adopt a specific Reli agent persona with the right tools — becoming Reli, not "
        "just talking to it. Use thing-schema for the full data model reference. "
        "Use reli_think for AI-powered reasoning over complex natural language requests."
    ),
    # Path is "/" because FastAPI mounts us at /mcp — the combined path is /mcp/
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed_hosts,
    ),
)


def _user_id() -> str:
    """Get the authenticated user_id for the current MCP request."""
    return _current_user_id.get("")


# ---------------------------------------------------------------------------
# Context + Search Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def fetch_context(
    search_queries: list[str] | None = None,
    fetch_ids: list[str] | None = None,
    active_only: bool = True,
    type_hint: str = "",
) -> dict[str, Any]:
    """Search the Things database for relevant context.

    Call this tool FIRST to find Things related to the user's request before
    making storage changes. This prevents creating duplicates and provides
    full context about what the user has already stored.

    Args:
        search_queries: List of search query strings, e.g. ["vacation plans", "travel"].
        fetch_ids: List of specific Thing IDs to fetch by ID.
        active_only: Only return active Things (default true).
        type_hint: Filter by type (task, note, person, project, etc.), or empty for all.

    Returns:
        Dict with 'things' (list of Thing dicts), 'relationships' (list of
        relationship dicts between found Things), and 'count' (number found).
    """
    return shared_tools.fetch_context(
        search_queries_json=json.dumps(search_queries or []),
        fetch_ids_json=json.dumps(fetch_ids or []),
        active_only=active_only,
        type_hint=type_hint,
        user_id=_user_id(),
    )


@mcp.tool()
def get_thing(thing_id: str) -> dict[str, Any]:
    """Get a single Thing by its ID, including all fields.

    Args:
        thing_id: The UUID of the Thing to retrieve.
    """
    return shared_tools.get_thing(thing_id=thing_id, user_id=_user_id())


@mcp.tool()
def create_thing(
    title: str,
    type_hint: str | None = None,
    data: dict[str, Any] | None = None,
    importance: int = 2,
    checkin_date: str | None = None,
    active: bool = True,
    surface: bool = True,
    open_questions: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new Thing in the knowledge graph.

    Use create_relationship with type 'parent-of' or 'child-of' to establish hierarchy.

    Args:
        title: Short descriptive title (required).
        type_hint: System type ('task', 'note', 'project', 'person', 'idea', 'goal', 'journal', 'event', 'place', 'concept', 'reference', 'preference') or a custom lowercase singular noun (e.g. 'trip', 'recipe', 'rehearsal'). Custom types default to surface=true.
        data: Arbitrary JSON data (e.g. {"email": "...", "birthday": "..."}).
        importance: How bad if undone: 0 (critical) to 4 (backlog), default 2.
        checkin_date: ISO 8601 date when this Thing should surface in the briefing.
        active: Whether the Thing is active (true) or completed/archived (false).
        surface: Whether to show in default views.
        open_questions: List of unresolved questions about this Thing.
    """
    data_json = json.dumps(data) if data is not None else "{}"
    oq_json = json.dumps(open_questions) if open_questions is not None else "[]"
    return shared_tools.create_thing(
        title=title,
        type_hint=type_hint or "",
        importance=importance,
        checkin_date=checkin_date or "",
        surface=surface,
        data_json=data_json,
        open_questions_json=oq_json,
        user_id=_user_id(),
    )


@mcp.tool()
def update_thing(
    thing_id: str,
    title: str | None = None,
    type_hint: str | None = None,
    data: dict[str, Any] | None = None,
    importance: int | None = None,
    checkin_date: str | None = None,
    active: bool | None = None,
    surface: bool | None = None,
    open_questions: list[str] | None = None,
) -> dict[str, Any]:
    """Update an existing Thing. Only provided fields are changed.

    Use create_relationship / delete_relationship to change hierarchy.

    Args:
        thing_id: The UUID of the Thing to update.
        title: New title.
        type_hint: New category.
        data: New arbitrary JSON data (shallow-merged into existing data dict).
        importance: How bad if undone: 0 (critical) to 4 (backlog).
        checkin_date: New checkin date (ISO 8601).
        active: Set active/archived status.
        surface: Set visibility in default views.
        open_questions: New list of unresolved questions.
    """
    data_json = json.dumps(data) if data is not None else ""
    oq_json = json.dumps(open_questions) if open_questions is not None else ""

    # Check if any field was actually provided
    has_fields = any(v is not None for v in [title, type_hint, data, importance, checkin_date, active, surface, open_questions])
    if not has_fields:
        return {"error": "No fields provided to update"}

    return shared_tools.update_thing(
        thing_id=thing_id,
        title=title or "",
        active=active,
        checkin_date=checkin_date or "",
        importance=importance,
        type_hint=type_hint or "",
        surface=surface,
        data_json=data_json,
        open_questions_json=oq_json,
        user_id=_user_id(),
    )


@mcp.tool()
def delete_thing(thing_id: str) -> dict[str, Any]:
    """Soft-delete a Thing by marking it inactive (active=false).

    The Thing record is preserved in the knowledge graph — MCP clients cannot
    permanently destroy data. Returns the deactivated Thing so the client can
    confirm what was deleted.

    Args:
        thing_id: The UUID of the Thing to deactivate.
    """
    return shared_tools.update_thing(thing_id=thing_id, active=False, user_id=_user_id())


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
    return shared_tools.merge_things(keep_id=keep_id, remove_id=remove_id, user_id=_user_id())


@mcp.tool()
def list_relationships(thing_id: str) -> list[dict[str, Any]]:
    """List all relationships where a Thing is source or target.

    Args:
        thing_id: The UUID of the Thing whose relationships to retrieve.
    """
    return shared_tools.list_relationships(thing_id=thing_id, user_id=_user_id())


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
    return shared_tools.create_relationship(
        from_thing_id=from_thing_id,
        to_thing_id=to_thing_id,
        relationship_type=relationship_type,
        user_id=_user_id(),
    )


@mcp.tool()
def delete_relationship(relationship_id: str) -> dict[str, Any]:
    """Delete a relationship between two Things.

    Args:
        relationship_id: The UUID of the relationship to delete.
    """
    return shared_tools.delete_relationship(relationship_id=relationship_id, user_id=_user_id())


# ---------------------------------------------------------------------------
# Server-side intelligence tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_briefing(as_of: str | None = None) -> dict[str, Any]:
    """Get today's daily briefing — structured sweep output for the calling agent.

    Returns machine-readable data for the PA to decide what to surface. Response
    structure:
      - date: ISO 8601 date the briefing is for.
      - things: Things with approaching checkin dates (the user asked to be
        reminded on/before this date). Each has a ``checkin_date`` field.
      - findings: Active sweep findings. Each has a ``finding_type`` field:
          - ``approaching_date``: Something time-sensitive within 7 days.
          - ``stale``: Active Thing not updated in 14+ days.
          - ``neglected``: High-importance or active-children Thing that's stale.
          - ``overdue_checkin``: Thing whose checkin_date is in the past.
          - ``cross_project_resource_conflict``: Person involved in multiple stale projects.
        Each finding also has ``message`` (human-readable summary), ``priority``
        (0=critical → 4=backlog), and an optional linked ``thing`` object.
      - total: Total count of things + findings.

    Returns empty lists (total=0) if no sweep has run or nothing needs attention.

    Args:
        as_of: Optional ISO 8601 date (YYYY-MM-DD) to get the briefing for.
               Defaults to today.
    """
    return shared_tools.get_briefing(as_of=as_of, user_id=_user_id())


@mcp.tool()
def get_open_questions(limit: int = 50) -> list[dict[str, Any]]:
    """Get Things that have unresolved open questions, ordered by importance then recency.

    Returns active Things with non-empty ``open_questions`` arrays. Each Thing
    includes its full field set including the ``open_questions`` list of strings —
    knowledge gaps the PA should proactively resolve by asking the user during
    conversation. Returns an empty list if no Things have open questions.

    Args:
        limit: Maximum number of Things to return (1-200, default 50).
    """
    return shared_tools.get_open_questions(limit=min(max(limit, 1), 200), user_id=_user_id())


@mcp.tool()
def get_user_profile() -> dict[str, Any]:
    """Get the current user's profile Thing with all resolved relationships.

    Returns the user's anchor Thing (type_hint=person, surface=false) with its
    full field set plus a 'relationships' list. Each relationship includes:
    - id, relationship_type, direction ('incoming' or 'outgoing')
    - related_thing_id, related_thing_title

    Call this once at session start to load who the user is. Returns an error
    dict if no profile Thing exists.
    """
    return shared_tools.get_user_profile(user_id=_user_id())


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
    return shared_tools.get_conflicts(window=min(max(window, 1), 90), user_id=_user_id())


@mcp.tool()
def schedule_task(
    scheduled_at: str,
    task_type: str = "remind",
    thing_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Schedule autonomous future work for Reli.

    Creates a task that will be executed automatically at the specified time.
    Results surface in the next briefing as sweep findings.

    Args:
        scheduled_at: ISO-8601 datetime when the task should execute (required).
            Example: "2026-05-01T09:00:00".
        task_type: Type of task. Valid values:
            - "remind" (default): Create a reminder finding at the scheduled time.
            - "check": Check on something and report findings.
            - "sweep_concern": Flag a concern for the next sweep.
            - "custom": Custom task with instructions in payload.
        thing_id: Optional UUID of a Thing this task relates to.
        payload: Optional JSON data for the task (e.g. {"message": "Check flight prices"}).

    Returns:
        The created scheduled task dict including its generated 'id'.
    """
    return shared_tools.create_scheduled_task(
        scheduled_at=scheduled_at,
        task_type=task_type,
        thing_id=thing_id or "",
        payload_json=json.dumps(payload or {}),
        user_id=_user_id(),
    )


@mcp.tool()
def chat_history(
    n: int = 10,
    search_query: str = "",
) -> dict[str, Any]:
    """Search across all conversation sessions for the current user.

    Use this to find past conversations, recall things discussed previously,
    or check what was said about a specific topic across sessions.

    Args:
        n: Number of messages to retrieve (default 10, max 50).
        search_query: Optional text to filter messages by content.
    """
    return shared_tools.chat_history(
        n=n,
        search_query=search_query,
        cross_session=True,
        user_id=_user_id(),
    )


# ---------------------------------------------------------------------------
# MCP Prompt Resources — Real agent system prompts from shared .md files
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    """Load a prompt from the prompts/ directory."""
    return (_PROMPTS_DIR / f"{name}.md").read_text()


@mcp.prompt(
    name="context-agent",
    description=(
        "The Reli context agent's full system prompt. Adopt this persona to search "
        "for relevant Things in the knowledge graph given a user message. "
        "Designed for use with the fetch_context tool (read-only)."
    ),
)
def context_agent_prompt() -> str:
    """Reli context agent — searches for relevant Things given a user message."""
    return _load_prompt("context-agent")


@mcp.prompt(
    name="reasoning-agent",
    description=(
        "The Reli reasoning agent's full system prompt. Adopt this persona to decide "
        "what storage changes are needed based on the user's request and retrieved context. "
        "Designed for use with: fetch_context, create_thing, update_thing, delete_thing, "
        "merge_things, create_relationship."
    ),
)
def reasoning_agent_prompt() -> str:
    """Reli reasoning agent — decides what storage changes to make."""
    return _load_prompt("reasoning-agent")


@mcp.prompt(
    name="response-agent",
    description=(
        "The Reli response agent's full system prompt. Adopt this persona to produce "
        "the final user-facing reply after reasoning and storage changes are complete. "
        "Pure formatting and personality — no MCP tools needed."
    ),
)
def response_agent_prompt() -> str:
    """Reli response agent — produces the final user-facing reply."""
    return _load_prompt("response-agent")


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
| checkin_date   | ISO 8601 or null| null    | When to surface this Thing in the daily briefing |
| importance     | int (0–4)       | 2       | How bad if undone: 0 = critical, 4 = backlog   |
| active         | bool            | true    | false = completed/archived (never hard-delete) |
| surface        | bool            | true    | false = graph entity, hide from default views  |
| data           | object or null  | null    | Arbitrary JSON for custom fields and notes     |
| open_questions | string[] or null| null    | Unresolved knowledge gaps about this Thing     |
| created_at     | ISO 8601        | auto    | Creation timestamp                             |
| updated_at     | ISO 8601        | auto    | Last-modified timestamp                        |

## type_hint

`type_hint` is open-ended — use any lowercase singular noun that fits.

### System types (preferred when they fit)

| type_hint   | Meaning                                            | surface default |
|-------------|---------------------------------------------------|-----------------|
| task        | Actionable work item with a clear outcome          | true            |
| note        | Freeform information or observation                | true            |
| idea        | Something to explore or brainstorm                 | true            |
| project     | Container for related tasks and notes              | true            |
| goal        | High-level objective (parent of tasks)             | true            |
| journal     | Reflective or diary-style entry                    | true            |
| preference  | Learned user preference pattern                    | false           |
| person      | A person the user interacts with                   | false           |
| place       | A physical or virtual location                     | false           |
| event       | A specific occurrence or meeting                   | false           |
| concept     | An abstract idea or recurring topic                | false           |
| reference   | An external resource (URL, book, document, etc.)   | false           |

### Custom types
Use a custom type when no system type fits: "trip", "recipe", "rehearsal", "habit", "gig", etc.
Custom types default to `surface=true`.

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
  "importance": 2,
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
  "importance": 1,
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
async def reli_think(
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
    from .reasoning_agent import run_think_agent

    return await run_think_agent(
        message=message,
        context=context or "",
    )


# ---------------------------------------------------------------------------
# Streamable HTTP transport (for mounting inside FastAPI)
# ---------------------------------------------------------------------------


def _resource_metadata_url(cfg: Any) -> str:
    """Build the OAuth protected resource metadata URL."""
    base = cfg.RELI_BASE_URL
    if not base:
        uri = cfg.GOOGLE_AUTH_REDIRECT_URI or ""
        parts = uri.split("/")
        base = "/".join(parts[:3])
    return base.rstrip("/") + "/.well-known/oauth-protected-resource"


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
            if static_token and secrets.compare_digest(provided, static_token):
                authorized = True
                from .auth import _resolve_api_token_user

                resolved_uid = _resolve_api_token_user()
                if resolved_uid:
                    _current_user_id.set(resolved_uid)

            # 2. JWT validation (OAuth flow)
            if not authorized and secret_key:
                try:
                    import jwt as _jwt

                    payload = _jwt.decode(provided, secret_key, algorithms=["HS256"])
                    authorized = True
                    user_id = payload.get("sub", "")
                    _current_user_id.set(user_id)
                except Exception:
                    pass

        if not authorized:
            response = Response(
                content='{"detail":"Unauthorized"}',
                status_code=401,
                media_type="application/json",
                headers={
                    "WWW-Authenticate": (
                        'Bearer realm="reli"'
                        ', resource_metadata="'
                        + _resource_metadata_url(_settings)
                        + '"'
                    ),
                },
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
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
