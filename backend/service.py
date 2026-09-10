"""The only write path into the graph.

Every public function here writes its row and its journal entry in a single transaction, so there
is no way to change a Thing or a relationship without leaving a record of the change. Nothing
outside this module may construct or mutate ``ThingRecord`` / ``RelationshipRecord``;
``backend/tests/test_architecture.py`` enforces that.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlmodel import Session, or_, select

from .db_models import (
    Actor,
    EntityType,
    JournalRecord,
    Operation,
    RelationshipRecord,
    RelationshipType,
    ThingRecord,
)

__all__ = [
    "Actor",
    "EntityType",
    "Operation",
    "ThingNotFound",
    "create_thing",
    "delete_thing",
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
    """Create a Thing and journal it as one ``create`` entry with no ``before``."""
    now = datetime.now(UTC)
    thing = ThingRecord(
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


def delete_thing(session: Session, *, actor: Actor, thing_id: uuid.UUID) -> None:
    """Delete a Thing and every relationship touching it, in one transaction.

    The foreign keys are ``ON DELETE RESTRICT``, so the edges are removed first — each one
    journalled as its own ``unrelate``. A Thing with N relationships therefore produces N+1 journal
    entries: the N unrelates, then the delete.
    """
    thing = _require_thing(session, thing_id)

    edges = session.exec(
        select(RelationshipRecord).where(
            or_(
                RelationshipRecord.source_thing_id == thing_id,
                RelationshipRecord.target_thing_id == thing_id,
            )
        )
    ).all()
    for edge in edges:
        edge_before = _snapshot(edge)
        edge_id = edge.id
        session.delete(edge)
        session.flush()
        _journalled(
            session,
            actor=actor,
            operation=Operation.UNRELATE,
            entity_type=EntityType.RELATIONSHIP,
            entity_id=edge_id,
            before=edge_before,
            after=None,
        )

    before = _snapshot(thing)
    session.delete(thing)
    session.flush()
    _journalled(
        session,
        actor=actor,
        operation=Operation.DELETE,
        entity_type=EntityType.THING,
        entity_id=thing_id,
        before=before,
        after=None,
    )
    session.commit()


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
