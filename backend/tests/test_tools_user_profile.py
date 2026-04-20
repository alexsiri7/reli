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
