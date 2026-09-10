"""The MCP surface: the only way into the graph.

Every tool here is a thin wrapper over :mod:`backend.service` (writes), :mod:`backend.queries`
(graph reads) or :mod:`backend.google_readers` (Calendar and Gmail reads). No judgement happens in
this module and no model is called from it — the tools hand Claude the graph and Claude decides
what it means.

Writing tools take ``actor`` as a required argument with no default, so a write cannot reach the
journal attributed to a guess: a call that omits it fails argument validation before any tool body
runs. Hard delete is deliberately not exposed; archiving goes through :func:`archive_thing`.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings
from sqlmodel import Session
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from . import google_readers, queries, service
from .config import settings
from .db_engine import get_engine
from .db_models import Actor, JournalRecord, RelationshipRecord, RelationshipType, ThingRecord

logger = logging.getLogger(__name__)

# ``Actor.USER`` is absent on purpose: per docs/vision.md the frontend never writes, and the one
# exception — rejecting a preference — arrives over HTTP in #1414, not over MCP. #1410 widens this
# alias if the preference tools need it; there is one place to widen.
McpActor = Literal[Actor.CLAUDE_INTERACTIVE, Actor.CLAUDE_SCHEDULED]


def _actor(actor: McpActor) -> Actor:
    return Actor(actor)


@contextmanager
def _session() -> Iterator[Session]:
    """The session a tool runs in. Tests patch this to bind the tools to the fixture session."""
    with Session(get_engine()) as session:
        yield session


def _thing_dict(thing: ThingRecord) -> dict[str, Any]:
    """Render a record the way ``service._snapshot`` does, so tool output and the journal agree."""
    return thing.model_dump(mode="json")


def _relationship_dict(relationship: RelationshipRecord) -> dict[str, Any]:
    return relationship.model_dump(mode="json")


def _journal_dict(entry: JournalRecord) -> dict[str, Any]:
    return entry.model_dump(mode="json")


def _related_dict(found: queries.RelatedThing) -> dict[str, Any]:
    return {
        "thing": _thing_dict(found.thing),
        "depth": found.depth,
        "relationship_type": found.relationship_type.value,
    }


reli_mcp = FastMCP(
    "Reli",
    instructions=(
        "Reli is a personal knowledge graph of Things — tasks, notes, projects, ideas, goals — and "
        "the typed relationships between them. There is no type column: what a Thing is lives in "
        "its tags and its edges, and hierarchy is a ChildOf relationship. "
        "Read with get_thing, find_things, get_related, children and the standing questions "
        "due_for_checkin, stale and blocked. Write with create_thing, update_thing, archive_thing, "
        "relate and unrelate. "
        "Every write requires an actor and is recorded in an append-only journal: pass "
        "'claude_interactive' when a person is in the conversation and 'claude_scheduled' when the "
        "session is an unattended scheduled task. The distinction is what lets Reli tell what the "
        "user decided from what Claude did, so it must be honest. "
        "Nothing is ever hard-deleted here — archive_thing retires a Thing and get_thing_history "
        "shows how it got that way. "
        "find_correspondence, find_events and check_occurred are read-only lookups into the user's "
        "Gmail and Calendar, there to settle a check-in without asking the user. They return "
        "evidence; what it means is yours to decide."
    ),
    # Mounted at /mcp by backend.main, so the SDK's own default of "/mcp" would serve /mcp/mcp.
    streamable_http_path="/",
    # The tools carry the actor per call and hold no session state, so there is nothing for a
    # session to remember; stateless also survives a container restart mid-conversation.
    stateless_http=True,
    # The SDK's default host allowlist is 127.0.0.1/localhost only, which answers 421 to every
    # request carrying a real Host header — Reli is served through a Cloudflare tunnel, so that
    # default is an outage. Safe only because _BearerTokenMiddleware below makes an Authorization
    # header mandatory, which a cross-origin page cannot set: the two decisions are coupled.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


# --- Writes ----------------------------------------------------------------


@reli_mcp.tool()
def create_thing(
    actor: McpActor,
    title: str,
    description: str | None = None,
    notes: dict[str, str] | None = None,
    tags: list[str] | None = None,
    urls: dict[str, str] | None = None,
    checkin_date: date | None = None,
    priority: float = 0.0,
) -> dict[str, Any]:
    """Create a Thing and journal it.

    Args:
        actor: 'claude_interactive' for a session with a person in it, 'claude_scheduled' for an
            unattended scheduled task. Required — no write is attributed by default.
        title: What the Thing is called.
        description: Longer prose about the Thing.
        notes: Slug to markdown mapping, for anything that does not fit the fields.
        tags: Free-form labels. What a Thing *is* lives here, not in a type column.
        urls: Name to URL mapping.
        checkin_date: When this should next come up; drives due_for_checkin.
        priority: Higher sorts first in every listing.

    Returns:
        The created Thing, including its id.
    """
    with _session() as session:
        thing = service.create_thing(
            session,
            actor=_actor(actor),
            title=title,
            description=description,
            notes=notes,
            tags=tags,
            urls=urls,
            checkin_date=checkin_date,
            priority=priority,
        )
        return _thing_dict(thing)


@reli_mcp.tool()
def update_thing(
    actor: McpActor,
    thing_id: uuid.UUID,
    title: str | None = None,
    description: str | None = None,
    notes: dict[str, str] | None = None,
    tags: list[str] | None = None,
    urls: dict[str, str] | None = None,
    checkin_date: date | None = None,
    priority: float | None = None,
) -> dict[str, Any]:
    """Update the given fields of a Thing and journal the change.

    Every field given **replaces** the stored value; nothing is merged. Passing ``tags`` writes
    exactly that list and drops the tags you left out; passing ``notes`` writes exactly that
    mapping. To add one note or one tag, read the Thing first with get_thing and pass the union.

    A field left unset is untouched, which also means this tool cannot clear a field back to empty.

    Archiving is not done here — use archive_thing, so there is one journalled way to retire a
    Thing.

    Args:
        actor: 'claude_interactive' or 'claude_scheduled'. Required.
        thing_id: The Thing to update.
        title: Replaces the title.
        description: Replaces the description.
        notes: Replaces the whole notes mapping.
        tags: Replaces the whole tag list.
        urls: Replaces the whole urls mapping.
        checkin_date: Replaces the check-in date.
        priority: Replaces the priority.

    Returns:
        The updated Thing.
    """
    with _session() as session:
        thing = service.update_thing(
            session,
            actor=_actor(actor),
            thing_id=thing_id,
            title=title,
            description=description,
            notes=notes,
            tags=tags,
            urls=urls,
            checkin_date=checkin_date,
            priority=priority,
        )
        return _thing_dict(thing)


@reli_mcp.tool()
def archive_thing(actor: McpActor, thing_id: uuid.UUID) -> dict[str, Any]:
    """Retire a Thing by setting it inactive, journalled as an update.

    The Thing and its relationships stay in the graph and stay readable; it simply drops out of
    due_for_checkin, stale, blocked and the default find_things. There is no hard delete over MCP
    and nothing here un-archives.

    Args:
        actor: 'claude_interactive' or 'claude_scheduled'. Required.
        thing_id: The Thing to archive.

    Returns:
        The archived Thing.
    """
    with _session() as session:
        thing = service.update_thing(session, actor=_actor(actor), thing_id=thing_id, active=False)
        return _thing_dict(thing)


@reli_mcp.tool()
def relate(
    actor: McpActor,
    source_thing_id: uuid.UUID,
    target_thing_id: uuid.UUID,
    relationship_type: RelationshipType,
    context: str | None = None,
) -> dict[str, Any]:
    """Link two Things with a typed, directed edge and journal it.

    Direction is read per type, not by a global convention:

    - ChildOf — source is the **parent**, target is the child.
    - Blocks — source is the **blocked** Thing, target is what blocks it.
    - EvidenceFor — source is the evidence, target is what it supports.
    - RelatedTo, References — direction carries no meaning yet.

    Args:
        actor: 'claude_interactive' or 'claude_scheduled'. Required.
        source_thing_id: The Thing the edge runs from.
        target_thing_id: The Thing the edge runs to.
        relationship_type: One of the five types above.
        context: Why this edge exists, in a sentence.

    Returns:
        The created relationship, including the id unrelate takes.
    """
    with _session() as session:
        relationship = service.relate(
            session,
            actor=_actor(actor),
            source_thing_id=source_thing_id,
            target_thing_id=target_thing_id,
            relationship_type=relationship_type,
            context=context,
        )
        return _relationship_dict(relationship)


@reli_mcp.tool()
def unrelate(actor: McpActor, relationship_id: uuid.UUID) -> dict[str, str]:
    """Remove a relationship and journal it. Both Things stay; only the edge goes.

    Args:
        actor: 'claude_interactive' or 'claude_scheduled'. Required.
        relationship_id: The edge to remove — get_thing lists the id of every edge on a Thing.

    Returns:
        The id that was removed.
    """
    with _session() as session:
        service.unrelate(session, actor=_actor(actor), relationship_id=relationship_id)
        return {"unrelated": str(relationship_id)}


# --- Reads -----------------------------------------------------------------


@reli_mcp.tool()
def get_thing(thing_id: uuid.UUID) -> dict[str, Any]:
    """One Thing and every edge touching it, in either direction.

    Args:
        thing_id: The Thing to read.

    Returns:
        ``{"thing": ..., "relationships": [...]}``. Each relationship carries the id that unrelate
        takes, so the graph is unlinkable from here.

    Raises:
        ThingNotFound: There is no Thing with that id.
    """
    with _session() as session:
        thing = session.get(ThingRecord, thing_id)
        if thing is None:
            raise service.ThingNotFound(f"no Thing with id {thing_id}")
        edges = queries.relationships_for(session, thing_id)
        return {
            "thing": _thing_dict(thing),
            "relationships": [_relationship_dict(edge) for edge in edges],
        }


@reli_mcp.tool()
def find_things(
    tags: list[str] | None = None,
    match: Literal["any", "all"] = "any",
    active: bool | None = True,
    checkin_from: date | None = None,
    checkin_to: date | None = None,
    priority_min: float | None = None,
    priority_max: float | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Things matching every filter given, highest priority first.

    This is a filter, not a search: there is no text matching anywhere in Reli.

    Args:
        tags: Restrict to Things carrying these tags. Omitted or empty means no tag filter — which
            returns everything, so pass tags when you mean to narrow.
        match: 'any' matches Things with at least one of the tags, 'all' requires every one.
        active: True for live Things, False for archived only, null for both.
        checkin_from: Only Things whose check-in date is on or after this.
        checkin_to: Only Things whose check-in date is on or before this.
        priority_min: Only Things at or above this priority.
        priority_max: Only Things at or below this priority.
        limit: How many to return at most.

    Returns:
        The matching Things.
    """
    with _session() as session:
        things = queries.find_things(
            session,
            tags=tags,
            match=match,
            active=active,
            checkin_from=checkin_from,
            checkin_to=checkin_to,
            priority_min=priority_min,
            priority_max=priority_max,
            limit=limit,
        )
        return [_thing_dict(thing) for thing in things]


