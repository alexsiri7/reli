"""Read-only, indexed queries over the graph.

Every function here answers a question with an index, not a search and never a model. They are the
deterministic half of Reli: the caller decides what the answer means.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal, NamedTuple

from sqlalchemy import Table, func, text
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session, SQLModel, col, or_, select

from .db_models import (
    PREFERENCE_TAG,
    REJECTED_TAG,
    USER_ANCHOR_ID,
    JournalRecord,
    RelationshipRecord,
    RelationshipType,
    ThingRecord,
)

_THINGS: Table = SQLModel.metadata.tables["things"]
_TAGS = _THINGS.c["tags"]
_NOTES = _THINGS.c["notes"]


class RelatedThing(NamedTuple):
    """A Thing reached from an origin, with the hop count and the edge type that reached it."""

    thing: ThingRecord
    depth: int
    relationship_type: RelationshipType


class History(NamedTuple):
    """A window onto one entity's journal, with ``total`` so a capped answer cannot pass for a whole one."""

    entries: list[JournalRecord]
    total: int

    @property
    def truncated(self) -> bool:
        """Whether older entries were left out of this window."""
        return self.total > len(self.entries)


class Preference(NamedTuple):
    """A preference Thing with the evidence pointing at it.

    Strength is ``evidence_count`` — the number of ``EvidenceFor`` edges, read off the edges
    themselves. There is no stored number, so there is nothing that can drift from what it counts.
    """

    thing: ThingRecord
    evidence: list[ThingRecord]

    @property
    def scope(self) -> str | None:
        """What the preference applies to; never ``None`` in a :func:`user_model` row, which requires it."""
        return self.thing.notes.get("scope")

    @property
    def rejected(self) -> bool:
        """Whether the user has rejected it. Rejected preferences stay readable."""
        return REJECTED_TAG in self.thing.tags

    @property
    def evidence_count(self) -> int:
        """How many Things support this preference."""
        return len(self.evidence)


def _tagged(tags: Sequence[str], match: Literal["any", "all"]) -> ColumnElement[bool]:
    """The tag condition both tag-filtering queries run, so a change to it cannot reach only one."""
    wanted = list(tags)
    return _TAGS.contains(wanted) if match == "all" else _TAGS.has_any(array(wanted))


def due_for_checkin(session: Session, as_of: date) -> list[ThingRecord]:
    """Active Things whose ``checkin_date`` has arrived, most important first."""
    statement = (
        select(ThingRecord)
        .where(col(ThingRecord.active).is_(True), col(ThingRecord.checkin_date) <= as_of)
        .order_by(col(ThingRecord.priority).desc())
    )
    return list(session.exec(statement).all())


def stale(session: Session, since: datetime) -> list[ThingRecord]:
    """Active Things untouched since *since*, longest untouched first."""
    statement = (
        select(ThingRecord)
        .where(col(ThingRecord.active).is_(True), col(ThingRecord.updated_at) < since)
        .order_by(col(ThingRecord.updated_at).asc())
    )
    return list(session.exec(statement).all())


def by_tag(
    session: Session,
    tags: Sequence[str],
    match: Literal["any", "all"] = "any",
) -> list[ThingRecord]:
    """Things carrying these tags — any of them by default, all of them on ``match="all"``.

    An empty *tags* returns nothing rather than everything: "matches none of no tags" is the
    answer that cannot be mistaken for an unfiltered listing.
    """
    if not tags:
        return []

    statement = select(ThingRecord).where(_tagged(tags, match)).order_by(col(ThingRecord.priority).desc())
    return list(session.exec(statement).all())


def blocked(session: Session) -> list[ThingRecord]:
    """Things held up by something unfinished.

    A ``Blocks`` edge runs from the blocked Thing to whatever blocks it, so these are the *sources*
    of ``Blocks`` edges whose target is still active. Once the blocker is archived the Thing is no
    longer blocked and drops out.
    """
    blocker = _THINGS.alias("blocker")
    statement = (
        select(ThingRecord)
        .distinct()
        .join(RelationshipRecord, col(RelationshipRecord.source_thing_id) == col(ThingRecord.id))
        .join(blocker, blocker.c["id"] == col(RelationshipRecord.target_thing_id))
        .where(
            col(RelationshipRecord.relationship_type) == RelationshipType.BLOCKS,
            blocker.c["active"].is_(True),
        )
        .order_by(col(ThingRecord.priority).desc())
    )
    return list(session.exec(statement).all())


