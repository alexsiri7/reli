"""The read-only HTTP surface the web view consumes, and the one write it is allowed.

The frontend does not speak MCP (docs/vision.md §4.4): it reads these routes, which are thin
wrappers over :mod:`backend.queries`. Nothing here constructs or mutates a record — the single
mutation, rejecting a preference, goes through :mod:`backend.service` like every other write, so the
journal keeps one story about who did what.

``Actor.USER`` is used by that one route and nowhere else. It is the whole reason a rejection relayed
through Claude and a rejection the user made themselves are distinguishable in the journal, which is
the learning pass's only signal for "the user decided".

Everything here sits behind :func:`add_web_view_auth`: the service is publicly reachable and these
routes serve the user's whole graph. A request is admitted by the ``reli_session`` cookie the Google
sign-in sets, and by nothing else. The bundle itself is public — it is the sign-in view — and so is
``/api/auth/``, which is how a browser gets a session, and ``/api/heartbeats``, which is read by a
GitHub Actions watchdog that holds no credential; see :func:`_is_guarded`.
"""

from __future__ import annotations

import json
import logging
import pathlib
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session
from starlette.requests import Request
from starlette.responses import FileResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from . import auth, queries, service
from .db_engine import get_engine
from .db_models import (
    OBSERVATION_TAG,
    PREFERENCE_TAG,
    USER_TAG,
    Actor,
    EntityType,
    Operation,
    RelationshipRecord,
    RelationshipType,
    ThingRecord,
)

logger = logging.getLogger(__name__)

#: The tree is for the user's own Things. Without this the ``#User`` anchor, every preference and
#: every ``#Observation`` would sit at the top level, because nothing claims them as a child — and
#: the user model has its own view. The tags are the constants the write path uses, so the two
#: cannot drift.
TREE_EXCLUDED_TAGS = (USER_TAG, PREFERENCE_TAG, OBSERVATION_TAG)

_EVERY_METHOD = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


# --- Response models -------------------------------------------------------
#
# Stated explicitly rather than returning the records: the HTTP boundary is what the TypeScript
# types are written against, so a new database column is not silently a new API field.


class _FromRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class NeighbourOut(_FromRecord):
    """The far end of an edge, or a piece of evidence: enough to label a link and follow it."""

    id: uuid.UUID
    title: str
    tags: list[str]


class ThingSummary(_FromRecord):
    """A Thing as one row of the tree."""

    id: uuid.UUID
    title: str
    tags: list[str]
    priority: float
    active: bool
    checkin_date: date | None
    has_children: bool


class TreeLevel(BaseModel):
    things: list[ThingSummary]


class HeartbeatOut(_FromRecord):
    """One scheduled pass's heartbeat: what tells a run that happened from one that did not, only."""

    id: uuid.UUID
    title: str
    checkin_date: date | None


class HeartbeatsOut(BaseModel):
    heartbeats: list[HeartbeatOut]


class ThingOut(_FromRecord):
    """A whole Thing, for the detail view and the user model's preference cards."""

    id: uuid.UUID
    title: str
    description: str | None
    notes: dict[str, str]
    tags: list[str]
    urls: dict[str, str]
    checkin_date: date | None
    priority: float
    active: bool
    created_at: datetime
    updated_at: datetime


class RelationshipOut(BaseModel):
    """One edge touching the requested Thing, with its direction resolved relative to that Thing."""

    id: uuid.UUID
    relationship_type: RelationshipType
    direction: Literal["outgoing", "incoming"]
    context: str | None
    created_at: datetime
    other: NeighbourOut


class ThingDetail(BaseModel):
    thing: ThingOut
    relationships: list[RelationshipOut]


class JournalEntryOut(_FromRecord):
    """One journalled mutation, including the actor the view attributes it to."""

    id: int
    occurred_at: datetime
    actor: Actor
    operation: Operation
    entity_type: EntityType
    entity_id: uuid.UUID
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class HistoryOut(BaseModel):
    entries: list[JournalEntryOut]
    total: int
    truncated: bool


class PreferenceOut(BaseModel):
    """A preference with the evidence behind it. ``evidence_count`` is the strength; there is no score."""

    thing: ThingOut
    scope: str | None
    rejected: bool
    evidence: list[NeighbourOut]
    evidence_count: int


class UserModelOut(BaseModel):
    scope: str | None
    preferences: list[PreferenceOut]


@contextmanager
def _session() -> Iterator[Session]:
    """The session a route runs in. Tests patch this to bind the routes to the fixture session."""
    with Session(get_engine()) as session:
        yield session


def _summary(node: queries.TreeNode) -> ThingSummary:
    thing = node.thing
    return ThingSummary(
        id=thing.id,
        title=thing.title,
        tags=thing.tags,
        priority=thing.priority,
        active=thing.active,
        checkin_date=thing.checkin_date,
        has_children=node.child_count > 0,
    )


