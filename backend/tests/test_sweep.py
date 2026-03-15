"""Tests for the nightly sweep SQL candidate queries."""

import json
from datetime import date, timedelta

from backend.database import db
from backend.sweep import (
    collect_candidates,
    find_approaching_dates,
    find_completed_projects,
    find_open_questions,
    find_orphan_things,
    find_stale_things,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_thing(
    conn,
    thing_id: str,
    title: str,
    *,
    type_hint: str | None = None,
    parent_id: str | None = None,
    checkin_date: str | None = None,
    active: bool = True,
    data: dict | None = None,
    open_questions: list[str] | None = None,
    updated_at: str | None = None,
) -> None:
    now = updated_at or date.today().isoformat()
    conn.execute(
        """INSERT INTO things
           (id, title, type_hint, parent_id, checkin_date, active, surface,
            data, open_questions, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
        (
            thing_id,
            title,
            type_hint,
            parent_id,
            checkin_date,
            int(active),
            json.dumps(data) if data else None,
            json.dumps(open_questions) if open_questions else None,
            now,
            now,
        ),
    )


def _insert_relationship(conn, rel_id: str, from_id: str, to_id: str, rel_type: str = "related-to") -> None:
    conn.execute(
        """INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type)
           VALUES (?, ?, ?, ?)""",
        (rel_id, from_id, to_id, rel_type),
    )


# ---------------------------------------------------------------------------
# Approaching dates
# ---------------------------------------------------------------------------


class TestApproachingDates:
    def test_checkin_date_within_window(self, patched_db):
        today = date.today()
        tomorrow = (today + timedelta(days=1)).isoformat()
        with db() as conn:
            _insert_thing(conn, "t1", "Task A", checkin_date=f"{tomorrow}T09:00:00")
        with db() as conn:
            results = find_approaching_dates(conn, today, window_days=7)
        assert len(results) == 1
        assert results[0].thing_id == "t1"
        assert results[0].finding_type == "approaching_date"
        assert "tomorrow" in results[0].message.lower()

    def test_checkin_date_outside_window(self, patched_db):
        today = date.today()
        far_future = (today + timedelta(days=30)).isoformat()
        with db() as conn:
            _insert_thing(conn, "t1", "Far Away", checkin_date=f"{far_future}T09:00:00")
        with db() as conn:
            results = find_approaching_dates(conn, today, window_days=7)
        assert len(results) == 0

    def test_data_json_deadline(self, patched_db):
        today = date.today()
        in_3_days = (today + timedelta(days=3)).isoformat()
        with db() as conn:
            _insert_thing(conn, "t1", "Project X", data={"deadline": in_3_days})
        with db() as conn:
            results = find_approaching_dates(conn, today, window_days=7)
        assert len(results) == 1
        assert "Deadline in 3d" in results[0].message

    def test_recurring_birthday(self, patched_db):
        today = date.today()
        # Set birthday to 2 days from now (different year)
        bday = today + timedelta(days=2)
        bday_str = f"1990-{bday.month:02d}-{bday.day:02d}"
        with db() as conn:
            _insert_thing(conn, "tom", "Tom", type_hint="person", data={"birthday": bday_str})
        with db() as conn:
            results = find_approaching_dates(conn, today, window_days=7)
        assert len(results) == 1
        assert results[0].extra["days_away"] == 2

    def test_past_oneshot_date_excluded(self, patched_db):
        today = date.today()
        past = (today - timedelta(days=5)).isoformat()
        with db() as conn:
            _insert_thing(conn, "t1", "Past Event", data={"deadline": past})
        with db() as conn:
            results = find_approaching_dates(conn, today, window_days=7)
        assert len(results) == 0

    def test_inactive_thing_excluded(self, patched_db):
        today = date.today()
        tomorrow = (today + timedelta(days=1)).isoformat()
        with db() as conn:
            _insert_thing(conn, "t1", "Inactive", checkin_date=f"{tomorrow}T09:00:00", active=False)
        with db() as conn:
            results = find_approaching_dates(conn, today, window_days=7)
        assert len(results) == 0

    def test_today_checkin(self, patched_db):
        today = date.today()
        with db() as conn:
            _insert_thing(conn, "t1", "Due Now", checkin_date=f"{today.isoformat()}T09:00:00")
        with db() as conn:
            results = find_approaching_dates(conn, today, window_days=7)
        assert len(results) == 1
        assert results[0].priority == 1  # high priority for today


# ---------------------------------------------------------------------------
# Stale Things
# ---------------------------------------------------------------------------


class TestStaleThings:
    def test_stale_thing_detected(self, patched_db):
        today = date.today()
        old_date = (today - timedelta(days=20)).isoformat()
        with db() as conn:
            _insert_thing(conn, "t1", "Old Task", updated_at=old_date)
        with db() as conn:
            results = find_stale_things(conn, today, stale_days=14)
        assert len(results) == 1
        assert results[0].finding_type == "stale"
        assert "20d" in results[0].message

    def test_recently_updated_excluded(self, patched_db):
        today = date.today()
        recent = (today - timedelta(days=3)).isoformat()
        with db() as conn:
            _insert_thing(conn, "t1", "Fresh Task", updated_at=recent)
        with db() as conn:
            results = find_stale_things(conn, today, stale_days=14)
        assert len(results) == 0

    def test_inactive_excluded(self, patched_db):
        today = date.today()
        old_date = (today - timedelta(days=20)).isoformat()
        with db() as conn:
            _insert_thing(conn, "t1", "Inactive Old", updated_at=old_date, active=False)
        with db() as conn:
            results = find_stale_things(conn, today, stale_days=14)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Orphan Things
# ---------------------------------------------------------------------------


class TestOrphanThings:
    def test_orphan_detected(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "Lonely Thing")
        with db() as conn:
            results = find_orphan_things(conn)
        assert len(results) == 1
        assert results[0].finding_type == "orphan"

    def test_thing_with_parent_not_orphan(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "parent", "Parent")
            _insert_thing(conn, "child", "Child", parent_id="parent")
        with db() as conn:
            results = find_orphan_things(conn)
        # Parent is orphan (no parent_id, no relationships), child is not
        ids = [r.thing_id for r in results]
        assert "parent" in ids
        assert "child" not in ids

    def test_thing_with_relationship_not_orphan(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "Connected A")
            _insert_thing(conn, "t2", "Connected B")
            _insert_relationship(conn, "r1", "t1", "t2")
        with db() as conn:
            results = find_orphan_things(conn)
        ids = [r.thing_id for r in results]
        assert "t1" not in ids
        assert "t2" not in ids

    def test_inactive_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "Inactive Orphan", active=False)
        with db() as conn:
            results = find_orphan_things(conn)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Completed projects
# ---------------------------------------------------------------------------


class TestCompletedProjects:
    def test_all_children_inactive(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "proj", "My Project", type_hint="project")
            _insert_thing(conn, "c1", "Task 1", parent_id="proj", active=False)
            _insert_thing(conn, "c2", "Task 2", parent_id="proj", active=False)
        with db() as conn:
            results = find_completed_projects(conn)
        assert len(results) == 1
        assert results[0].thing_id == "proj"
        assert results[0].extra["total_children"] == 2

    def test_some_children_active(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "proj", "Active Project", type_hint="project")
            _insert_thing(conn, "c1", "Done", parent_id="proj", active=False)
            _insert_thing(conn, "c2", "WIP", parent_id="proj", active=True)
        with db() as conn:
            results = find_completed_projects(conn)
        assert len(results) == 0

    def test_project_with_no_children(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "proj", "Empty Project", type_hint="project")
        with db() as conn:
            results = find_completed_projects(conn)
        assert len(results) == 0

    def test_inactive_project_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "proj", "Done Project", type_hint="project", active=False)
            _insert_thing(conn, "c1", "Task", parent_id="proj", active=False)
        with db() as conn:
            results = find_completed_projects(conn)
        assert len(results) == 0

    def test_non_project_type_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "goal", "My Goal", type_hint="goal")
            _insert_thing(conn, "c1", "Step 1", parent_id="goal", active=False)
        with db() as conn:
            results = find_completed_projects(conn)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Open questions
# ---------------------------------------------------------------------------


class TestOpenQuestions:
    def test_thing_with_questions(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "Budget", open_questions=["When is the deadline?", "Who approves?"])
        with db() as conn:
            results = find_open_questions(conn)
        assert len(results) == 1
        assert results[0].finding_type == "open_question"
        assert "2 unanswered questions" in results[0].message
        assert results[0].extra["question_count"] == 2

    def test_empty_questions_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "No Q", open_questions=[])
        with db() as conn:
            results = find_open_questions(conn)
        assert len(results) == 0

    def test_null_questions_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "Null Q")
        with db() as conn:
            results = find_open_questions(conn)
        assert len(results) == 0

    def test_inactive_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "Inactive Q", open_questions=["Why?"], active=False)
        with db() as conn:
            results = find_open_questions(conn)
        assert len(results) == 0

    def test_single_question_grammar(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "One Q", open_questions=["What?"])
        with db() as conn:
            results = find_open_questions(conn)
        assert "1 unanswered question:" in results[0].message  # no 's'


# ---------------------------------------------------------------------------
# collect_candidates integration
# ---------------------------------------------------------------------------


class TestCollectCandidates:
    def test_empty_db_returns_empty(self, patched_db):
        results = collect_candidates()
        assert results == []

    def test_combines_all_types(self, patched_db):
        today = date.today()
        old = (today - timedelta(days=20)).isoformat()
        tomorrow = (today + timedelta(days=1)).isoformat()

        with db() as conn:
            # approaching date
            _insert_thing(conn, "t1", "Upcoming", checkin_date=f"{tomorrow}T09:00:00")
            # stale
            _insert_thing(conn, "t2", "Stale", updated_at=old)
            # orphan (t1 and t2 are also orphans — they'll appear there too)
            # completed project
            _insert_thing(conn, "proj", "Done Project", type_hint="project")
            _insert_thing(conn, "c1", "Child", parent_id="proj", active=False)
            # open question
            _insert_thing(conn, "t3", "Has Q", open_questions=["What?"])

        results = collect_candidates(today=today)
        types = {c.finding_type for c in results}
        assert "approaching_date" in types
        assert "stale" in types
        assert "orphan" in types
        assert "completed_project" in types
        assert "open_question" in types

    def test_deduplicates_by_thing_and_type(self, patched_db):
        """Same thing_id + finding_type keeps highest priority."""
        today = date.today()
        # A thing with both checkin_date and a deadline in data — both approaching_date
        tomorrow = (today + timedelta(days=1)).isoformat()
        with db() as conn:
            _insert_thing(
                conn,
                "t1",
                "Double Date",
                checkin_date=f"{tomorrow}T09:00:00",
                data={"deadline": tomorrow},
            )
        results = collect_candidates(today=today)
        approaching = [c for c in results if c.finding_type == "approaching_date" and c.thing_id == "t1"]
        assert len(approaching) == 1  # deduplicated

    def test_sorted_by_priority_then_title(self, patched_db):
        today = date.today()
        old = (today - timedelta(days=20)).isoformat()
        tomorrow = (today + timedelta(days=1)).isoformat()
        with db() as conn:
            _insert_thing(conn, "b", "Bravo", updated_at=old)  # stale, priority 3
            _insert_thing(conn, "a", "Alpha", checkin_date=f"{tomorrow}T09:00:00")  # approaching, priority 1
        results = collect_candidates(today=today)
        # Alpha (priority 1) should come before Bravo (priority 3)
        approaching = [c for c in results if c.finding_type == "approaching_date"]
        assert approaching[0].thing_title == "Alpha"
