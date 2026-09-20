"""The only write path into the graph.

Every public function here writes its row and its journal entry in a single transaction, so there
is no way to change a Thing or a relationship without leaving a record of the change. Nothing
outside this module may construct or mutate ``ThingRecord`` / ``RelationshipRecord``;
``backend/tests/test_architecture.py`` enforces that.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from .db_models import (
    INTERNAL_TAGS,
    NEW_TAG,
    OWNER_TIMEZONE,
    PREFERENCE_TAG,
    REJECTED_TAG,
    USER_ANCHOR_ID,
    USER_TAG,
    Actor,
    EntityType,
    JournalRecord,
    Operation,
    RelationshipRecord,
    RelationshipType,
    ThingRecord,
)

__all__ = [
    "BACKFILL_PER_DAY",
    "Actor",
    "EntityType",
    "Operation",
    "ThingNotFound",
    "add_preference_evidence",
    "backfill_checkin_dates",
    "create_thing",
    "get_or_create_user_anchor",
    "record_preference",
    "reject_preference",
    "relate",
    "unrelate",
    "update_thing",
]


class ThingNotFound(LookupError):
    """Raised when a mutation names a Thing or relationship that does not exist."""


def _snapshot(record: ThingRecord | RelationshipRecord) -> dict[str, Any]:
    """Render a record as the JSON-safe dict the journal stores in ``before`` / ``after``."""
    return record.model_dump(mode="json")


def _journalled(
    session: Session,
    *,
    actor: Actor,
    operation: Operation,
    entity_type: EntityType,
    entity_id: uuid.UUID,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> JournalRecord:
    """Append the journal entry for a mutation. Called by every public function in this module."""
    entry = JournalRecord(
        occurred_at=datetime.now(UTC),
        actor=actor,
        operation=operation,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
    )
    session.add(entry)
    return entry


def _require_thing(session: Session, thing_id: uuid.UUID) -> ThingRecord:
    thing = session.get(ThingRecord, thing_id)
    if thing is None:
        raise ThingNotFound(f"no Thing with id {thing_id}")
    return thing


def _insert_thing(
    session: Session,
    *,
    actor: Actor,
    title: str,
    description: str | None = None,
    notes: dict[str, str] | None = None,
    tags: list[str] | None = None,
    urls: dict[str, str] | None = None,
    checkin_date: date | None = None,
    priority: float = 0.0,
    active: bool = True,
    thing_id: uuid.UUID | None = None,
) -> ThingRecord:
    """Add a Thing and its journal entry without committing, so several mutations can share one.

    Every public function in this module still commits; this half exists for the ones that must
    write more than one row or not write at all.
    """
    now = datetime.now(UTC)
    thing = ThingRecord(
        # An explicit ``id=None`` would defeat the field's default_factory, so pass one or neither.
        **({"id": thing_id} if thing_id is not None else {}),
        title=title,
        description=description,
        notes=notes if notes is not None else {},
        tags=tags if tags is not None else [],
        urls=urls if urls is not None else {},
        checkin_date=checkin_date,
        priority=priority,
        active=active,
        created_at=now,
        updated_at=now,
    )
    session.add(thing)
    session.flush()
    _journalled(
        session,
        actor=actor,
        operation=Operation.CREATE,
        entity_type=EntityType.THING,
        entity_id=thing.id,
        before=None,
        after=_snapshot(thing),
    )
    return thing


def _default_checkin_date(now: datetime) -> date:
    """Tomorrow as the owner would say it — the next ``OWNER_TIMEZONE`` day, not the next UTC day."""
    return now.astimezone(OWNER_TIMEZONE).date() + timedelta(days=1)


def create_thing(
    session: Session,
    *,
    actor: Actor,
    title: str,
    description: str | None = None,
    notes: dict[str, str] | None = None,
    tags: list[str] | None = None,
    urls: dict[str, str] | None = None,
    checkin_date: date | None = None,
    priority: float = 0.0,
    active: bool = True,
) -> ThingRecord:
    """Create a Thing and journal it as one ``create`` entry with no ``before``.

    A capture is what the owner has not yet been asked about (#1516): unless *tags* holds one of
    ``INTERNAL_TAGS``, it is tagged ``NEW_TAG``, and a missing *checkin_date* becomes tomorrow in
    ``OWNER_TIMEZONE`` so it comes up in the morning rather than never. A date given explicitly is
    kept as given, and Reli's own records get neither the tag nor the date.
    """
    tags = list(tags) if tags is not None else []
    if not any(tag in INTERNAL_TAGS for tag in tags):
        if NEW_TAG not in tags:
            tags.append(NEW_TAG)
        if checkin_date is None:
            checkin_date = _default_checkin_date(datetime.now(UTC))

    thing = _insert_thing(
        session,
        actor=actor,
        title=title,
        description=description,
        notes=notes,
        tags=tags,
        urls=urls,
        checkin_date=checkin_date,
        priority=priority,
        active=active,
    )
    session.commit()
    session.refresh(thing)
    return thing


def update_thing(
    session: Session,
    *,
    actor: Actor,
    thing_id: uuid.UUID,
    title: str | None = None,
    description: str | None = None,
    notes: dict[str, str] | None = None,
    tags: list[str] | None = None,
    urls: dict[str, str] | None = None,
    checkin_date: date | None = None,
    priority: float | None = None,
    active: bool | None = None,
) -> ThingRecord:
    """Update the fields that are given and journal the change as one ``update`` entry.

    Every field **replaces** the stored value; nothing is merged. Passing ``notes`` writes exactly
    that mapping, passing ``tags`` writes exactly that list. Merge semantics cannot express removal,
    so callers that want to add a note read the current value and pass the union.

    A field left as ``None`` is not touched, which means this function cannot clear a nullable
    field. Whoever needs an explicit clear adds it.
    """
    thing = _require_thing(session, thing_id)
    before = _snapshot(thing)

    updates = {
        "title": title,
        "description": description,
        "notes": notes,
        "tags": tags,
        "urls": urls,
        "checkin_date": checkin_date,
        "priority": priority,
        "active": active,
    }
    for name, value in updates.items():
        if value is not None:
            setattr(thing, name, value)
    thing.updated_at = datetime.now(UTC)

    session.add(thing)
    session.flush()
    _journalled(
        session,
        actor=actor,
        operation=Operation.UPDATE,
        entity_type=EntityType.THING,
        entity_id=thing.id,
        before=before,
        after=_snapshot(thing),
    )
    session.commit()
    session.refresh(thing)
    return thing


#: How many backfilled Things fall due on one day. The morning conversation asks about three to
#: five ``NEW_TAG`` Things a morning, so a day of the backfill is the size of one morning's batch.
BACKFILL_PER_DAY = 5


def backfill_checkin_dates(session: Session, *, now: datetime) -> int:
    """Date every active capture that has none, as #1516's default would have, and return the count.

    The one-off backfill for #1517: a Thing captured before the default existed has no check-in
    date and so never surfaces. Each such Thing outside ``INTERNAL_TAGS`` gets a date, spread
    ``BACKFILL_PER_DAY`` to a day from tomorrow in ``OWNER_TIMEZONE``, oldest capture first, so the
    backlog does not all fall due on one morning; one with no description is a bare capture that
    was never filled in, so it is marked ``NEW_TAG`` as well. Archived Things, Reli's own records
    and anything already dated are left alone, which is what makes a second run touch nothing.

    Every write is journalled as an ``update`` by ``Actor.CLAUDE_SCHEDULED``: a bulk pass
    attributed to ``user`` would read, to the learning pass, as the owner having touched every
    Thing in one second.

    Unlike the rest of this module this does not commit. It runs inside the migration's
    transaction, which commits or rolls back the whole backfill with the revision.
    """
    undated = session.exec(
        select(ThingRecord)
        .where(col(ThingRecord.active).is_(True), col(ThingRecord.checkin_date).is_(None))
        .order_by(col(ThingRecord.created_at).asc(), col(ThingRecord.id).asc())
    ).all()
    captures = [thing for thing in undated if not any(tag in INTERNAL_TAGS for tag in thing.tags)]

    first_date = _default_checkin_date(now)
    for position, thing in enumerate(captures):
        before = _snapshot(thing)
        thing.checkin_date = first_date + timedelta(days=position // BACKFILL_PER_DAY)
        if not thing.description and NEW_TAG not in thing.tags:
            thing.tags = [*thing.tags, NEW_TAG]
        thing.updated_at = now
        session.add(thing)
        session.flush()
        _journalled(
            session,
            actor=Actor.CLAUDE_SCHEDULED,
            operation=Operation.UPDATE,
            entity_type=EntityType.THING,
            entity_id=thing.id,
            before=before,
            after=_snapshot(thing),
        )
    session.flush()
    return len(captures)


def _insert_relationship(
    session: Session,
    *,
    actor: Actor,
    source_thing_id: uuid.UUID,
    target_thing_id: uuid.UUID,
    relationship_type: RelationshipType,
    context: str | None = None,
) -> RelationshipRecord:
    """Add a relationship and its journal entry without committing. See :func:`_insert_thing`."""
    relationship = RelationshipRecord(
        source_thing_id=source_thing_id,
        target_thing_id=target_thing_id,
        relationship_type=RelationshipType(relationship_type),
        context=context,
        created_at=datetime.now(UTC),
    )
    session.add(relationship)
    session.flush()
    _journalled(
        session,
        actor=actor,
        operation=Operation.RELATE,
        entity_type=EntityType.RELATIONSHIP,
        entity_id=relationship.id,
        before=None,
        after=_snapshot(relationship),
    )
    return relationship


def relate(
    session: Session,
    *,
    actor: Actor,
    source_thing_id: uuid.UUID,
    target_thing_id: uuid.UUID,
    relationship_type: RelationshipType,
    context: str | None = None,
) -> RelationshipRecord:
    """Create a relationship and journal it as one ``relate`` entry.

    See :class:`~backend.db_models.RelationshipType` for what source and target mean per type.

    Raises ``ValueError`` for a type outside the five, before any statement is issued, so callers
    that resolve the type from outside the process get the offending value back rather than a
    constraint violation.
    """
    relationship = _insert_relationship(
        session,
        actor=actor,
        source_thing_id=source_thing_id,
        target_thing_id=target_thing_id,
        relationship_type=relationship_type,
        context=context,
    )
    session.commit()
    session.refresh(relationship)
    return relationship


def unrelate(session: Session, *, actor: Actor, relationship_id: uuid.UUID) -> None:
    """Remove a relationship and journal it as one ``unrelate`` entry with no ``after``."""
    relationship = session.get(RelationshipRecord, relationship_id)
    if relationship is None:
        raise ThingNotFound(f"no relationship with id {relationship_id}")

    before = _snapshot(relationship)
    session.delete(relationship)
    session.flush()
    _journalled(
        session,
        actor=actor,
        operation=Operation.UNRELATE,
        entity_type=EntityType.RELATIONSHIP,
        entity_id=relationship_id,
        before=before,
        after=None,
    )
    session.commit()


# --- The user model --------------------------------------------------------


def get_or_create_user_anchor(session: Session, *, actor: Actor) -> ThingRecord:
    """The single ``#User`` Thing every preference hangs off, created on first use.

    Created lazily rather than at boot: a startup write has no honest actor to attribute, and it
    would put a journal entry nobody made into the learning pass's only input. Reads never create
    it — :func:`backend.queries.user_model` on a graph without an anchor simply has no edges to
    follow.
    """
    anchor = session.get(ThingRecord, USER_ANCHOR_ID)
    if anchor is not None:
        return anchor

    try:
        anchor = _insert_thing(
            session,
            actor=actor,
            thing_id=USER_ANCHOR_ID,
            title="User",
            description="The anchor every preference hangs off.",
            tags=[USER_TAG],
        )
        session.commit()
    except IntegrityError:
        # Two concurrent first writes both miss the get above; the primary key makes the loser fail
        # rather than create a second anchor, so the loser reads the winner's row.
        session.rollback()
        anchor = session.get(ThingRecord, USER_ANCHOR_ID)
        if anchor is None:
            raise
        return anchor

    session.refresh(anchor)
    return anchor


def record_preference(
    session: Session,
    *,
    actor: Actor,
    title: str,
    scope: str,
    evidence_ids: Sequence[uuid.UUID],
) -> ThingRecord:
    """Record a preference as its own Thing, anchored to ``#User`` and linked to its evidence.

    Evidence is required: a preference nobody can trace back to specific moments is the confidence
    float this design exists to avoid. Every evidence id is a **Thing** id — a relationship can only
    point at a Thing, so a journal entry becomes evidence by being wrapped in a Thing tagged
    ``#Observation`` carrying ``notes["journal_entry_id"]``.

    The anchor edge runs anchor → preference as a ``RelatedTo``; each evidence edge runs evidence →
    preference as an ``EvidenceFor``. ``RelationshipType`` leaves ``RelatedTo``'s direction unpinned,
    so it is pinned here because :func:`backend.queries.user_model` follows it.

    The preference Thing and all of its edges are written in one transaction, so a failure part-way
    cannot leave behind the evidence-less preference this function refuses to create.
    """
    scope = scope.strip()
    if not scope:
        raise ValueError("a preference must declare the scope it applies to")

    wanted = list(dict.fromkeys(evidence_ids))
    if not wanted:
        raise ValueError("a preference with no evidence is not recordable")
    for evidence_id in wanted:
        _require_thing(session, evidence_id)

    anchor = get_or_create_user_anchor(session, actor=actor)

    preference = _insert_thing(
        session,
        actor=actor,
        title=title,
        notes={"scope": scope},
        tags=[PREFERENCE_TAG],
    )
    _insert_relationship(
        session,
        actor=actor,
        source_thing_id=anchor.id,
        target_thing_id=preference.id,
        relationship_type=RelationshipType.RELATED_TO,
    )
    for evidence_id in wanted:
        _insert_relationship(
            session,
            actor=actor,
            source_thing_id=evidence_id,
            target_thing_id=preference.id,
            relationship_type=RelationshipType.EVIDENCE_FOR,
        )

    session.commit()
    session.refresh(preference)
    return preference


def _require_preference(session: Session, preference_id: uuid.UUID) -> ThingRecord:
    """A Thing that is not a preference exists, so ``ThingNotFound`` would be a lie."""
    preference = _require_thing(session, preference_id)
    if PREFERENCE_TAG not in preference.tags:
        raise ValueError(f"Thing {preference_id} is not tagged {PREFERENCE_TAG}")
    return preference


def add_preference_evidence(
    session: Session,
    *,
    actor: Actor,
    preference_id: uuid.UUID,
    evidence_id: uuid.UUID,
) -> ThingRecord:
    """Link one more piece of evidence to an existing preference, for when it is reinforced.

    Returns the preference rather than the edge: the reinforced preference and its new strength are
    what the caller asked about.

    Idempotent, and not as a nicety: strength *is* the count of these edges, so adding the same
    evidence twice would silently overstate the preference. Evidence already linked leaves the
    preference untouched and journals nothing.
    """
    preference = _require_preference(session, preference_id)
    _require_thing(session, evidence_id)
    if evidence_id == preference.id:
        raise ValueError("a preference cannot be its own evidence")

    already_linked = session.exec(
        select(RelationshipRecord).where(
            RelationshipRecord.source_thing_id == evidence_id,
            RelationshipRecord.target_thing_id == preference.id,
            RelationshipRecord.relationship_type == RelationshipType.EVIDENCE_FOR,
        )
    ).first()
    if already_linked is None:
        relate(
            session,
            actor=actor,
            source_thing_id=evidence_id,
            target_thing_id=preference.id,
            relationship_type=RelationshipType.EVIDENCE_FOR,
        )
    return preference


def reject_preference(session: Session, *, actor: Actor, preference_id: uuid.UUID) -> ThingRecord:
    """Tag a preference ``#Rejected`` and journal who rejected it.

    The preference is not archived and not deleted: a rejected preference stays readable, both so
    the user can see it and so the learning pass can check it before deriving the same ground again.
    Rejecting an already-rejected preference changes nothing and journals nothing.
    """
    preference = _require_preference(session, preference_id)
    if REJECTED_TAG in preference.tags:
        return preference

    return update_thing(
        session,
        actor=actor,
        thing_id=preference.id,
        tags=[*preference.tags, REJECTED_TAG],
    )
