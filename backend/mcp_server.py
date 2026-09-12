"""The MCP surface: the only way into the graph.

Every tool here is a thin wrapper over :mod:`backend.service` (writes) or :mod:`backend.queries`
(graph reads). No judgement happens in this module and no model is called from it — the tools hand
Claude the graph and Claude decides what it means.

Writing tools take ``actor`` as a required argument with no default, so a write cannot reach the
journal attributed to a guess: a call that omits it fails argument validation before any tool body
runs. Hard delete is deliberately not exposed; archiving goes through :func:`archive_thing`.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import jwt
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings
from sqlmodel import Session
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from . import auth, prompts, queries, service
from .config import settings
from .db_engine import get_engine
from .db_models import (
    OBSERVATION_TAG,
    PREFERENCE_TAG,
    REJECTED_TAG,
    USER_TAG,
    Actor,
    JournalRecord,
    RelationshipRecord,
    RelationshipType,
    ThingRecord,
)

logger = logging.getLogger(__name__)

# ``Actor.USER`` is absent on purpose: per docs/vision.md the frontend never writes. #1410 did not
# widen this — over MCP, ``reject_preference`` records the Claude session that relayed the
# rejection, which is what actually happened, and widening would let any MCP caller stamp a
# mutation as a user decision. That distinction is the learning pass's only signal for "the user
# decided" against "Claude did". A rejection attributed to ``Actor.USER`` arrives in #1414 by
# calling ``service.reject_preference`` directly, which takes any actor.
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


def _preference_dict(preference: queries.Preference) -> dict[str, Any]:
    return {
        "thing": _thing_dict(preference.thing),
        "scope": preference.scope,
        "rejected": preference.rejected,
        "evidence": [_thing_dict(thing) for thing in preference.evidence],
        "evidence_count": preference.evidence_count,
    }


def _history_dict(found: queries.History) -> dict[str, Any]:
    return {
        "entries": [_journal_dict(entry) for entry in found.entries],
        "total": found.total,
        "truncated": found.truncated,
    }


def _needs_input_dict(found: queries.NeedsInput) -> dict[str, Any]:
    return {
        "things": [_thing_dict(thing) for thing in found.things],
        "total": found.total,
        "truncated": found.truncated,
    }


reli_mcp = FastMCP(
    "Reli",
    instructions=(
        "Reli is a personal knowledge graph of Things — tasks, notes, projects, ideas, goals — and "
        "the typed relationships between them. Call get_initial_instructions before anything else: "
        "it returns how to behave as the user's assistant with Reli attached. "
        "There is no type column: what a Thing is lives in its tags and its edges, and hierarchy "
        "is a ChildOf relationship. "
        "Read with get_thing, find_things, get_related, children and the standing questions "
        "due_for_checkin, stale, blocked and needs_input. Write with create_thing, update_thing, "
        "archive_thing, relate and unrelate. "
        "Every write requires an actor and is recorded in an append-only journal: pass "
        "'claude_interactive' when a person is in the conversation and 'claude_scheduled' when the "
        "session is an unattended scheduled task. The distinction is what lets Reli tell what the "
        "user decided from what Claude did, so it must be honest. "
        "Nothing is ever hard-deleted here — archive_thing retires a Thing and get_thing_history "
        "shows how it got that way; journal_since reads the journal across the whole graph from an "
        "id onward, filtered by actor. "
        f"Reli also holds a model of its user: a single Thing tagged {USER_TAG} anchors "
        f"preferences, each its own Thing tagged {PREFERENCE_TAG} with a scope and the "
        "EvidenceFor edges that support it. Strength is the count of that evidence — there is no "
        "confidence score anywhere, and none may be added. Record a preference the moment you "
        "notice one, with record_preference, rather than in an end-of-session summary; reinforce "
        "an existing one with add_preference_evidence. A journal entry is evidence once a "
        f"{OBSERVATION_TAG} Thing holding its journal_entry_id stands for it, because an edge can "
        f"only point at a Thing. reject_preference tags a preference {REJECTED_TAG}; read the "
        "model with get_user_model, or load reli://user-model as context without a call. "
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
    due_for_checkin, stale, blocked, needs_input and the default find_things. There is no hard
    delete over MCP and nothing here un-archives.

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
def needs_input(limit: int = 100) -> dict[str, Any]:
    """Active Things tagged #NeedsInput — what only the user can settle — most important first.

    The tag is what the prompts apply to a Thing that cannot be resolved from Calendar, Gmail or the
    graph; this reads them back. Bounded because nothing but the user takes a Thing off this list,
    so total says how many there are and truncated whether this answer left any out.

    Args:
        limit: How many Things to return.

    Returns:
        things, total and truncated.
    """
    with _session() as session:
        return _needs_input_dict(queries.needs_input(session, limit=limit))


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
def get_thing_history(thing_id: uuid.UUID, limit: int = 200) -> dict[str, Any]:
    """How a Thing got to its current state: its most recent journal entries, oldest first.

    Only entries recorded against the Thing itself. Relating and unrelating are journalled against
    the *relationship*, so they do not appear here — use get_thing or get_related for the edges as
    they stand now. An id with no entries returns no entries and a total of zero.

    Args:
        thing_id: The Thing to trace.
        limit: How many entries to return at most; the newest this many are the ones returned.

    Returns:
        {"entries": [...], "total": N, "truncated": bool} — one entry per mutation, each with the
        actor, the operation, and the before and after snapshots; ``total`` is how many entries the
        Thing has in all. ``truncated`` is true when older entries were left out, and a larger
        ``limit`` reaches them.
    """
    with _session() as session:
        return _history_dict(queries.history(session, thing_id, limit))


@reli_mcp.tool()
def journal_since(after_id: int = 0, actors: list[Actor] | None = None, limit: int = 200) -> dict[str, Any]:
    """Everything that happened since a point in the journal, across every Thing and relationship.

    This is the learning pass's input: the entries with an id above ``after_id``, oldest first,
    whoever made them and whatever they touched. Page forward by passing the last ``id`` you saw
    back as the next ``after_id``; ``truncated`` says whether there is more.

    ``actors`` is how you keep Claude's own unattended edits out of a conclusion about the user: a
    check-in date moved by 'claude_scheduled' is not evidence of anything the user does. Pass
    ['user', 'claude_interactive'] to see only what happened with a person present.

    Args:
        after_id: Return entries with an id strictly above this; 0 reads from the beginning.
        actors: Only entries these actors made; omitted returns every actor's.
        limit: How many entries to return at most; the oldest this many are the ones returned.

    Returns:
        {"entries": [...], "total": N, "truncated": bool} — one entry per mutation, each with the
        actor, the operation, the entity and the before and after snapshots; ``total`` is how many
        entries match in all, and ``truncated`` is true when there is a next page.
    """
    with _session() as session:
        return _history_dict(queries.journal_since(session, after_id=after_id, actors=actors, limit=limit))


# --- The user model --------------------------------------------------------


def _user_model_payload(scope: str | None = None, include_rejected: bool = False) -> dict[str, Any]:
    """One shape for the tool and both resources, so they cannot answer differently."""
    with _session() as session:
        preferences = queries.user_model(session, scope=scope, include_rejected=include_rejected)
        return {"scope": scope, "preferences": [_preference_dict(preference) for preference in preferences]}


@reli_mcp.tool()
def record_preference(actor: McpActor, title: str, scope: str, evidence_ids: list[uuid.UUID]) -> dict[str, Any]:
    """Record something you have learned about the user as its own Thing, with its evidence.

    Write one the moment you notice it — a closed tab is a lost signal. Evidence is **required**: a
    preference nobody can trace back to specific moments is not recordable. Every evidence id is a
    Thing id; if what you are citing is a journal entry, create a Thing tagged #Observation with
    notes.journal_entry_id first and cite that.

    Strength is the number of pieces of evidence, so there is nothing to score and nothing to decay.

    Before recording, call get_user_model(include_rejected=true) and check you are not re-deriving
    something the user already rejected.

    Args:
        actor: 'claude_interactive' or 'claude_scheduled'. Required.
        title: The preference stated plainly — "Prefers deep work 9-11am".
        scope: What it applies to — one of the labels the prompts load: 'capture', 'scheduling',
            'planning' or 'review'. get_user_model matches it exactly (case aside), so a label no
            prompt loads is a preference no session ever sees.
        evidence_ids: The Things that support it. At least one.

    Returns:
        The preference with its scope, its evidence and the count of it.
    """
    with _session() as session:
        thing = service.record_preference(
            session,
            actor=_actor(actor),
            title=title,
            scope=scope,
            evidence_ids=evidence_ids,
        )
        return _preference_dict(queries.Preference(thing=thing, evidence=queries.evidence_for(session, thing.id)))


@reli_mcp.tool()
def add_preference_evidence(actor: McpActor, preference_id: uuid.UUID, evidence_id: uuid.UUID) -> dict[str, Any]:
    """Link one more piece of evidence to a preference the user has just reinforced.

    Adding the same evidence twice changes nothing: strength is the count of these links, so a
    repeat would overstate the preference rather than confirm it.

    Args:
        actor: 'claude_interactive' or 'claude_scheduled'. Required.
        preference_id: The preference being reinforced.
        evidence_id: The Thing that reinforces it. Not the preference itself.

    Returns:
        The preference with its evidence and its new count.
    """
    with _session() as session:
        thing = service.add_preference_evidence(
            session,
            actor=_actor(actor),
            preference_id=preference_id,
            evidence_id=evidence_id,
        )
        return _preference_dict(queries.Preference(thing=thing, evidence=queries.evidence_for(session, thing.id)))


@reli_mcp.tool()
def reject_preference(actor: McpActor, preference_id: uuid.UUID) -> dict[str, Any]:
    """Tag a preference #Rejected when the user says it is wrong, and journal the rejection.

    The preference stays in the graph and stays readable, so the user can see what was rejected and
    so it is not derived again. Rejecting one twice changes nothing.

    Args:
        actor: 'claude_interactive' or 'claude_scheduled'. Required — this records who performed
            the rejection, which is you, relaying it.
        preference_id: The preference the user rejected.

    Returns:
        The rejected preference, with its evidence still attached.
    """
    with _session() as session:
        thing = service.reject_preference(session, actor=_actor(actor), preference_id=preference_id)
        return _preference_dict(queries.Preference(thing=thing, evidence=queries.evidence_for(session, thing.id)))


@reli_mcp.tool()
def get_user_model(scope: str | None = None, include_rejected: bool = False) -> dict[str, Any]:
    """What Reli knows about the user: their preferences and the evidence behind each one.

    Pass a scope to load what this session needs rather than everything — 'scheduling' for daily
    planning, not naming conventions. Matching is exact apart from case, so use the scope labels
    already in the model.

    Args:
        scope: Only preferences declaring this scope; omitted returns all of them.
        include_rejected: Include preferences the user has rejected. Pass true before deriving a
            new preference, so you can see what has already been refused.

    Returns:
        {"scope": ..., "preferences": [...]} — each preference with its scope, whether it is
        rejected, its evidence and the count of it. There is no confidence score.
    """
    return _user_model_payload(scope=scope, include_rejected=include_rejected)


@reli_mcp.resource(
    "reli://user-model",
    name="user-model",
    description="Every preference Reli holds about the user, with the evidence behind each one.",
    mime_type="application/json",
)
def user_model_resource() -> dict[str, Any]:
    """The whole user model, loadable as context without a tool call.

    Rejected preferences are left out: a resource is ambient context, and what the user refused is
    not what they prefer. get_user_model(include_rejected=true) is where they are visible.
    """
    return _user_model_payload()


@reli_mcp.resource(
    "reli://user-model/{scope}",
    name="user-model-scoped",
    description="The user's preferences for one scope, with the evidence behind each one.",
    mime_type="application/json",
)
def scoped_user_model_resource(scope: str) -> dict[str, Any]:
    """One scope of the user model, for a session that only needs part of it."""
    return _user_model_payload(scope=scope)


# --- The default behaviour, and the hats ------------------------------------
#
# The text lives in backend.prompts; these register it. A prompt reaches a session only when the
# user picks it, so the default behaviour is a tool as well: any session can call it, and nothing
# outside this repository needs to restate it. Each prompt's description names the preference
# scope it loads, because the description is what a connected session shows before the prompt is
# picked.


@reli_mcp.tool()
def get_initial_instructions() -> str:
    """How to behave as the user's assistant with Reli attached. Call this first, every session.

    Returns the default behaviour — what is worth a Thing, how to title and tag it, when to relate
    rather than create, when to set a check-in date and what one means, how to record a
    preference, which actor to write as — and names the three prompts to load when the
    conversation turns to daily planning, project planning or review. It reads nothing from the
    graph: loading the user model is the first thing the text tells you to do.
    """
    return prompts.initial_instructions()


@reli_mcp.prompt(
    name="capture",
    title="Capture",
    description=(
        "The default behaviour: what is worth a Thing, how to title and tag it, when to set a "
        f"check-in date, and when to relate rather than create. Loads the '{prompts.CAPTURE_SCOPE}' "
        "preference scope."
    ),
)
def capture_prompt() -> str:
    return prompts.capture()


@reli_mcp.prompt(
    name="daily-planning",
    title="Daily planning",
    description=(
        "The daily hat: resolves what is due for check-in, then shapes a plan for the day. "
        f"Loads the '{prompts.SCHEDULING_SCOPE}' preference scope."
    ),
)
def daily_planning_prompt() -> str:
    return prompts.daily_planning()


@reli_mcp.prompt(
    name="project-planning",
    title="Project planning",
    description=(
        "The project hat: breaks a piece of work into Things related by ChildOf and Blocks, each "
        f"with a check-in date. Loads the '{prompts.PLANNING_SCOPE}' preference scope."
    ),
)
def project_planning_prompt() -> str:
    return prompts.project_planning()


@reli_mcp.prompt(
    name="review",
    title="Review",
    description=(
        "The review hat: walks a part of the graph, archives what is done and re-dates what has "
        f"drifted. Loads the '{prompts.REVIEW_SCOPE}' preference scope."
    ),
)
def review_prompt() -> str:
    return prompts.review()


# --- Transport -------------------------------------------------------------


_EXPIRED = (
    "Access token expired: the connector refreshes it at /oauth/token with its refresh token, "
    "or re-authorises against Google"
)
_NOT_OURS = "Not a token this Reli issued: authorise the connector against Google via the authorization server"
_CLOSED = "/mcp is closed: a human sets SECRET_KEY and the Google sign-in settings (CLAUDE.md)"
_NO_BEARER = (
    "Authorization required: a Bearer of the access token the authorization server at /oauth/token "
    "issues after a Google sign-in"
)


class _BearerTokenMiddleware:
    """Requires ``Authorization: Bearer <credential>`` on every request to the mounted app.

    The one credential is an ``aud="mcp"`` JWT minted by the authorization server in
    :mod:`backend.mcp_oauth` after a Google sign-in.

    An unset ``SECRET_KEY`` closes the endpoint rather than opening it: there is no dev-mode bypass,
    because /mcp is the only write path into the graph and it is publicly reachable. Every 401 says
    what a human or the connector must do next, and names the RFC 9728 resource metadata when a
    base URL is configured, which is how an MCP client discovers the authorization server.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Read the secret per request, not at construction: the app is built at import time, so a
        # value captured then could never be corrected.
        if not settings.SECRET_KEY:
            await _refuse(scope, receive, send, _CLOSED)
            return
        header = dict(scope.get("headers", [])).get(b"authorization", b"").decode()
        provided = header[7:] if header.startswith("Bearer ") else ""
        if not provided:
            await _refuse(scope, receive, send, _NO_BEARER)
            return
        try:
            auth.decode_jwt(provided, audience=auth.MCP_AUDIENCE)
        except jwt.ExpiredSignatureError:
            await _refuse(scope, receive, send, _EXPIRED, error="invalid_token")
            return
        except jwt.InvalidTokenError:
            await _refuse(scope, receive, send, _NOT_OURS, error="invalid_token")
            return
        await self._app(scope, receive, send)


async def _refuse(scope: Scope, receive: Receive, send: Send, description: str, error: str | None = None) -> None:
    """A 401 whose body is the remedy and whose ``WWW-Authenticate`` follows RFC 6750 §3 and RFC 9728."""
    challenge = 'Bearer realm="reli"'
    base = auth.base_url()
    if base:
        challenge += f', resource_metadata="{base}/.well-known/oauth-protected-resource"'
    if error:
        challenge += f', error="{error}", error_description="{description}"'
    response = Response(
        content=json.dumps({"detail": description}),
        status_code=401,
        media_type="application/json",
        headers={"WWW-Authenticate": challenge},
    )
    await response(scope, receive, send)


def create_mcp_asgi_app() -> ASGIApp:
    """The streamable-HTTP MCP app behind the bearer check, for ``app.mount("/mcp", ...)``."""
    if not settings.SECRET_KEY:
        logger.warning("SECRET_KEY is not set: /mcp will answer 401 to every request.")
    elif missing := auth.missing_sign_in_settings():
        logger.warning("SECRET_KEY is set but %s is not: the OAuth sign-in cannot complete.", ", ".join(missing))
    return _BearerTokenMiddleware(reli_mcp.streamable_http_app())