_RELATED_WALK = text(
    """
    WITH RECURSIVE walk(thing_id, depth, relationship_type, path) AS (
        SELECT
            CASE WHEN r.source_thing_id = :origin THEN r.target_thing_id ELSE r.source_thing_id END,
            1,
            r.relationship_type,
            ARRAY[:origin]::uuid[]
        FROM relationships r
        WHERE (r.source_thing_id = :origin OR r.target_thing_id = :origin)
          AND r.relationship_type = ANY(:types)
      UNION ALL
        SELECT
            CASE WHEN r.source_thing_id = w.thing_id THEN r.target_thing_id ELSE r.source_thing_id END,
            w.depth + 1,
            r.relationship_type,
            w.path || w.thing_id
        FROM walk w
        JOIN relationships r
          ON r.source_thing_id = w.thing_id OR r.target_thing_id = w.thing_id
        WHERE w.depth < :max_depth
          AND NOT (CASE WHEN r.source_thing_id = w.thing_id THEN r.target_thing_id ELSE r.source_thing_id END
                   = ANY(w.path))
          AND r.relationship_type = ANY(:types)
    )
    SELECT DISTINCT ON (thing_id) thing_id, depth, relationship_type
    FROM walk
    WHERE thing_id <> :origin
    ORDER BY thing_id, depth
    """
)


def related(
    session: Session,
    thing_id: uuid.UUID,
    types: Sequence[RelationshipType] | None = None,
    depth: int = 1,
) -> list[RelatedThing]:
    """Things reachable from *thing_id* within *depth* hops, nearest hop first.

    Edges are followed in **both** directions: a Thing's neighbourhood includes what points at it,
    not only what it points at. The origin is never returned, and a Thing already on the path is
    not revisited, so cycles terminate. ``types=None`` traverses every relationship type.

    A Thing reached by several edges is returned once, at its shortest depth; which of the tying
    edges supplies ``relationship_type`` is unspecified. Pass *types* to make that deterministic.
    """
    if depth < 1:
        return []

    wanted = [t.value for t in (types if types is not None else list(RelationshipType))]
    if not wanted:
        return []

    rows = (
        session.connection()
        .execute(
            _RELATED_WALK,
            {"origin": thing_id, "types": wanted, "max_depth": depth},
        )
        .all()
    )
    if not rows:
        return []

    found = {row[0]: (row[1], RelationshipType(row[2])) for row in rows}
    things = session.exec(select(ThingRecord).where(col(ThingRecord.id).in_(found))).all()

    results = [RelatedThing(thing, found[thing.id][0], found[thing.id][1]) for thing in things]
    results.sort(key=lambda r: (r.depth, r.thing.title))
    return results


def children(session: Session, thing_id: uuid.UUID) -> list[ThingRecord]:
    """The children of a Thing, for the tree view.

    A ``ChildOf`` edge runs from the parent to the child, so the children of *thing_id* are the
    **targets** of its ``ChildOf`` edges (issue #1408: "targets of ``ChildOf``, for the tree view").
    """
    statement = (
        select(ThingRecord)
        .join(RelationshipRecord, col(RelationshipRecord.target_thing_id) == col(ThingRecord.id))
        .where(
            col(RelationshipRecord.source_thing_id) == thing_id,
            col(RelationshipRecord.relationship_type) == RelationshipType.CHILD_OF,
        )
        .order_by(col(ThingRecord.priority).desc())
    )
    return list(session.exec(statement).all())


def relationships_for(session: Session, thing_id: uuid.UUID) -> list[RelationshipRecord]:
    """Every edge touching a Thing, in either direction, oldest first.

    Both halves are returned because an edge is as much a fact about its target as about its
    source; :class:`~backend.db_models.RelationshipType` says which reading applies to each type.
    """
    statement = (
        select(RelationshipRecord)
        .where(
            or_(
                col(RelationshipRecord.source_thing_id) == thing_id,
                col(RelationshipRecord.target_thing_id) == thing_id,
            )
        )
        .order_by(col(RelationshipRecord.created_at).asc(), col(RelationshipRecord.id).asc())
    )
    return list(session.exec(statement).all())


def find_things(
    session: Session,
    *,
    tags: Sequence[str] | None = None,
    match: Literal["any", "all"] = "any",
    active: bool | None = True,
    checkin_from: date | None = None,
    checkin_to: date | None = None,
    priority_min: float | None = None,
    priority_max: float | None = None,
    limit: int = 100,
) -> list[ThingRecord]:
    """Things matching every filter that was given, most important first.

    An empty or omitted *tags* means "no tag filter" and returns Things regardless of their tags —
    the opposite of :func:`by_tag`, which reads an empty *tags* as "matches none of no tags" and
    returns nothing. The two differ because this is the general listing query, where omitting a
    filter must not empty the result, and ``by_tag`` answers one question about specific tags.

    ``active=None`` drops the active filter and returns archived Things alongside live ones.
    """
    conditions = []
    if tags:
        conditions.append(_tagged(tags, match))
    if active is not None:
        conditions.append(col(ThingRecord.active).is_(active))
    if checkin_from is not None:
        conditions.append(col(ThingRecord.checkin_date) >= checkin_from)
    if checkin_to is not None:
        conditions.append(col(ThingRecord.checkin_date) <= checkin_to)
    if priority_min is not None:
        conditions.append(col(ThingRecord.priority) >= priority_min)
    if priority_max is not None:
        conditions.append(col(ThingRecord.priority) <= priority_max)

    statement = (
        select(ThingRecord)
        .where(*conditions)
        .order_by(col(ThingRecord.priority).desc(), col(ThingRecord.title).asc())
        .limit(limit)
    )
    return list(session.exec(statement).all())


