"""Integration tests for tools.get_user_profile()."""
from __future__ import annotations

from sqlmodel import Session

import backend.db_engine as engine_module
from backend.db_models import ThingRecord, ThingRelationshipRecord
from backend.tools import get_user_profile


def _create_person(session: Session, title: str, user_id: str = "") -> ThingRecord:
    record = ThingRecord(title=title, type_hint="person", surface=False, user_id=user_id or None)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


class TestGetUserProfile:
    def test_returns_thing_and_empty_relationships(self, patched_db):
        with Session(engine_module.engine) as session:
            _create_person(session, "Alice")
        result = get_user_profile()
        assert "error" not in result
        assert result["thing"]["title"] == "Alice"
        assert result["thing"]["type_hint"] == "person"
        assert isinstance(result["relationships"], list)

    def test_no_profile_returns_error(self, patched_db):
        result = get_user_profile()
        assert result == {"error": "User profile Thing not found"}

    def test_relationships_resolved(self, patched_db):
        with Session(engine_module.engine) as session:
            person = _create_person(session, "Bob")
            other = ThingRecord(title="Acme Corp", type_hint="project")
            session.add(other)
            session.commit()
            session.refresh(other)
            rel = ThingRelationshipRecord(
                from_thing_id=person.id,
                to_thing_id=other.id,
                relationship_type="works_at",
            )
            session.add(rel)
            session.commit()

        result = get_user_profile()
        assert "error" not in result
        assert len(result["relationships"]) == 1
        r = result["relationships"][0]
        assert r["direction"] == "outgoing"
        assert r["related_thing_title"] == "Acme Corp"
        assert r["relationship_type"] == "works_at"

    def test_incoming_relationship_direction(self, patched_db):
        with Session(engine_module.engine) as session:
            person = _create_person(session, "Carol")
            employer = ThingRecord(title="BigCo", type_hint="project")
            session.add(employer)
            session.commit()
            session.refresh(employer)
            # Carol works_at BigCo (outgoing from person)
            rel_out = ThingRelationshipRecord(
                from_thing_id=person.id,
                to_thing_id=employer.id,
                relationship_type="works_at",
            )
            # BigCo employs Carol (incoming to person)
            rel_in = ThingRelationshipRecord(
                from_thing_id=employer.id,
                to_thing_id=person.id,
                relationship_type="employs",
            )
            session.add(rel_out)
            session.add(rel_in)
            session.commit()

        result = get_user_profile()
        assert "error" not in result
        directions = {r["relationship_type"]: r["direction"] for r in result["relationships"]}
        assert directions["works_at"] == "outgoing"
        assert directions["employs"] == "incoming"
        titles = {r["relationship_type"]: r["related_thing_title"] for r in result["relationships"]}
        assert titles["works_at"] == "BigCo"
        assert titles["employs"] == "BigCo"

    def test_user_isolation(self, patched_db):
        USER_A = "user-a"
        USER_B = "user-b"
        with Session(engine_module.engine) as session:
            _create_person(session, "Alice", user_id=USER_A)
            _create_person(session, "Bob", user_id=USER_B)

        result_a = get_user_profile(user_id=USER_A)
        assert "error" not in result_a
        assert result_a["thing"]["title"] == "Alice"

        result_b = get_user_profile(user_id=USER_B)
        assert "error" not in result_b
        assert result_b["thing"]["title"] == "Bob"
