"""Tests for SQLModel table models (Phase 1 — db_models.py).

Verifies that the models can be imported, the engine/session work against
a fresh in-memory SQLite database, and basic CRUD round-trips are correct.

These tests use an isolated in-memory DB (not the patched_db fixture from
conftest) so they never touch production schema or the test sqlite3 path.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from backend.db_models import ChatHistory, SweepFinding, Thing, ThingRelationship, User  # noqa: F401


@pytest.fixture(scope="module")
def engine():
    """In-memory SQLite engine with all SQLModel tables created fresh."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s
        s.rollback()  # Isolate each test


class TestThingModel:
    def test_insert_and_retrieve(self, session):
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        thing = Thing(id="t-1", title="Buy milk", priority=3, created_at=now, updated_at=now)
        session.add(thing)
        session.commit()

        fetched = session.get(Thing, "t-1")
        assert fetched is not None
        assert fetched.title == "Buy milk"
        assert fetched.priority == 3
        assert fetched.active is True

    def test_json_data_field(self, session):
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        thing = Thing(
            id="t-2",
            title="Project X",
            data={"notes": "important", "tags": ["work"]},
            created_at=now,
            updated_at=now,
        )
        session.add(thing)
        session.commit()
        session.refresh(thing)

        assert thing.data == {"notes": "important", "tags": ["work"]}

    def test_open_questions_json_field(self, session):
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        thing = Thing(
            id="t-3",
            title="Research",
            open_questions=["What is the budget?", "Who is the owner?"],
            created_at=now,
            updated_at=now,
        )
        session.add(thing)
        session.commit()
        session.refresh(thing)

        assert thing.open_questions == ["What is the budget?", "Who is the owner?"]

    def test_nullable_fields_default_to_none(self, session):
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        thing = Thing(id="t-4", title="Minimal", created_at=now, updated_at=now)
        session.add(thing)
        session.commit()
        session.refresh(thing)

        assert thing.type_hint is None
        assert thing.parent_id is None
        assert thing.data is None
        assert thing.user_id is None

    def test_select_query(self, session):
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        session.add(Thing(id="t-q1", title="Alpha", priority=1, created_at=now, updated_at=now))
        session.add(Thing(id="t-q2", title="Beta", priority=2, created_at=now, updated_at=now))
        session.commit()

        results = session.exec(select(Thing).where(Thing.priority == 1)).all()
        ids = [t.id for t in results]
        assert "t-q1" in ids
        assert "t-q2" not in ids


class TestThingRelationshipModel:
    def test_insert_and_retrieve(self, session):
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        # Insert parent things first (FK constraints active in SQLite)
        session.add(Thing(id="tr-src", title="Source", created_at=now, updated_at=now))
        session.add(Thing(id="tr-tgt", title="Target", created_at=now, updated_at=now))
        session.commit()

        rel = ThingRelationship(
            id="rel-1",
            from_thing_id="tr-src",
            to_thing_id="tr-tgt",
            relationship_type="blocks",
            created_at=now,
        )
        session.add(rel)
        session.commit()

        fetched = session.get(ThingRelationship, "rel-1")
        assert fetched is not None
        assert fetched.relationship_type == "blocks"
        assert fetched.rel_metadata is None

    def test_metadata_json_column(self, session):
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        session.add(Thing(id="rm-src", title="A", created_at=now, updated_at=now))
        session.add(Thing(id="rm-tgt", title="B", created_at=now, updated_at=now))
        session.commit()

        rel = ThingRelationship(
            id="rel-2",
            from_thing_id="rm-src",
            to_thing_id="rm-tgt",
            relationship_type="supports",
            rel_metadata={"strength": "high"},
            created_at=now,
        )
        session.add(rel)
        session.commit()
        session.refresh(rel)

        assert rel.rel_metadata == {"strength": "high"}


class TestSweepFindingModel:
    def test_insert_and_retrieve(self, session):
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        finding = SweepFinding(
            id="sf-1",
            finding_type="stale_task",
            message="Task hasn't been updated in 30 days",
            priority=2,
            created_at=now,
        )
        session.add(finding)
        session.commit()

        fetched = session.get(SweepFinding, "sf-1")
        assert fetched is not None
        assert fetched.finding_type == "stale_task"
        assert fetched.dismissed is False
        assert fetched.snoozed_until is None


class TestChatHistoryModel:
    def test_insert_and_retrieve(self, session):
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        msg = ChatHistory(
            session_id="sess-abc",
            role="user",
            content="What tasks are due today?",
            timestamp=now,
        )
        session.add(msg)
        session.commit()
        session.refresh(msg)

        assert msg.id is not None
        assert msg.role == "user"
        assert msg.prompt_tokens == 0

    def test_applied_changes_json(self, session):
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        msg = ChatHistory(
            session_id="sess-abc",
            role="assistant",
            content="Done.",
            applied_changes={"created": ["t-abc"], "updated": []},
            timestamp=now,
        )
        session.add(msg)
        session.commit()
        session.refresh(msg)

        assert msg.applied_changes == {"created": ["t-abc"], "updated": []}
