"""Tests for user_filter_clause — the core multi-tenancy primitive.

Modeled on the TestUserFilterText suite in test_things.py, but exercises the
SQLAlchemy filter-clause version used directly in ORM ``select()`` queries.
"""

from sqlmodel import Session, select

import backend.db_engine as engine_module
from backend.db_engine import user_filter_clause
from backend.db_models import ThingRecord


class TestUserFilterClause:
    def test_empty_user_id_is_a_no_op_filter(self):
        assert user_filter_clause(ThingRecord.user_id, "") is True

    def test_selects_owned_and_null_rows_but_not_other_users(self, patched_db):
        with Session(engine_module.engine) as session:
            session.add(ThingRecord(id="t-u1", title="Owned by u1", user_id="u1"))
            session.add(ThingRecord(id="t-u2", title="Owned by u2", user_id="u2"))
            session.add(ThingRecord(id="t-null", title="Legacy, no owner", user_id=None))
            session.commit()

            rows = session.exec(
                select(ThingRecord).where(user_filter_clause(ThingRecord.user_id, "u1"))
            ).all()

        ids = {row.id for row in rows}
        assert ids == {"t-u1", "t-null"}
        assert "t-u2" not in ids
