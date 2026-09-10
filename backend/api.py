"""The read-only HTTP surface the web view consumes, and the one write it is allowed.

The frontend does not speak MCP (docs/vision.md §4.4): it reads these routes, which are thin
wrappers over :mod:`backend.queries`. Nothing here constructs or mutates a record — the single
mutation, rejecting a preference, goes through :mod:`backend.service` like every other write, so the
journal keeps one story about who did what.

``Actor.USER`` is used by that one route and nowhere else. It is the whole reason a rejection relayed
through Claude and a rejection the user made themselves are distinguishable in the journal, which is
the learning pass's only signal for "the user decided".

Everything here except ``/healthz`` and ``/mcp`` sits behind :func:`add_web_view_auth`: the service
is publicly reachable and these routes serve the user's whole graph.
"""

from __future__ import annotations

import base64
import binascii
import logging
import pathlib
import secrets
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session
from starlette.responses import FileResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from . import queries, service
from .config import settings
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
    return ThingSummary(
        **ThingOut.model_validate(node.thing).model_dump(
            include={"id", "title", "tags", "priority", "active", "checkin_date"}
        ),
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


def _is_exempt(path: str) -> bool:
    """``/healthz`` is polled unauthenticated by the deploy pipeline; ``/mcp`` carries its own bearer check."""
    return path == "/healthz" or path == "/mcp" or path.startswith("/mcp/")


def _basic_password(header: str) -> str:
    """The password out of an ``Authorization: Basic`` header; empty for anything else.

    The username is ignored: Reli has one user, so there are no accounts to tell apart.
    """
    if not header.startswith("Basic "):
        return ""
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return ""
    _, separator, password = decoded.partition(":")
    return password if separator else ""


class _BasicAuthMiddleware:
    """Requires HTTP Basic with ``WEB_UI_PASSWORD`` on every path but ``/healthz`` and ``/mcp``.

    An unset password closes the view rather than opening it: there is no dev-mode bypass, because
    these routes serve the user's whole graph and the deploy URLs answer the public internet.

    Guarding the static bundle as well as ``/api`` is what makes this work with no login view — the
    browser gets a 401 on ``/``, prompts once, and then carries the header on the XHRs too.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or _is_exempt(scope.get("path", "")):
            await self._app(scope, receive, send)
            return

        # Read the password per request, not at construction: the app is built at import time, so a
        # value captured then could never be corrected.
        expected = settings.WEB_UI_PASSWORD
        header = dict(scope.get("headers", [])).get(b"authorization", b"").decode()

        if not expected or not secrets.compare_digest(_basic_password(header), expected):
            response = Response(
                content='{"detail":"Unauthorized"}',
                status_code=401,
                media_type="application/json",
                headers={"WWW-Authenticate": 'Basic realm="reli"'},
            )
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)


def add_web_view_auth(app: FastAPI) -> None:
    """Put every route but ``/healthz`` and ``/mcp`` behind the Basic check."""
    if not settings.WEB_UI_PASSWORD:
        logger.warning("WEB_UI_PASSWORD is not set: the web view and /api will answer 401 to every request.")
    app.add_middleware(_BasicAuthMiddleware)
