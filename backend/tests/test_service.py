"""The semantics of the write path, beyond the journalling that test_journal.py covers."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from backend.db_models import NEW_TAG, Actor, RelationshipType
from backend.service import ThingNotFound, create_thing, relate, update_thing


def _journal_count(session):
    return session.execute(text("SELECT count(*) FROM journal")).scalar_one()


def test_create_thing_defaults(session):
    """The capture defaults — tomorrow and ``#New`` — are test_capture_defaults.py's; the rest are here."""
    thing = create_thing(session, actor=Actor.USER, title="bare")

    assert thing.description is None
    assert thing.notes == {}
    assert thing.tags == [NEW_TAG]
    assert thing.urls == {}
    assert thing.checkin_date is not None
    assert thing.priority == 0.0
    assert thing.active is True
    assert thing.created_at == thing.updated_at


def test_update_thing_replaces_rather_than_merges(session):
    thing = create_thing(
        session,
        actor=Actor.USER,
        title="notes",
        notes={"keep": "a", "drop": "b"},
        tags=["one", "two"],
        urls={"home": "https://example.test"},
    )

    updated = update_thing(
        session,
        actor=Actor.USER,
        thing_id=thing.id,
        notes={"keep": "z"},
        tags=["three"],
        urls={"docs": "https://docs.test"},
    )

    assert updated.notes == {"keep": "z"}
    assert updated.tags == ["three"]
    assert updated.urls == {"docs": "https://docs.test"}


def test_update_thing_leaves_untouched_fields_alone(session):
    thing = create_thing(session, actor=Actor.USER, title="title", description="description", priority=3.0)

    updated = update_thing(session, actor=Actor.USER, thing_id=thing.id, title="new title")

    assert updated.title == "new title"
    assert updated.description == "description"
    assert updated.priority == 3.0


def test_update_thing_advances_updated_at(session):
    thing = create_thing(session, actor=Actor.USER, title="stamped")
    original = thing.updated_at

    updated = update_thing(session, actor=Actor.USER, thing_id=thing.id, title="restamped")

    assert updated.updated_at > original
    assert updated.created_at == thing.created_at


def test_update_thing_rejects_an_unknown_id(session):
    with pytest.raises(ThingNotFound):
        update_thing(session, actor=Actor.USER, thing_id=uuid.uuid4(), title="nobody")


def test_relate_rejects_a_type_outside_the_five(session):
    """The column type rejects it before the database CHECK has to; test_schema.py covers the CHECK."""
    source = create_thing(session, actor=Actor.USER, title="source")
    target = create_thing(session, actor=Actor.USER, title="target")

    with pytest.raises(ValueError, match="Supersedes"):
        relate(
            session,
            actor=Actor.USER,
            source_thing_id=source.id,
            target_thing_id=target.id,
            relationship_type="Supersedes",
        )
    session.rollback()


def test_a_failed_mutation_leaves_no_journal_entry(session):
    """The row and its journal entry share one transaction, so neither survives a failure."""
    before_count = _journal_count(session)

    with pytest.raises(DatabaseError):
        relate(
            session,
            actor=Actor.USER,
            source_thing_id=uuid.uuid4(),
            target_thing_id=uuid.uuid4(),
            relationship_type=RelationshipType.BLOCKS,
        )
    session.rollback()

    assert _journal_count(session) == before_count
