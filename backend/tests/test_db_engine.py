"""Tests for backend.db_engine utility functions."""

from __future__ import annotations

from sqlmodel import select

from backend.db_engine import user_filter_clause
from backend.db_models import ThingRecord


class TestUserFilterClause:
    """user_filter_clause must enforce strict ownership (SEC-01)."""

    def test_excludes_null_user_id_records(self, patched_db, db):
        """Records with NULL user_id must NOT be visible to authenticated users."""
        with db() as conn:
            conn.execute(
                "INSERT INTO things (id, title, user_id, active) VALUES (?, ?, ?, ?)",
                ("null-owner", "orphan thing", None, 1),
            )
            conn.execute(
                "INSERT INTO things (id, title, user_id, active) VALUES (?, ?, ?, ?)",
                ("owned", "my thing", "user-1", 1),
            )

        from sqlmodel import Session

        from backend.db_engine import engine

        with Session(engine) as session:
            clause = user_filter_clause(ThingRecord.user_id, "user-1")
            results = session.exec(select(ThingRecord).where(clause)).all()
            ids = {r.id for r in results}
            assert "owned" in ids
            assert "null-owner" not in ids

    def test_returns_true_when_auth_disabled(self):
        """When user_id is empty (auth disabled), all records should be visible."""
        result = user_filter_clause(ThingRecord.user_id, "")
        assert result is True