@reli_mcp.tool()
def get_related(
    thing_id: uuid.UUID,
    types: list[RelationshipType] | None = None,
    depth: int = 1,
) -> list[dict[str, Any]]:
    """The neighbourhood of a Thing, nearest hop first.

    Edges are followed in **both** directions, so this includes what points at the Thing as well as
    what it points at. The Thing itself is never returned and cycles terminate. An id with no edges
    — or one that does not exist — returns an empty list.

    Args:
        thing_id: Where to start walking.
        types: Restrict the walk to these relationship types; omitted walks all five.
        depth: How many hops out to walk.

    Returns:
        One entry per Thing reached, with its hop count and the edge type that reached it.
    """
    with _session() as session:
        return [_related_dict(found) for found in queries.related(session, thing_id, types, depth)]


@reli_mcp.tool()
def due_for_checkin(as_of: date | None = None) -> list[dict[str, Any]]:
    """Active Things whose check-in date has arrived, most important first.

    Args:
        as_of: The date to judge against; today if omitted.

    Returns:
        The Things due.
    """
    with _session() as session:
        return [_thing_dict(thing) for thing in queries.due_for_checkin(session, as_of or datetime.now(UTC).date())]


@reli_mcp.tool()
def stale(days: int = 30) -> list[dict[str, Any]]:
    """Active Things untouched for at least this many days, longest untouched first.

    Args:
        days: How many days of silence counts as stale.

    Returns:
        The Things nobody has touched.
    """
    with _session() as session:
        return [_thing_dict(thing) for thing in queries.stale(session, datetime.now(UTC) - timedelta(days=days))]