def _relationship(
    edge: RelationshipRecord, thing_id: uuid.UUID, others: dict[uuid.UUID, ThingRecord]
) -> RelationshipOut:
    outgoing = edge.source_thing_id == thing_id
    other_id = edge.target_thing_id if outgoing else edge.source_thing_id
    return RelationshipOut(
        id=edge.id,
        relationship_type=edge.relationship_type,
        direction="outgoing" if outgoing else "incoming",
        context=edge.context,
        created_at=edge.created_at,
        other=NeighbourOut.model_validate(others[other_id]),
    )


def _preference(preference: queries.Preference) -> PreferenceOut:
    return PreferenceOut(
        thing=ThingOut.model_validate(preference.thing),
        scope=preference.scope,
        rejected=preference.rejected,
        evidence=[NeighbourOut.model_validate(thing) for thing in preference.evidence],
        evidence_count=preference.evidence_count,
    )


def _history(found: queries.History) -> HistoryOut:
    return HistoryOut(
        entries=[JournalEntryOut.model_validate(entry) for entry in found.entries],
        total=found.total,
        truncated=found.truncated,
    )


router = APIRouter(prefix="/api", tags=["web view"])


@router.get("/things", summary="One level of the ChildOf tree")
def tree_level(parent: uuid.UUID | None = None) -> TreeLevel:
    """The children of *parent*, or the top level of the tree when it is omitted.

    The top level is the active Things nothing claims as a child, less the user-model tags in
    ``TREE_EXCLUDED_TAGS``. One level per request, most important first; ``has_children`` says
    whether expanding a row will show anything, so a leaf never offers an expansion that is empty.
    """
    with _session() as session:
        nodes = queries.tree_level(session, parent_id=parent, exclude_tags=TREE_EXCLUDED_TAGS)
        return TreeLevel(things=[_summary(node) for node in nodes])


@router.get("/things/{thing_id}", summary="One Thing and every edge touching it")
def thing_detail(thing_id: uuid.UUID) -> ThingDetail:
    """A Thing with every edge on it, each carrying the far end's title so it can be a link.

    ``direction`` is resolved here, against the requested Thing, so the view never re-derives what a
    ``ChildOf`` edge means and the two cannot disagree about it.
    """
    with _session() as session:
        thing = session.get(ThingRecord, thing_id)
        if thing is None:
            raise HTTPException(status_code=404, detail=f"no Thing with id {thing_id}")

        edges = queries.relationships_for(session, thing_id)
        others = queries.things_by_id(session, _far_ends(edges, thing_id))
        return ThingDetail(
            thing=ThingOut.model_validate(thing),
            relationships=[_relationship(edge, thing_id, others) for edge in edges],
        )


def _far_ends(edges: Sequence[RelationshipRecord], thing_id: uuid.UUID) -> list[uuid.UUID]:
    return [edge.target_thing_id if edge.source_thing_id == thing_id else edge.source_thing_id for edge in edges]


@router.get("/things/{thing_id}/history", summary="A Thing's journal history")
def thing_history(thing_id: uuid.UUID, limit: int = Query(default=200, ge=1, le=1000)) -> HistoryOut:
    """How a Thing got to its current state: its newest *limit* journal entries, oldest first.

    Only entries recorded against the Thing itself. Relating and unrelating are journalled against
    the **relationship**, so edge changes do not appear here — the same limitation
    ``get_thing_history`` has over MCP, and the detail view shows the edges as they stand now.

    An id with no entries answers with no entries and a total of zero rather than a 404: whether the
    Thing exists is what ``GET /api/things/{thing_id}`` answers.
    """
    with _session() as session:
        return _history(queries.history(session, thing_id, limit))


@router.get("/user-model", summary="Every preference with its evidence")
def user_model(scope: str | None = None) -> UserModelOut:
    """The user's preferences, each with the evidence behind it and whether it has been rejected.

    Rejected preferences are **always** included: the view's job is to make a wrong preference
    spottable, so it shows them rather than hiding them, visually distinct. That is why there is no
    ``include_rejected`` parameter — the MCP resource's default is right for ambient context and
    wrong here.

    ``queries.user_model`` drops any preference with no evidence or a blank scope, so such a Thing
    cannot appear here. That is deliberate — an evidence-less preference is the confidence float
    this design exists to avoid — and not a missing row.
    """
    with _session() as session:
        preferences = queries.user_model(session, scope=scope, include_rejected=True)
        return UserModelOut(scope=scope, preferences=[_preference(preference) for preference in preferences])


@router.get("/heartbeats", summary="The scheduled passes' heartbeats")
def heartbeats() -> HeartbeatsOut:
    """The active ``#ScheduledTask`` Things, by title. **The one unauthenticated ``/api`` route.**

    The scheduled-pass watchdog in ``.github/workflows/scheduled-run-health.yml`` runs in GitHub
    Actions, which holds no Google session and cannot obtain one, so this answers without a
    credential. What it exposes is the three heartbeats' titles and check-in dates — written by
    Reli's own prompts, not by the user — which is why opening it costs the graph nothing.

    An archived heartbeat is absent, exactly as it is absent from the tree, so archiving one reads
    as a missed run. No heartbeats is an empty list: "a pass has never run" is the watchdog's
    judgement to make, not a 404 here.
    """
    with _session() as session:
        found = queries.scheduled_tasks(session)
        return HeartbeatsOut(heartbeats=[HeartbeatOut.model_validate(thing) for thing in found])


