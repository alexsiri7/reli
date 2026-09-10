"""Every mutation produces exactly one journal entry — #1408's mandated test.

Counts are taken as deltas because the journal is append-only: the fixture cannot clear it between
tests, and the trigger would refuse if it tried.
"""

import pytest
from sqlalchemy import text

from backend.db_models import Actor, EntityType, Operation, RelationshipType
from backend.service import create_thing, delete_thing, relate, unrelate, update_thing


def _journal_count(session):
    return session.execute(text("SELECT count(*) FROM journal")).scalar_one()


def _entries_since(session, count_before):
    rows = session.execute(
        text("SELECT actor, operation, entity_type, entity_id, before, after FROM journal ORDER BY id OFFSET :n"),
        {"n": count_before},
    ).all()
    return rows


def _make_thing(session, title="thing"):
    return create_thing(session, actor=Actor.USER, title=title)


@pytest.mark.parametrize("actor", list(Actor))
def test_create_thing_writes_exactly_one_entry(session, actor):
    before_count = _journal_count(session)
    thing = create_thing(session, actor=actor, title="created")

    entries = _entries_since(session, before_count)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.actor == actor.value
    assert entry.operation == Operation.CREATE.value
    assert entry.entity_type == EntityType.THING.value
    assert entry.entity_id == thing.id
    assert entry.before is None
    assert entry.after["title"] == "created"


def test_update_thing_writes_exactly_one_entry_with_both_snapshots(session):
    thing = _make_thing(session, "before title")
    before_count = _journal_count(session)

    update_thing(session, actor=Actor.CLAUDE_INTERACTIVE, thing_id=thing.id, title="after title")

    entries = _entries_since(session, before_count)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.actor == Actor.CLAUDE_INTERACTIVE.value
    assert entry.operation == Operation.UPDATE.value
    assert entry.entity_type == EntityType.THING.value
    assert entry.entity_id == thing.id
    assert entry.before["title"] == "before title"
    assert entry.after["title"] == "after title"


def test_delete_thing_without_relationships_writes_exactly_one_entry(session):
    thing = _make_thing(session, "doomed")
    before_count = _journal_count(session)

    delete_thing(session, actor=Actor.USER, thing_id=thing.id)

    entries = _entries_since(session, before_count)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.operation == Operation.DELETE.value
    assert entry.entity_type == EntityType.THING.value
    assert entry.entity_id == thing.id
    assert entry.before["title"] == "doomed"
    assert entry.after is None


def test_relate_writes_exactly_one_entry(session):
    source = _make_thing(session, "source")
    target = _make_thing(session, "target")
    before_count = _journal_count(session)

    relationship = relate(
        session,
        actor=Actor.CLAUDE_SCHEDULED,
        source_thing_id=source.id,
        target_thing_id=target.id,
        relationship_type=RelationshipType.CHILD_OF,
    )

    entries = _entries_since(session, before_count)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.actor == Actor.CLAUDE_SCHEDULED.value
    assert entry.operation == Operation.RELATE.value
    assert entry.entity_type == EntityType.RELATIONSHIP.value
    assert entry.entity_id == relationship.id
    assert entry.before is None
    assert entry.after["relationship_type"] == RelationshipType.CHILD_OF.value


def test_unrelate_writes_exactly_one_entry(session):
    source = _make_thing(session, "source")
    target = _make_thing(session, "target")
    relationship = relate(
        session,
        actor=Actor.USER,
        source_thing_id=source.id,
        target_thing_id=target.id,
        relationship_type=RelationshipType.BLOCKS,
    )
    before_count = _journal_count(session)

    unrelate(session, actor=Actor.USER, relationship_id=relationship.id)

    entries = _entries_since(session, before_count)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.operation == Operation.UNRELATE.value
    assert entry.entity_type == EntityType.RELATIONSHIP.value
    assert entry.entity_id == relationship.id
    assert entry.before["relationship_type"] == RelationshipType.BLOCKS.value
    assert entry.after is None


def test_deleting_a_thing_with_two_edges_journals_each_unrelate_then_the_delete(session):
    thing = _make_thing(session, "hub")
    other = _make_thing(session, "spoke")
    relate(
        session,
        actor=Actor.USER,
        source_thing_id=thing.id,
        target_thing_id=other.id,
        relationship_type=RelationshipType.CHILD_OF,
    )
    relate(
        session,
        actor=Actor.USER,
        source_thing_id=other.id,
        target_thing_id=thing.id,
        relationship_type=RelationshipType.RELATED_TO,
    )
    before_count = _journal_count(session)

    delete_thing(session, actor=Actor.USER, thing_id=thing.id)

    entries = _entries_since(session, before_count)
    assert [e.operation for e in entries] == [
        Operation.UNRELATE.value,
        Operation.UNRELATE.value,
        Operation.DELETE.value,
    ]
    assert entries[-1].entity_id == thing.id