@reli_mcp.tool()
def blocked() -> list[dict[str, Any]]:
    """Things held up by something still active, most important first.

    A Blocks edge runs from the blocked Thing to its blocker, so once the blocker is archived the
    Thing drops out of this list.

    Returns:
        The Things that are waiting on something.
    """
    with _session() as session:
        return [_thing_dict(thing) for thing in queries.blocked(session)]


@reli_mcp.tool()
def children(thing_id: uuid.UUID) -> list[dict[str, Any]]:
    """The children of a Thing — the targets of its ChildOf edges — most important first.

    An id with no children, or one that does not exist, returns an empty list.

    Args:
        thing_id: The parent.

    Returns:
        Its children.
    """
    with _session() as session:
        return [_thing_dict(thing) for thing in queries.children(session, thing_id)]


@reli_mcp.tool()
def get_thing_history(thing_id: uuid.UUID, limit: int = 200) -> list[dict[str, Any]]:
    """How a Thing got to its current state: its journal entries, oldest first.

    Only entries recorded against the Thing itself. Relating and unrelating are journalled against
    the *relationship*, so they do not appear here — use get_thing or get_related for the edges as
    they stand now. An id with no entries returns an empty list.

    Args:
        thing_id: The Thing to trace.
        limit: How many entries to return at most.

    Returns:
        One entry per mutation, each with the actor, the operation, and the before and after
        snapshots.
    """
    with _session() as session:
        return [_journal_dict(entry) for entry in queries.history(session, thing_id, limit)]