@router.post("/preferences/{preference_id}/reject", summary="Reject a preference")
def reject_preference(preference_id: uuid.UUID) -> PreferenceOut:
    """Tag a preference ``#Rejected`` as the user, and journal it. The only write in the web view.

    Attributed to ``Actor.USER`` because the user performed it — over MCP the same rejection records
    the Claude session that relayed it, and keeping those apart is the point.

    Rejecting an already-rejected preference is a 200 that changes and journals nothing. A Thing that
    exists but is not tagged ``#Preference`` is a 404: the path names a preference, and there is no
    preference there.
    """
    with _session() as session:
        try:
            thing = service.reject_preference(session, actor=Actor.USER, preference_id=preference_id)
        except service.ThingNotFound as missing:
            raise HTTPException(status_code=404, detail=str(missing)) from missing
        except ValueError as not_a_preference:
            raise HTTPException(status_code=404, detail=str(not_a_preference)) from not_a_preference

        return _preference(queries.Preference(thing=thing, evidence=queries.evidence_for(session, thing.id)))


@router.api_route("/{unmatched:path}", methods=_EVERY_METHOD, include_in_schema=False, response_model=None)
def unmatched_api_route(unmatched: str) -> Response:
    """Refuse an ``/api`` path that is not a route above, rather than letting the SPA fallback take it.

    Registered last, so it only sees what nothing else matched. Without it a typo'd endpoint answers
    ``200 text/html`` and the browser reports a JSON parse error that names nothing.
    """
    raise HTTPException(status_code=404, detail=f"no /api route at /{unmatched}")


# --- Serving the built frontend --------------------------------------------


def mount_frontend(app: FastAPI, dist: pathlib.Path) -> None:
    """Serve the Vite bundle in *dist*, with every unmatched path falling back to ``index.html``.

    Call this **last**: the fallback matches everything, so any route registered after it is dead.

    A missing or incomplete build is not an error — local development and the test suite run without
    one. Nothing is mounted and the API still serves.
    """
    index = dist / "index.html"
    assets = dist / "assets"
    if not (index.is_file() and assets.is_dir()):
        logger.warning("No frontend build at %s: the web view is not served.", dist)
        return

    app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{spa_path:path}", include_in_schema=False)
    def spa(spa_path: str) -> FileResponse:
        """Hand every path the bundle, so a reload on /things/<uuid> resolves client-side."""
        return FileResponse(index)


# --- Access control --------------------------------------------------------


#: What the check guards: the graph, which only ``/api`` serves. The bundle is static code from a
#: public repository and is the sign-in view, so it answers everyone; ``/api/auth/`` is how a
#: browser gets a session, so it must answer before there is one, and ``/api/heartbeats`` is read by
#: a watchdog that cannot hold one. ``/healthz``, ``/mcp``, ``/.well-known/`` and ``/oauth/`` were
#: never the web view's to guard — ``/mcp`` carries its own bearer check. The prefix ends in a slash
#: so ``/api/auth`` cannot be widened into ``/api/authors``, and the path is matched whole so
#: ``/api/heartbeats-and-everything-else`` is not exempt either.
_GUARDED_PREFIX = "/api/"
_PUBLIC_PREFIX = "/api/auth/"
_PUBLIC_PATH = "/api/heartbeats"

_NO_CREDENTIAL = "Not signed in: sign in with Google at /."


def _is_guarded(path: str) -> bool:
    if path == _PUBLIC_PATH or path.startswith(_PUBLIC_PREFIX):
        return False
    return path == "/api" or path.startswith(_GUARDED_PREFIX)


def _refusal(request: Request) -> str | None:
    """Why the request is not admitted, or ``None`` when the ``reli_session`` cookie admits it."""
    try:
        if auth.web_session(request) is not None:
            return None
    except auth.SessionRefused as refused:
        return str(refused)
    return _NO_CREDENTIAL


class _WebViewAuthMiddleware:
    """Requires the ``reli_session`` cookie on every ``/api`` path outside the public ones.

    The cookie is the only credential: there is no HTTP Basic password any more (#1471), so nothing
    but a Google sign-in opens the graph. Nothing configured closes it rather than opening it —
    there is no dev-mode bypass, because these routes serve the user's whole graph and the deploy
    URLs answer the public internet.

    The 401 carries no ``WWW-Authenticate``: a challenge would make the browser pop its own
    credential prompt over the sign-in view. The body says what admits a request instead.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_guarded(scope.get("path", "")):
            await self._app(scope, receive, send)
            return

        reason = _refusal(Request(scope))
        if reason is not None:
            response = Response(content=json.dumps({"detail": reason}), status_code=401, media_type="application/json")
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)


def add_web_view_auth(app: FastAPI) -> None:
    """Put every ``/api`` route outside ``/api/auth/`` and ``/api/heartbeats`` behind the session."""
    missing = auth.missing_sign_in_settings()
    if missing:
        logger.warning(
            "The Google sign-in is missing %s: /api will answer 401 to every request.",
            ", ".join(missing),
        )
    app.add_middleware(_WebViewAuthMiddleware)
