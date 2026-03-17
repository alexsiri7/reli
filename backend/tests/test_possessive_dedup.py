"""Tests for possessive entity deduplication in apply_storage_changes."""

import json
import uuid

from backend.database import db


def _insert_thing(conn, title, type_hint="person", data=None):
    """Insert a Thing directly and return its id."""
    thing_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO things (id, title, type_hint, priority, active, surface, data,
           created_at, updated_at)
           VALUES (?, ?, ?, 3, 1, 0, ?, datetime('now'), datetime('now'))""",
        (thing_id, title, type_hint, json.dumps(data) if data else None),
    )
    return thing_id


def _insert_relationship(conn, from_id, to_id, rel_type):
    """Insert a relationship and return its id."""
    rel_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type)"
        " VALUES (?, ?, ?, ?)",
        (rel_id, from_id, to_id, rel_type),
    )
    return rel_id


class TestPossessiveDedup:
    def test_reuses_existing_entity_by_relationship_type(self, patched_db):
        """'my sister Sarah' should reuse existing 'Sister' entity linked by 'sister' rel."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            user_id = _insert_thing(conn, "Me")
            sister_id = _insert_thing(conn, "Sister", data={"notes": "User's sister"})
            _insert_relationship(conn, user_id, sister_id, "sister")
            conn.commit()

        # LLM tries to create "Sarah" with a "sister" relationship from user
        with db() as conn:
            result = apply_storage_changes(
                {
                    "create": [
                        {
                            "title": "Sarah",
                            "type_hint": "person",
                            "data": {"notes": "User's sister"},
                        }
                    ],
                    "relationships": [
                        {
                            "from_thing_id": user_id,
                            "to_thing_id": "NEW:0",
                            "relationship_type": "sister",
                        }
                    ],
                },
                conn,
            )
            conn.commit()

        # Should have updated existing entity, not created a new one
        assert len(result["created"]) == 0
        assert len(result["updated"]) == 1
        assert result["updated"][0]["id"] == sister_id

        # Title should be updated to the more specific name
        with db() as conn:
            row = conn.execute("SELECT title FROM things WHERE id = ?", (sister_id,)).fetchone()
            assert row["title"] == "Sarah"

    def test_no_duplicate_relationship_created(self, patched_db):
        """When possessive dedup matches, the existing relationship should not be duplicated."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            user_id = _insert_thing(conn, "Me")
            doctor_id = _insert_thing(conn, "Dr. Smith")
            _insert_relationship(conn, user_id, doctor_id, "doctor")
            conn.commit()

        with db() as conn:
            result = apply_storage_changes(
                {
                    "create": [
                        {
                            "title": "Dr. Smith",
                            "type_hint": "person",
                            "data": {"notes": "User's doctor"},
                        }
                    ],
                    "relationships": [
                        {
                            "from_thing_id": user_id,
                            "to_thing_id": "NEW:0",
                            "relationship_type": "doctor",
                        }
                    ],
                },
                conn,
            )
            conn.commit()

        # Relationship should not be duplicated
        assert len(result["relationships_created"]) == 0

        with db() as conn:
            rels = conn.execute(
                "SELECT * FROM thing_relationships WHERE from_thing_id = ? AND relationship_type = 'doctor'",
                (user_id,),
            ).fetchall()
            assert len(rels) == 1

    def test_creates_new_entity_when_no_existing_relationship(self, patched_db):
        """If no existing relationship of the type exists, create normally."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            user_id = _insert_thing(conn, "Me")
            conn.commit()

        with db() as conn:
            result = apply_storage_changes(
                {
                    "create": [
                        {
                            "title": "Alice",
                            "type_hint": "person",
                            "data": {"notes": "User's cousin"},
                        }
                    ],
                    "relationships": [
                        {
                            "from_thing_id": user_id,
                            "to_thing_id": "NEW:0",
                            "relationship_type": "cousin",
                        }
                    ],
                },
                conn,
            )
            conn.commit()

        # Should create the new entity
        assert len(result["created"]) == 1
        assert result["created"][0]["title"] == "Alice"
        # Relationship should be created
        assert len(result["relationships_created"]) == 1
        assert result["relationships_created"][0]["relationship_type"] == "cousin"

    def test_title_dedup_still_works(self, patched_db):
        """Exact title match dedup should still work independently of possessive dedup."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            existing_id = _insert_thing(conn, "Bob")
            conn.commit()

        with db() as conn:
            result = apply_storage_changes(
                {
                    "create": [
                        {
                            "title": "Bob",
                            "type_hint": "person",
                            "data": {"notes": "Friend"},
                        }
                    ],
                },
                conn,
            )
            conn.commit()

        assert len(result["created"]) == 0
        assert len(result["updated"]) == 1
        assert result["updated"][0]["id"] == existing_id

    def test_does_not_match_different_relationship_type(self, patched_db):
        """User has 'sister' relationship; creating with 'doctor' should not match."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            user_id = _insert_thing(conn, "Me")
            sister_id = _insert_thing(conn, "Sister")
            _insert_relationship(conn, user_id, sister_id, "sister")
            conn.commit()

        with db() as conn:
            result = apply_storage_changes(
                {
                    "create": [
                        {
                            "title": "Dr. Park",
                            "type_hint": "person",
                            "data": {"notes": "User's doctor"},
                        }
                    ],
                    "relationships": [
                        {
                            "from_thing_id": user_id,
                            "to_thing_id": "NEW:0",
                            "relationship_type": "doctor",
                        }
                    ],
                },
                conn,
            )
            conn.commit()

        # Should create new entity since no "doctor" relationship exists
        assert len(result["created"]) == 1
        assert result["created"][0]["title"] == "Dr. Park"

    def test_skips_possessive_dedup_for_non_entity_types(self, patched_db):
        """Non-entity type_hints (task, etc.) should not trigger possessive dedup."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            user_id = _insert_thing(conn, "Me")
            project_id = _insert_thing(conn, "Work Project", type_hint="task")
            _insert_relationship(conn, user_id, project_id, "owner_of")
            conn.commit()

        with db() as conn:
            result = apply_storage_changes(
                {
                    "create": [
                        {
                            "title": "New Project",
                            "type_hint": "task",
                            "data": {"notes": "Another project"},
                        }
                    ],
                    "relationships": [
                        {
                            "from_thing_id": user_id,
                            "to_thing_id": "NEW:0",
                            "relationship_type": "owner_of",
                        }
                    ],
                },
                conn,
            )
            conn.commit()

        # Should create new entity since type_hint is "task" (not an entity type)
        assert len(result["created"]) == 1

    def test_preserves_title_when_same(self, patched_db):
        """When possessive dedup matches and titles are the same, don't update title."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            user_id = _insert_thing(conn, "Me")
            friend_id = _insert_thing(conn, "Alex")
            _insert_relationship(conn, user_id, friend_id, "friend")
            conn.commit()

        with db() as conn:
            result = apply_storage_changes(
                {
                    "create": [
                        {
                            "title": "alex",
                            "type_hint": "person",
                            "data": {"notes": "User's friend"},
                        }
                    ],
                    "relationships": [
                        {
                            "from_thing_id": user_id,
                            "to_thing_id": "NEW:0",
                            "relationship_type": "friend",
                        }
                    ],
                },
                conn,
            )
            conn.commit()

        # Should reuse existing entity
        assert len(result["created"]) == 0
        assert len(result["updated"]) == 1

        # Title should remain "Alex" (original casing) since they match case-insensitively
        with db() as conn:
            row = conn.execute("SELECT title FROM things WHERE id = ?", (friend_id,)).fetchone()
            assert row["title"] == "Alex"


