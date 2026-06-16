"""Tests for apply_storage_changes create and update paths."""

import sqlite3

from backend.agents import apply_storage_changes


def _get_conn(patched_db) -> sqlite3.Connection:
    conn = sqlite3.connect(str(patched_db), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class TestApplyStorageChangesCreate:
    def test_create_inserts_thing_into_db(self, patched_db, mock_vector_store):
        """A create action should insert a new Thing row."""
        conn = _get_conn(patched_db)
        try:
            changes = {"create": [{"title": "Alice", "type_hint": "person"}]}
            result = apply_storage_changes(changes, conn)
            conn.commit()

            assert len(result["created"]) == 1
            assert result["created"][0]["title"] == "Alice"

            row = conn.execute("SELECT * FROM things WHERE title = 'Alice'").fetchone()
            assert row is not None
            assert row["type_hint"] == "person"
        finally:
            conn.close()

    def test_create_upserts_vector_embedding(self, patched_db, mock_vector_store):
        """Creating a Thing should also call upsert_thing for vector embedding."""
        from unittest.mock import patch

        conn = _get_conn(patched_db)
        try:
            changes = {"create": [{"title": "Bob", "type_hint": "person"}]}
            with patch("backend.vector_store.upsert_thing", return_value=None) as mock_upsert:
                apply_storage_changes(changes, conn)
                conn.commit()

            mock_upsert.assert_called_once()
            upserted = mock_upsert.call_args.args[0]
            assert upserted["title"] == "Bob"
        finally:
            conn.close()

    def test_update_modifies_existing_thing(self, patched_db, mock_vector_store):
        """An update action should modify an existing Thing's fields."""
        conn = _get_conn(patched_db)
        try:
            # First create a Thing
            changes = {"create": [{"title": "Task A", "type_hint": "task"}]}
            result = apply_storage_changes(changes, conn)
            conn.commit()
            thing_id = result["created"][0]["id"]

            # Now update it
            update_changes = {
                "update": [{"id": thing_id, "changes": {"importance": 5}}],
            }
            result = apply_storage_changes(update_changes, conn)
            conn.commit()

            assert len(result["updated"]) == 1
            row = conn.execute("SELECT importance FROM things WHERE id = ?", (thing_id,)).fetchone()
            assert row["importance"] == 5
        finally:
            conn.close()