def history(session: Session, entity_id: uuid.UUID, limit: int = 200) -> History:
    """The most recent *limit* journal entries for one entity, oldest first within that window.

    The window is taken from the newest end: a Thing with more entries than *limit* loses its
    oldest, never the state it is in now. ``total`` is every entry the entity has, so a caller that
    got a capped answer can see that it did and ask again with a wider *limit*.

    Ordered by ``id`` rather than ``occurred_at``: two mutations inside one transaction share a
    timestamp, and the sequence is the point of the journal.
    """
    condition = col(JournalRecord.entity_id) == entity_id
    newest_first = session.exec(
        select(JournalRecord).where(condition).order_by(col(JournalRecord.id).desc()).limit(limit)
    ).all()
    total = session.exec(select(func.count()).select_from(JournalRecord).where(condition)).one()
    return History(entries=list(reversed(newest_first)), total=total)


def _evidence_by_preference(
    session: Session, preference_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[ThingRecord]]:
    """The evidence Things for each preference, in the order the evidence was attached.

    Two statements rather than one tuple-returning select: the edges carry the order, the Things
    carry the content, and joining them in Python keeps both ``session.exec`` calls returning a
    single model.
    """
    if not preference_ids:
        return {}

    edges = session.exec(
        select(RelationshipRecord)
        .where(
            col(RelationshipRecord.target_thing_id).in_(preference_ids),
            col(RelationshipRecord.relationship_type) == RelationshipType.EVIDENCE_FOR,
        )
        .order_by(col(RelationshipRecord.created_at).asc(), col(RelationshipRecord.id).asc())
    ).all()
    if not edges:
        return {}

    sources = {edge.source_thing_id for edge in edges}
    things = {
        thing.id: thing for thing in session.exec(select(ThingRecord).where(col(ThingRecord.id).in_(sources))).all()
    }

    found: dict[uuid.UUID, list[ThingRecord]] = {}
    for edge in edges:
        thing = things.get(edge.source_thing_id)
        if thing is not None:
            found.setdefault(edge.target_thing_id, []).append(thing)
    return found


def evidence_for(session: Session, thing_id: uuid.UUID) -> list[ThingRecord]:
    """The Things supporting *thing_id*, in the order they were attached to it.

    The sources of ``EvidenceFor`` edges pointing at it, which is how strength is counted.
    """
    return _evidence_by_preference(session, [thing_id]).get(thing_id, [])


def user_model(
    session: Session,
    *,
    scope: str | None = None,
    include_rejected: bool = False,
) -> list[Preference]:
    """The user's preferences, each with the evidence behind it, most important first.

    A preference is a ``#Preference`` Thing the ``#User`` anchor points at that carries a scope and
    at least one piece of evidence, so a graph with no anchor has no edges and returns an empty list
    — which is why a read never creates the anchor. Scope and evidence are floors on the read, not
    only on :func:`backend.service.record_preference`: the shape is a tag plus an edge type, both
    writable through ``create_thing`` and ``relate``, and an evidence-less preference passing for a
    recorded one is the confidence float this design exists to avoid.

    *scope* matches exactly, case aside: ``scheduling`` and ``scheduling-preferences`` are different
    scopes, because there is no text search anywhere in Reli. There is deliberately no limit —
    scope is the mechanism for loading what a session needs rather than everything.

    Rejected preferences are left out unless *include_rejected*, so the learning pass can ask for
    them and check it is not re-deriving ground the user already refused.

    ``notes->>'scope'`` is not indexed; the ``#Preference`` tag filter hits the existing GIN index
    first, and one user's preferences are a handful of rows.
    """
    conditions = [
        col(RelationshipRecord.source_thing_id) == USER_ANCHOR_ID,
        col(RelationshipRecord.relationship_type) == RelationshipType.RELATED_TO,
        _tagged([PREFERENCE_TAG], "all"),
        func.btrim(_NOTES["scope"].astext) != "",
    ]
    if scope is not None:
        conditions.append(func.lower(_NOTES["scope"].astext) == scope.strip().lower())
    if not include_rejected:
        conditions.append(~_TAGS.contains([REJECTED_TAG]))

    statement = (
        select(ThingRecord)
        .distinct()
        .join(RelationshipRecord, col(RelationshipRecord.target_thing_id) == col(ThingRecord.id))
        .where(*conditions)
        .order_by(col(ThingRecord.priority).desc(), col(ThingRecord.title).asc())
    )
    preferences = list(session.exec(statement).all())

    evidence = _evidence_by_preference(session, [preference.id for preference in preferences])
    return [Preference(thing=thing, evidence=evidence[thing.id]) for thing in preferences if thing.id in evidence]