class TestCompoundPossessives:
    """Tests for compound/chained possessives like 'my sister's husband Bob'."""

    def test_compound_possessive_creates_chain(self, patched_db):
        """'my sister's husband Bob' creates sister, Bob, and both relationships."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            user_id = _insert_thing(conn, "Me")
            conn.commit()

        with db() as conn:
            result = apply_storage_changes(
                {
                    "create": [
                        {
                            "title": "Sister",
                            "type_hint": "person",
                            "data": {"notes": "User's sister"},
                        },
                        {
                            "title": "Bob",
                            "type_hint": "person",
                            "data": {"notes": "User's sister's husband"},
                        },
                    ],
                    "relationships": [
                        {
                            "from_thing_id": user_id,
                            "to_thing_id": "NEW:0",
                            "relationship_type": "sister",
                        },
                        {
                            "from_thing_id": "NEW:0",
                            "to_thing_id": "NEW:1",
                            "relationship_type": "husband",
                        },
                    ],
                },
                conn,
            )
            conn.commit()

        # Both entities should be created
        assert len(result["created"]) == 2
        assert result["created"][0]["title"] == "Sister"
        assert result["created"][1]["title"] == "Bob"
        # Both relationships should be created
        assert len(result["relationships_created"]) == 2
        rel_types = {r["relationship_type"] for r in result["relationships_created"]}
        assert rel_types == {"sister", "husband"}

    def test_compound_possessive_reuses_existing_first_link(self, patched_db):
        """'my sister's husband Bob' reuses existing sister entity."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            user_id = _insert_thing(conn, "Me")
            sister_id = _insert_thing(conn, "Sarah", data={"notes": "User's sister"})
            _insert_relationship(conn, user_id, sister_id, "sister")
            conn.commit()

        with db() as conn:
            result = apply_storage_changes(
                {
                    "create": [
                        {
                            "title": "Sister",
                            "type_hint": "person",
                            "data": {"notes": "User's sister"},
                        },
                        {
                            "title": "Bob",
                            "type_hint": "person",
                            "data": {"notes": "User's sister's husband"},
                        },
                    ],
                    "relationships": [
                        {
                            "from_thing_id": user_id,
                            "to_thing_id": "NEW:0",
                            "relationship_type": "sister",
                        },
                        {
                            "from_thing_id": "NEW:0",
                            "to_thing_id": "NEW:1",
                            "relationship_type": "husband",
                        },
                    ],
                },
                conn,
            )
            conn.commit()

        # Sister should be deduped (reused), Bob should be created
        assert len(result["created"]) == 1
        assert result["created"][0]["title"] == "Bob"
        assert len(result["updated"]) == 1
        assert result["updated"][0]["id"] == sister_id

        # The husband relationship should link sister → Bob
        husband_rels = [r for r in result["relationships_created"] if r["relationship_type"] == "husband"]
        assert len(husband_rels) == 1
        assert husband_rels[0]["from_thing_id"] == sister_id

    def test_compound_possessive_dedup_second_link(self, patched_db):
        """If sister already has a husband entity, reuse it via possessive dedup."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            user_id = _insert_thing(conn, "Me")
            sister_id = _insert_thing(conn, "Sarah", data={"notes": "User's sister"})
            husband_id = _insert_thing(conn, "Husband", data={"notes": "Sarah's husband"})
            _insert_relationship(conn, user_id, sister_id, "sister")
            _insert_relationship(conn, sister_id, husband_id, "husband")
            conn.commit()

        with db() as conn:
            result = apply_storage_changes(
                {
                    "create": [
                        {
                            "title": "Sister",
                            "type_hint": "person",
                            "data": {"notes": "User's sister"},
                        },
                        {
                            "title": "Bob",
                            "type_hint": "person",
                            "data": {"notes": "User's sister's husband"},
                        },
                    ],
                    "relationships": [
                        {
                            "from_thing_id": user_id,
                            "to_thing_id": "NEW:0",
                            "relationship_type": "sister",
                        },
                        {
                            "from_thing_id": "NEW:0",
                            "to_thing_id": "NEW:1",
                            "relationship_type": "husband",
                        },
                    ],
                },
                conn,
            )
            conn.commit()

        # Both should be deduped
        assert len(result["created"]) == 0
        assert len(result["updated"]) == 2

        # Husband title should be updated to "Bob"
        with db() as conn:
            row = conn.execute("SELECT title FROM things WHERE id = ?", (husband_id,)).fetchone()
            assert row["title"] == "Bob"

        # No new relationships created (both already exist)
        assert len(result["relationships_created"]) == 0
