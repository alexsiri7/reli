"""Tests for connection_sweep relationship scoping (PR #957)."""

from unittest.mock import patch

from backend.connection_sweep import find_connection_candidates

# ---------------------------------------------------------------------------
# Helpers (same pattern as test_sweep.py)
# ---------------------------------------------------------------------------


def _insert_thing(conn, thing_id: str, title: str, *, user_id: str = "", active: bool = True) -> None:
    from datetime import date

    now = date.today().isoformat()
    conn.execute(
        """INSERT INTO things
           (id, title, type_hint, importance, active, surface, created_at, updated_at, user_id)
           VALUES (?, ?, NULL, 2, ?, 1, ?, ?, ?)""",
        (thing_id, title, int(active), now, now, user_id or None),
    )


def _insert_relationship(conn, rel_id: str, from_id: str, to_id: str, rel_type: str = "related-to") -> None:
    conn.execute(
        """INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type)
           VALUES (?, ?, ?, ?)""",
        (rel_id, from_id, to_id, rel_type),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFindConnectionCandidatesScoping:
    """Verify that relationship queries are scoped to the requesting user's things."""

    def test_excludes_other_user_relationships(self, patched_db, db):
        """Relationships between other users' things should not appear in existing_rels,
        so they don't incorrectly filter out candidates for the requesting user."""
        with db() as conn:
            # User A's things
            _insert_thing(conn, "a1", "Task A1", user_id="user-a")
            _insert_thing(conn, "a2", "Task A2", user_id="user-a")

            # User B's things with a relationship
            _insert_thing(conn, "b1", "Task B1", user_id="user-b")
            _insert_thing(conn, "b2", "Task B2", user_id="user-b")
            _insert_relationship(conn, "r-b", "b1", "b2", "related-to")

        # Mock vector store: vector_count returns 2, vector_search returns a2 as similar to a1
        with (
            patch(
                "backend.vector_store.vector_search_with_distances",
                side_effect=lambda query, **kw: [("a2", 0.1)] if "A1" in query else [("a1", 0.1)],
            ),
            patch("backend.vector_store.vector_count", return_value=10),
        ):
            candidates = find_connection_candidates(user_id="user-a")

        # a1-a2 should be a candidate (no relationship exists for user A)
        pair_ids = {(c.from_thing_id, c.to_thing_id) for c in candidates}
        assert ("a1", "a2") in pair_ids or ("a2", "a1") in pair_ids

    def test_own_relationships_filter_candidates(self, patched_db, db):
        """User's own existing relationships should correctly filter out candidates."""
        with db() as conn:
            _insert_thing(conn, "a1", "Task A1", user_id="user-a")
            _insert_thing(conn, "a2", "Task A2", user_id="user-a")
            # User A already has a relationship between a1 and a2
            _insert_relationship(conn, "r-a", "a1", "a2", "related-to")

        with (
            patch(
                "backend.vector_store.vector_search_with_distances",
                side_effect=lambda query, **kw: [("a2", 0.1)] if "A1" in query else [("a1", 0.1)],
            ),
            patch("backend.vector_store.vector_count", return_value=10),
        ):
            candidates = find_connection_candidates(user_id="user-a")

        # a1-a2 should NOT be a candidate (relationship already exists)
        pair_ids = {(c.from_thing_id, c.to_thing_id) for c in candidates}
        assert ("a1", "a2") not in pair_ids
        assert ("a2", "a1") not in pair_ids

    def test_empty_things_returns_empty(self, patched_db, db):
        """When user has no things, function returns [] without SQL error."""
        with (
            patch("backend.vector_store.vector_count", return_value=10),
        ):
            candidates = find_connection_candidates(user_id="nonexistent-user")

        assert candidates == []

    def test_parent_of_relationships_scoped(self, patched_db, db):
        """Parent-of relationships from other users should not affect candidate filtering."""
        with db() as conn:
            # User A's things
            _insert_thing(conn, "a1", "Task A1", user_id="user-a")
            _insert_thing(conn, "a2", "Task A2", user_id="user-a")

            # User B has a parent-of relationship (should not affect user A)
            _insert_thing(conn, "b1", "Project B", user_id="user-b")
            _insert_thing(conn, "b2", "Subtask B", user_id="user-b")
            _insert_relationship(conn, "r-b", "b1", "b2", "parent-of")

        with (
            patch(
                "backend.vector_store.vector_search_with_distances",
                side_effect=lambda query, **kw: [("a2", 0.1)] if "A1" in query else [("a1", 0.1)],
            ),
            patch("backend.vector_store.vector_count", return_value=10),
        ):
            candidates = find_connection_candidates(user_id="user-a")

        # a1-a2 should be a candidate (user B's parent-of doesn't affect user A)
        pair_ids = {(c.from_thing_id, c.to_thing_id) for c in candidates}
        assert ("a1", "a2") in pair_ids or ("a2", "a1") in pair_ids
