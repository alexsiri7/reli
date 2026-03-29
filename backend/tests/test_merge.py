"""Tests for Thing merge functionality in apply_storage_changes."""

import json
import uuid

from backend.database import db


def _insert_thing(conn, title, type_hint="task", data=None, open_questions=None):
    """Insert a Thing directly and return its id."""
    thing_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO things (id, title, type_hint, importance, active, surface, data,
           open_questions, created_at, updated_at)
           VALUES (?, ?, ?, 2, 1, 1, ?, ?, datetime('now'), datetime('now'))""",
        (
            thing_id,
            title,
            type_hint,
            json.dumps(data) if data else None,
            json.dumps(open_questions) if open_questions else None,
        ),
    )
    return thing_id


def _insert_relationship(conn, from_id, to_id, rel_type="related-to"):
    """Insert a relationship and return its id."""
    rel_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type) VALUES (?, ?, ?, ?)",
        (rel_id, from_id, to_id, rel_type),
    )
    return rel_id


class TestMergeThings:
    def test_basic_merge(self, patched_db):
        """Merge combines data and deletes the duplicate."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            keep_id = _insert_thing(conn, "Bob", data={"age": 30})
            remove_id = _insert_thing(conn, "My cousin", data={"hobby": "chess"})
            conn.commit()

        with db() as conn:
            result = apply_storage_changes(
                {
                    "merge": [
                        {
                            "keep_id": keep_id,
                            "remove_id": remove_id,
                            "merged_data": {"age": 30, "hobby": "chess", "relation": "cousin"},
                        }
                    ]
                },
                conn,
            )

        assert len(result["merged"]) == 1
        assert result["merged"][0]["keep_id"] == keep_id
        assert result["merged"][0]["remove_id"] == remove_id

        # Verify primary Thing has merged data
        with db() as conn:
            row = conn.execute("SELECT * FROM things WHERE id = ?", (keep_id,)).fetchone()
            assert row is not None
            data = json.loads(row["data"])
            assert data["relation"] == "cousin"
            assert data["hobby"] == "chess"
            assert data["age"] == 30

            # Verify duplicate is deleted
            removed = conn.execute("SELECT * FROM things WHERE id = ?", (remove_id,)).fetchone()
            assert removed is None

    def test_merge_repoints_relationships(self, patched_db):
        """All relationships from/to the duplicate get re-pointed to the primary."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            keep_id = _insert_thing(conn, "Bob")
            remove_id = _insert_thing(conn, "My cousin")
            other_id = _insert_thing(conn, "Alice")
            # Relationships pointing from and to the duplicate
            _insert_relationship(conn, remove_id, other_id, "knows")
            _insert_relationship(conn, other_id, remove_id, "involves")
            conn.commit()

        with db() as conn:
            apply_storage_changes(
                {"merge": [{"keep_id": keep_id, "remove_id": remove_id, "merged_data": {}}]},
                conn,
            )

        with db() as conn:
            # Both relationships should now point to/from keep_id
            rels = conn.execute("SELECT * FROM thing_relationships ORDER BY relationship_type").fetchall()
            assert len(rels) == 2
            for rel in rels:
                assert rel["from_thing_id"] != remove_id
                assert rel["to_thing_id"] != remove_id
            # Check specific re-pointing
            rel_map = {r["relationship_type"]: dict(r) for r in rels}
            assert rel_map["knows"]["from_thing_id"] == keep_id
            assert rel_map["knows"]["to_thing_id"] == other_id
            assert rel_map["involves"]["from_thing_id"] == other_id
            assert rel_map["involves"]["to_thing_id"] == keep_id

    def test_merge_removes_self_referential_relationships(self, patched_db):
        """If keep and remove had a relationship between them, it becomes self-ref and is cleaned up."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            keep_id = _insert_thing(conn, "Bob")
            remove_id = _insert_thing(conn, "My cousin")
            _insert_relationship(conn, keep_id, remove_id, "same-as")
            conn.commit()

        with db() as conn:
            apply_storage_changes(
                {"merge": [{"keep_id": keep_id, "remove_id": remove_id, "merged_data": {}}]},
                conn,
            )

        with db() as conn:
            rels = conn.execute("SELECT * FROM thing_relationships").fetchall()
            assert len(rels) == 0  # self-ref should be deleted

    def test_merge_transfers_open_questions(self, patched_db):
        """Open questions from the duplicate are transferred, skipping duplicates."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            keep_id = _insert_thing(conn, "Bob", open_questions=["What's his birthday?", "Where does he work?"])
            remove_id = _insert_thing(
                conn, "My cousin", open_questions=["Where does he work?", "What's his phone number?"]
            )
            conn.commit()

        with db() as conn:
            apply_storage_changes(
                {"merge": [{"keep_id": keep_id, "remove_id": remove_id, "merged_data": {}}]},
                conn,
            )

        with db() as conn:
            row = conn.execute("SELECT * FROM things WHERE id = ?", (keep_id,)).fetchone()
            oq = json.loads(row["open_questions"])
            assert "What's his birthday?" in oq
            assert "Where does he work?" in oq
            assert "What's his phone number?" in oq
            # No duplicates
            assert len(oq) == 3

    def test_merge_skips_nonexistent_ids(self, patched_db):
        """Merge gracefully skips when either ID doesn't exist."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            keep_id = _insert_thing(conn, "Bob")
            conn.commit()

        with db() as conn:
            result = apply_storage_changes(
                {"merge": [{"keep_id": keep_id, "remove_id": "nonexistent", "merged_data": {}}]},
                conn,
            )

        assert len(result["merged"]) == 0

    def test_merge_skips_same_id(self, patched_db):
        """Merge skips when keep_id == remove_id."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            thing_id = _insert_thing(conn, "Bob")
            conn.commit()

        with db() as conn:
            result = apply_storage_changes(
                {"merge": [{"keep_id": thing_id, "remove_id": thing_id, "merged_data": {}}]},
                conn,
            )

        assert len(result["merged"]) == 0

        # Thing should still exist
        with db() as conn:
            row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
            assert row is not None

    def test_merge_with_empty_data(self, patched_db):
        """Merge works when Things have no existing data."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            keep_id = _insert_thing(conn, "Bob")
            remove_id = _insert_thing(conn, "My cousin")
            conn.commit()

        with db() as conn:
            result = apply_storage_changes(
                {"merge": [{"keep_id": keep_id, "remove_id": remove_id, "merged_data": {"name": "Bob"}}]},
                conn,
            )

        assert len(result["merged"]) == 1
        with db() as conn:
            row = conn.execute("SELECT * FROM things WHERE id = ?", (keep_id,)).fetchone()
            data = json.loads(row["data"])
            assert data["name"] == "Bob"

    def test_merge_records_history(self, patched_db):
        """Merge via apply_storage_changes creates a merge_history record."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            keep_id = _insert_thing(conn, "Bob", data={"age": 30})
            remove_id = _insert_thing(conn, "My cousin", data={"hobby": "chess"})
            conn.commit()

        with db() as conn:
            apply_storage_changes(
                {
                    "merge": [
                        {
                            "keep_id": keep_id,
                            "remove_id": remove_id,
                            "merged_data": {"age": 30, "hobby": "chess"},
                        }
                    ]
                },
                conn,
            )

        with db() as conn:
            rows = conn.execute("SELECT * FROM merge_history").fetchall()
            assert len(rows) == 1
            rec = rows[0]
            assert rec["keep_id"] == keep_id
            assert rec["remove_id"] == remove_id
            assert rec["keep_title"] == "Bob"
            assert rec["remove_title"] == "My cousin"
            assert rec["triggered_by"] == "agent"
            merged = json.loads(rec["merged_data"])
            assert merged["hobby"] == "chess"

    def test_merge_skipped_no_history(self, patched_db):
        """When merge is skipped (nonexistent ID), no history record is created."""
        from backend.agents import apply_storage_changes

        with db() as conn:
            keep_id = _insert_thing(conn, "Bob")
            conn.commit()

        with db() as conn:
            apply_storage_changes(
                {"merge": [{"keep_id": keep_id, "remove_id": "nonexistent", "merged_data": {}}]},
                conn,
            )

        with db() as conn:
            rows = conn.execute("SELECT * FROM merge_history").fetchall()
            assert len(rows) == 0


class TestMergeHistoryAPI:
    def test_merge_endpoint_records_history(self, client):
        """POST /api/things/merge creates a merge_history record."""
        # Create two things
        a = client.post("/api/things", json={"title": "Alice", "type_hint": "person"})
        b = client.post("/api/things", json={"title": "Alicia", "type_hint": "person"})
        keep_id = a.json()["id"]
        remove_id = b.json()["id"]

        resp = client.post("/api/things/merge", json={"keep_id": keep_id, "remove_id": remove_id})
        assert resp.status_code == 200

        history = client.get("/api/things/merge-history")
        assert history.status_code == 200
        records = history.json()
        assert len(records) >= 1
        rec = records[0]
        assert rec["keep_id"] == keep_id
        assert rec["remove_id"] == remove_id
        assert rec["keep_title"] == "Alice"
        assert rec["remove_title"] == "Alicia"
        assert rec["triggered_by"] == "api"

    def test_merge_history_filter_by_thing(self, client):
        """GET /api/things/merge-history?thing_id= filters by kept Thing."""
        a = client.post("/api/things", json={"title": "X"})
        b = client.post("/api/things", json={"title": "Y"})
        c = client.post("/api/things", json={"title": "Z"})
        keep_id = a.json()["id"]
        other_keep = c.json()["id"]

        client.post("/api/things/merge", json={"keep_id": keep_id, "remove_id": b.json()["id"]})

        # Create another thing to merge into c (need a 4th thing)
        d = client.post("/api/things", json={"title": "W"})
        client.post("/api/things/merge", json={"keep_id": other_keep, "remove_id": d.json()["id"]})

        # Filter by keep_id
        history = client.get(f"/api/things/merge-history?thing_id={keep_id}")
        records = history.json()
        assert len(records) == 1
        assert records[0]["keep_id"] == keep_id
