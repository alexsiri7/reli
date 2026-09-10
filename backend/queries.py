"""Read-only, indexed queries over the graph.

Every function here answers a question with an index, not a search and never a model. They are the
deterministic half of Reli: the caller decides what the answer means.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal, NamedTuple

from sqlalchemy import Table, text
from sqlalchemy.dialects.postgresql import array
from sqlmodel import Session, SQLModel, col, select

from .db_models import RelationshipRecord, RelationshipType, ThingRecord

_THINGS: Table = SQLModel.metadata.tables["things"]
_TAGS = _THINGS.c["tags"]


class RelatedThing(NamedTuple):
    """A Thing reached from an origin, with the hop count and the edge type that reached it."""

    thing: ThingRecord
    depth: int
    relationship_type: RelationshipType


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

    wanted = list(tags)
    condition = _TAGS.contains(wanted) if match == "all" else _TAGS.has_any(array(wanted))
    statement = select(ThingRecord).where(condition).order_by(col(ThingRecord.priority).desc())
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