# --- Google reads (Calendar and Gmail) -------------------------------------


@reli_mcp.tool()
def find_correspondence(
    query: str,
    since: date | None = None,
    until: date | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search the user's Gmail and summarise what matched.

    Read-only: this cannot send, reply, draft, label or delete. Each result is a summary —
    sender, recipient, subject, date, Gmail's own snippet and the labels. Message bodies are
    never fetched, so a snippet is all the text there is.

    Every result costs a separate request to Gmail, so ``limit`` is capped at 25: a broad query is
    not free.

    Args:
        query: Gmail search syntax, the same as the search box — words, from:, subject:, has:.
        since: Only messages on or after this date. Inclusive.
        until: Only messages on or before this date. Inclusive.
        limit: How many messages to summarise at most, capped at 25.

    Returns:
        The matching messages, newest first.
    """
    return google_readers.find_correspondence(query=query, since=since, until=until, limit=limit)


@reli_mcp.tool()
def find_events(since: date, until: date, query: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    """Read the user's primary calendar over a date range and summarise what is on it.

    Read-only: this cannot create, move, cancel or respond to an event. Recurring events are
    expanded into their individual occurrences. Each result is a summary — title, start, end,
    status, location, how many people were invited, and how the user themselves responded.

    Args:
        since: First day of the window. Inclusive.
        until: Last day of the window. Inclusive.
        query: Free-text filter over the events; omitted returns everything in the window.
        limit: How many events to return at most, capped at 25.

    Returns:
        The events in the window, earliest first.
    """
    return google_readers.find_events(since=since, until=until, query=query, limit=limit)


@reli_mcp.tool()
def check_occurred(description: str, since: date, until: date, limit: int = 10) -> dict[str, Any]:
    """Gather what Calendar and Gmail hold about something, so you can judge whether it happened.

    Read-only, and deliberately verdict-free: it returns the events and messages it found plus
    their counts, and nothing that says yes or no. **Judging whether the thing happened is your
    job** — an empty result can mean it did not happen, or that it left no trace, and only you can
    tell those apart from the rest of the conversation. If you record a conclusion in the graph,
    record what you concluded it from.

    Gmail costs one request per message, so ``limit`` is capped at 25 per source.

    Args:
        description: What to look for, in the user's own words — searched in both sources.
        since: First day of the window. Inclusive.
        until: Last day of the window. Inclusive.
        limit: How many results to gather from each source, capped at 25.

    Returns:
        The window, the matching events and messages, and a count of each.
    """
    return google_readers.check_occurred(description=description, since=since, until=until, limit=limit)


# --- Transport -------------------------------------------------------------


class _BearerTokenMiddleware:
    """Requires ``Authorization: Bearer <MCP_API_TOKEN>`` on every request to the mounted app.

    An unset token closes the endpoint rather than opening it: there is no dev-mode bypass, because
    /mcp is the only write path into the graph and it is publicly reachable.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Read the token per request, not at construction: the app is built at import time, so a
        # value captured then could never be corrected.
        expected = settings.MCP_API_TOKEN
        header = dict(scope.get("headers", [])).get(b"authorization", b"").decode()
        provided = header[7:] if header.startswith("Bearer ") else ""

        if not expected or not secrets.compare_digest(provided, expected):
            response = Response(
                content='{"detail":"Unauthorized"}',
                status_code=401,
                media_type="application/json",
                headers={"WWW-Authenticate": 'Bearer realm="reli"'},
            )
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)


def create_mcp_asgi_app() -> ASGIApp:
    """The streamable-HTTP MCP app behind the bearer check, for ``app.mount("/mcp", ...)``."""
    if not settings.MCP_API_TOKEN:
        logger.warning("MCP_API_TOKEN is not set: /mcp will answer 401 to every request.")
    return _BearerTokenMiddleware(reli_mcp.streamable_http_app())
