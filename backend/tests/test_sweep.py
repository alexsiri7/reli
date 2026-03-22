"""Tests for the nightly sweep SQL candidate queries."""

import json
from datetime import date, timedelta

from backend.database import db
from backend.sweep import (
    aggregate_personality_patterns,
    collect_candidates,
    find_approaching_dates,
    find_completed_projects,
    find_cross_project_duplicate_effort,
    find_cross_project_resource_conflicts,
    find_cross_project_shared_blockers,
    find_cross_project_thematic_connections,
    find_open_questions,
    find_orphan_things,
    find_overdue_checkins,
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

    def test_high_priority_flagged_as_neglected(self, patched_db):
        """High-priority stale Things should be flagged as 'neglected'."""
        today = date.today()
        old_date = (today - timedelta(days=20)).isoformat()
        with db() as conn:
            _insert_thing(conn, "t1", "Urgent Task", updated_at=old_date)
            conn.execute("UPDATE things SET priority = 1 WHERE id = 't1'")
        with db() as conn:
            results = find_stale_things(conn, today, stale_days=14)
        assert len(results) == 1
        assert results[0].finding_type == "neglected"
        assert results[0].priority == 2  # higher urgency
        assert "high-priority" in results[0].message
        assert results[0].extra["is_neglected"] is True

    def test_thing_with_active_children_flagged_as_neglected(self, patched_db):
        """Stale Things with active children should be flagged as 'neglected'."""
        today = date.today()
        old_date = (today - timedelta(days=20)).isoformat()
        with db() as conn:
            _insert_thing(conn, "proj", "Old Project", type_hint="project", updated_at=old_date)
            _insert_thing(conn, "c1", "Active Child", parent_id="proj")
        with db() as conn:
            results = find_stale_things(conn, today, stale_days=14)
        neglected = [r for r in results if r.thing_id == "proj"]
        assert len(neglected) == 1
        assert neglected[0].finding_type == "neglected"
        assert "1 pending subtask" in neglected[0].message

    def test_low_priority_no_children_is_plain_stale(self, patched_db):
        """Low-priority stale Things without children are plain 'stale'."""
        today = date.today()
        old_date = (today - timedelta(days=20)).isoformat()
        with db() as conn:
            _insert_thing(conn, "t1", "Low Priority Note", updated_at=old_date)
            conn.execute("UPDATE things SET priority = 4 WHERE id = 't1'")
        with db() as conn:
            results = find_stale_things(conn, today, stale_days=14)
        assert len(results) == 1
        assert results[0].finding_type == "stale"
        assert results[0].extra["is_neglected"] is False


# ---------------------------------------------------------------------------
# Overdue check-ins
# ---------------------------------------------------------------------------


class TestOverdueCheckins:
    def test_overdue_checkin_detected(self, patched_db):
        today = date.today()
        past = (today - timedelta(days=5)).isoformat()
        with db() as conn:
            _insert_thing(conn, "t1", "Overdue Task", checkin_date=f"{past}T09:00:00")
        with db() as conn:
            results = find_overdue_checkins(conn, today, grace_days=1)
        assert len(results) == 1
        assert results[0].finding_type == "overdue_checkin"
        assert results[0].extra["days_overdue"] == 5
        assert "overdue by 5d" in results[0].message.lower()

    def test_recent_checkin_within_grace_excluded(self, patched_db):
        """Check-ins within the grace period are not flagged (handled by approaching_dates)."""
        today = date.today()
        yesterday = (today - timedelta(days=0)).isoformat()  # today
        with db() as conn:
            _insert_thing(conn, "t1", "Today Check-in", checkin_date=f"{yesterday}T09:00:00")
        with db() as conn:
            results = find_overdue_checkins(conn, today, grace_days=1)
        assert len(results) == 0

    def test_inactive_excluded(self, patched_db):
        today = date.today()
        past = (today - timedelta(days=10)).isoformat()
        with db() as conn:
            _insert_thing(conn, "t1", "Done Thing", checkin_date=f"{past}T09:00:00", active=False)
        with db() as conn:
            results = find_overdue_checkins(conn, today, grace_days=1)
        assert len(results) == 0

    def test_severely_overdue_gets_high_priority(self, patched_db):
        today = date.today()
        old = (today - timedelta(days=10)).isoformat()
        with db() as conn:
            _insert_thing(conn, "t1", "Very Overdue", checkin_date=f"{old}T09:00:00")
        with db() as conn:
            results = find_overdue_checkins(conn, today, grace_days=1)
        assert len(results) == 1
        assert results[0].priority == 1  # high priority for 7+ days overdue

    def test_future_checkin_excluded(self, patched_db):
        today = date.today()
        future = (today + timedelta(days=5)).isoformat()
        with db() as conn:
            _insert_thing(conn, "t1", "Future Check-in", checkin_date=f"{future}T09:00:00")
        with db() as conn:
            results = find_overdue_checkins(conn, today, grace_days=1)
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
        past = (today - timedelta(days=5)).isoformat()

        with db() as conn:
            # approaching date
            _insert_thing(conn, "t1", "Upcoming", checkin_date=f"{tomorrow}T09:00:00")
            # stale
            _insert_thing(conn, "t2", "Stale", updated_at=old)
            # overdue checkin
            _insert_thing(conn, "t4", "Overdue", checkin_date=f"{past}T09:00:00")
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
        assert "overdue_checkin" in types
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

    def test_includes_cross_project_findings(self, patched_db):
        """collect_candidates includes cross-project detection types."""
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project")
            _insert_thing(conn, "t1", "Setup database", parent_id="p1")
            _insert_thing(conn, "t2", "Setup database", parent_id="p2")
        results = collect_candidates()
        types = {c.finding_type for c in results}
        assert "cross_project_duplicate_effort" in types


# ---------------------------------------------------------------------------
# Cross-project: shared blockers
# ---------------------------------------------------------------------------


class TestCrossProjectSharedBlockers:
    def test_thing_blocking_in_multiple_projects(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project")
            _insert_thing(conn, "t1", "Task in Alpha", parent_id="p1")
            _insert_thing(conn, "t2", "Task in Beta", parent_id="p2")
            _insert_thing(conn, "blocker", "API Migration")
            _insert_relationship(conn, "r1", "blocker", "t1", "blocks")
            _insert_relationship(conn, "r2", "blocker", "t2", "blocks")
        with db() as conn:
            results = find_cross_project_shared_blockers(conn)
        assert len(results) == 1
        assert results[0].thing_id == "blocker"
        assert results[0].finding_type == "cross_project_shared_blocker"
        assert results[0].priority == 1
        assert results[0].extra["project_count"] == 2

    def test_blocker_in_single_project_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "t1", "Task A", parent_id="p1")
            _insert_thing(conn, "t2", "Task B", parent_id="p1")
            _insert_thing(conn, "blocker", "Single Project Blocker")
            _insert_relationship(conn, "r1", "blocker", "t1", "blocks")
            _insert_relationship(conn, "r2", "blocker", "t2", "blocks")
        with db() as conn:
            results = find_cross_project_shared_blockers(conn)
        assert len(results) == 0

    def test_inactive_blocker_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project")
            _insert_thing(conn, "t1", "Task in Alpha", parent_id="p1")
            _insert_thing(conn, "t2", "Task in Beta", parent_id="p2")
            _insert_thing(conn, "blocker", "Done Blocker", active=False)
            _insert_relationship(conn, "r1", "blocker", "t1", "blocks")
            _insert_relationship(conn, "r2", "blocker", "t2", "blocks")
        with db() as conn:
            results = find_cross_project_shared_blockers(conn)
        assert len(results) == 0

    def test_depends_on_relationship_type(self, patched_db):
        """depends_on is treated as a blocking relationship."""
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project")
            _insert_thing(conn, "t1", "Task in Alpha", parent_id="p1")
            _insert_thing(conn, "t2", "Task in Beta", parent_id="p2")
            _insert_thing(conn, "dep", "Shared Dependency")
            _insert_relationship(conn, "r1", "t1", "dep", "depends_on")
            _insert_relationship(conn, "r2", "t2", "dep", "depends_on")
        with db() as conn:
            results = find_cross_project_shared_blockers(conn)
        assert len(results) == 1
        assert results[0].thing_id == "dep"


# ---------------------------------------------------------------------------
# Cross-project: resource conflicts
# ---------------------------------------------------------------------------


class TestCrossProjectResourceConflicts:
    def test_person_in_multiple_projects_with_stale_tasks(self, patched_db):
        today = date.today()
        old = (today - timedelta(days=20)).isoformat()
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project")
            _insert_thing(conn, "t1", "Task in Alpha", parent_id="p1", updated_at=old)
            _insert_thing(conn, "t2", "Task in Beta", parent_id="p2")
            _insert_thing(conn, "alice", "Alice", type_hint="person")
            _insert_relationship(conn, "r1", "alice", "t1", "assigned_to")
            _insert_relationship(conn, "r2", "alice", "t2", "assigned_to")
        with db() as conn:
            results = find_cross_project_resource_conflicts(conn, today)
        assert len(results) == 1
        assert results[0].thing_id == "alice"
        assert results[0].finding_type == "cross_project_resource_conflict"
        assert results[0].extra["stale_tasks"] == 1

    def test_person_in_one_project_excluded(self, patched_db):
        today = date.today()
        old = (today - timedelta(days=20)).isoformat()
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "t1", "Task A", parent_id="p1", updated_at=old)
            _insert_thing(conn, "alice", "Alice", type_hint="person")
            _insert_relationship(conn, "r1", "alice", "t1", "assigned_to")
        with db() as conn:
            results = find_cross_project_resource_conflicts(conn, today)
        assert len(results) == 0

    def test_no_stale_tasks_excluded(self, patched_db):
        today = date.today()
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project")
            _insert_thing(conn, "t1", "Task in Alpha", parent_id="p1")
            _insert_thing(conn, "t2", "Task in Beta", parent_id="p2")
            _insert_thing(conn, "alice", "Alice", type_hint="person")
            _insert_relationship(conn, "r1", "alice", "t1", "assigned_to")
            _insert_relationship(conn, "r2", "alice", "t2", "assigned_to")
        with db() as conn:
            results = find_cross_project_resource_conflicts(conn, today)
        assert len(results) == 0

    def test_non_person_excluded(self, patched_db):
        today = date.today()
        old = (today - timedelta(days=20)).isoformat()
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project")
            _insert_thing(conn, "t1", "Task in Alpha", parent_id="p1", updated_at=old)
            _insert_thing(conn, "t2", "Task in Beta", parent_id="p2")
            _insert_thing(conn, "tool", "Shared Tool", type_hint="tool")
            _insert_relationship(conn, "r1", "tool", "t1", "used_by")
            _insert_relationship(conn, "r2", "tool", "t2", "used_by")
        with db() as conn:
            results = find_cross_project_resource_conflicts(conn, today)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Cross-project: thematic connections
# ---------------------------------------------------------------------------


class TestCrossProjectThematicConnections:
    def test_similar_titles_across_projects(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project")
            _insert_thing(conn, "t1", "Design user authentication flow", parent_id="p1")
            _insert_thing(conn, "t2", "Implement user authentication service", parent_id="p2")
        with db() as conn:
            results = find_cross_project_thematic_connections(conn)
        assert len(results) == 1
        assert results[0].finding_type == "cross_project_thematic_connection"
        assert "user" in results[0].extra["shared_words"]
        assert "authentication" in results[0].extra["shared_words"]

    def test_same_project_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "t1", "Design user auth", parent_id="p1")
            _insert_thing(conn, "t2", "Implement user auth", parent_id="p1")
        with db() as conn:
            results = find_cross_project_thematic_connections(conn)
        assert len(results) == 0

    def test_unrelated_titles_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project")
            _insert_thing(conn, "t1", "Design homepage layout", parent_id="p1")
            _insert_thing(conn, "t2", "Fix database migration", parent_id="p2")
        with db() as conn:
            results = find_cross_project_thematic_connections(conn)
        assert len(results) == 0

    def test_short_words_excluded(self, patched_db):
        """Words shorter than 3 chars should not count."""
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project")
            _insert_thing(conn, "t1", "Do it", parent_id="p1")
            _insert_thing(conn, "t2", "Do it", parent_id="p2")
        with db() as conn:
            results = find_cross_project_thematic_connections(conn)
        # "Do" and "it" are <3 chars, no significant shared words
        assert len(results) == 0

    def test_inactive_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project")
            _insert_thing(conn, "t1", "Design user authentication", parent_id="p1", active=False)
            _insert_thing(conn, "t2", "Implement user authentication", parent_id="p2")
        with db() as conn:
            results = find_cross_project_thematic_connections(conn)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Cross-project: duplicate effort
# ---------------------------------------------------------------------------


class TestCrossProjectDuplicateEffort:
    def test_identical_titles_across_projects(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project")
            _insert_thing(conn, "t1", "Setup database", parent_id="p1")
            _insert_thing(conn, "t2", "Setup database", parent_id="p2")
        with db() as conn:
            results = find_cross_project_duplicate_effort(conn)
        assert len(results) == 1
        assert results[0].finding_type == "cross_project_duplicate_effort"
        assert results[0].priority == 2

    def test_case_insensitive_match(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project")
            _insert_thing(conn, "t1", "Setup Database", parent_id="p1")
            _insert_thing(conn, "t2", "setup database", parent_id="p2")
        with db() as conn:
            results = find_cross_project_duplicate_effort(conn)
        assert len(results) == 1

    def test_same_project_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "t1", "Setup database", parent_id="p1")
            _insert_thing(conn, "t2", "Setup database", parent_id="p1")
        with db() as conn:
            results = find_cross_project_duplicate_effort(conn)
        assert len(results) == 0

    def test_different_titles_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project")
            _insert_thing(conn, "t1", "Setup database", parent_id="p1")
            _insert_thing(conn, "t2", "Deploy server", parent_id="p2")
        with db() as conn:
            results = find_cross_project_duplicate_effort(conn)
        assert len(results) == 0

    def test_inactive_task_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project")
            _insert_thing(conn, "t1", "Setup database", parent_id="p1", active=False)
            _insert_thing(conn, "t2", "Setup database", parent_id="p2")
        with db() as conn:
            results = find_cross_project_duplicate_effort(conn)
        assert len(results) == 0

    def test_inactive_project_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "p1", "Project Alpha", type_hint="project")
            _insert_thing(conn, "p2", "Project Beta", type_hint="project", active=False)
            _insert_thing(conn, "t1", "Setup database", parent_id="p1")
            _insert_thing(conn, "t2", "Setup database", parent_id="p2")
        with db() as conn:
            results = find_cross_project_duplicate_effort(conn)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Personality pattern aggregation
# ---------------------------------------------------------------------------


def _insert_chat_message(
    conn,
    role: str,
    content: str,
    *,
    applied_changes: dict | None = None,
    session_id: str = "test-session",
    timestamp: str | None = None,
) -> None:
    now = timestamp or date.today().isoformat()
    conn.execute(
        """INSERT INTO chat_history
           (session_id, role, content, applied_changes, timestamp)
           VALUES (?, ?, ?, ?, ?)""",
        (
            session_id,
            role,
            content,
            json.dumps(applied_changes) if applied_changes else None,
            now,
        ),
    )


def _insert_sweep_finding(
    conn,
    finding_id: str,
    finding_type: str,
    *,
    dismissed: bool = False,
    created_at: str | None = None,
) -> None:
    now = created_at or date.today().isoformat()
    conn.execute(
        """INSERT INTO sweep_findings
           (id, finding_type, message, priority, dismissed, created_at)
           VALUES (?, ?, ?, 3, ?, ?)""",
        (finding_id, finding_type, f"Test {finding_type}", int(dismissed), now),
    )


class TestPersonalityPatternBrevity:
    def test_short_titles_detected(self, patched_db):
        """When most titles are 3 words or fewer, brevity pattern fires."""
        with db() as conn:
            for i in range(6):
                _insert_chat_message(
                    conn,
                    "assistant",
                    f"Created thing {i}",
                    applied_changes={
                        "created": [{"id": f"t{i}", "title": "Fix bug"}],
                    },
                )
        with db() as conn:
            results = aggregate_personality_patterns(conn)
        assert len(results) == 1
        assert results[0].extra["pattern"] == "title_brevity"
        assert results[0].finding_type == "personality_pattern"

    def test_long_titles_no_pattern(self, patched_db):
        """When most titles are long, brevity pattern does not fire."""
        with db() as conn:
            for i in range(6):
                _insert_chat_message(
                    conn,
                    "assistant",
                    f"Created thing {i}",
                    applied_changes={
                        "created": [
                            {"id": f"t{i}", "title": "A very long descriptive title here"}
                        ],
                    },
                )
        with db() as conn:
            results = aggregate_personality_patterns(conn)
        brevity = [r for r in results if r.extra.get("pattern") == "title_brevity"]
        assert len(brevity) == 0

    def test_too_few_titles_no_pattern(self, patched_db):
        """Fewer than 5 titles → not enough data to detect pattern."""
        with db() as conn:
            for i in range(3):
                _insert_chat_message(
                    conn,
                    "assistant",
                    f"Created thing {i}",
                    applied_changes={
                        "created": [{"id": f"t{i}", "title": "Bug"}],
                    },
                )
        with db() as conn:
            results = aggregate_personality_patterns(conn)
        brevity = [r for r in results if r.extra.get("pattern") == "title_brevity"]
        assert len(brevity) == 0

    def test_updated_titles_included(self, patched_db):
        """Updated titles (not just created) count toward brevity."""
        with db() as conn:
            for i in range(6):
                _insert_chat_message(
                    conn,
                    "assistant",
                    f"Updated thing {i}",
                    applied_changes={
                        "updated": [{"id": f"t{i}", "title": "Short"}],
                    },
                )
        with db() as conn:
            results = aggregate_personality_patterns(conn)
        assert len(results) == 1
        assert results[0].extra["pattern"] == "title_brevity"


class TestPersonalityPatternStalenessFatigue:
    def test_high_dismiss_rate_detected(self, patched_db):
        """When ≥60% of stale findings are dismissed, fatigue pattern fires."""
        with db() as conn:
            for i in range(4):
                _insert_sweep_finding(conn, f"sf-d{i}", "stale", dismissed=True)
            _insert_sweep_finding(conn, "sf-k1", "stale", dismissed=False)
        with db() as conn:
            results = aggregate_personality_patterns(conn)
        fatigue = [r for r in results if r.extra.get("pattern") == "staleness_fatigue"]
        assert len(fatigue) == 1
        assert fatigue[0].extra["dismissed"] == 4
        assert fatigue[0].extra["total"] == 5

    def test_low_dismiss_rate_no_pattern(self, patched_db):
        """When few stale findings are dismissed, no fatigue pattern."""
        with db() as conn:
            _insert_sweep_finding(conn, "sf-d1", "stale", dismissed=True)
            for i in range(5):
                _insert_sweep_finding(conn, f"sf-k{i}", "stale", dismissed=False)
        with db() as conn:
            results = aggregate_personality_patterns(conn)
        fatigue = [r for r in results if r.extra.get("pattern") == "staleness_fatigue"]
        assert len(fatigue) == 0

    def test_neglected_findings_included(self, patched_db):
        """Both stale and neglected finding types contribute to the pattern."""
        with db() as conn:
            for i in range(3):
                _insert_sweep_finding(conn, f"sf-s{i}", "stale", dismissed=True)
            for i in range(3):
                _insert_sweep_finding(conn, f"sf-n{i}", "neglected", dismissed=True)
        with db() as conn:
            results = aggregate_personality_patterns(conn)
        fatigue = [r for r in results if r.extra.get("pattern") == "staleness_fatigue"]
        assert len(fatigue) == 1
        assert fatigue[0].extra["total"] == 6

    def test_too_few_findings_no_pattern(self, patched_db):
        """Fewer than 5 stale findings → not enough data."""
        with db() as conn:
            for i in range(3):
                _insert_sweep_finding(conn, f"sf-d{i}", "stale", dismissed=True)
        with db() as conn:
            results = aggregate_personality_patterns(conn)
        fatigue = [r for r in results if r.extra.get("pattern") == "staleness_fatigue"]
        assert len(fatigue) == 0


class TestPersonalityPatternDateEngagement:
    def test_high_date_engagement_detected(self, patched_db):
        """When ≥60% of updated Things have dates, date engagement fires."""
        with db() as conn:
            # 4 date Things, 1 non-date
            for i in range(4):
                _insert_chat_message(
                    conn,
                    "assistant",
                    f"Updated {i}",
                    applied_changes={
                        "updated": [
                            {"id": f"d{i}", "title": f"Event {i}", "checkin_date": "2026-04-01"}
                        ],
                    },
                )
            _insert_chat_message(
                conn,
                "assistant",
                "Updated non-date",
                applied_changes={
                    "updated": [{"id": "nd1", "title": "No date thing"}],
                },
            )
        with db() as conn:
            results = aggregate_personality_patterns(conn)
        date_pat = [r for r in results if r.extra.get("pattern") == "date_engagement"]
        assert len(date_pat) == 1
        assert date_pat[0].extra["date_things"] == 4

    def test_date_in_data_json_detected(self, patched_db):
        """Date fields in the data JSON also count toward date engagement."""
        with db() as conn:
            for i in range(4):
                _insert_chat_message(
                    conn,
                    "assistant",
                    f"Updated {i}",
                    applied_changes={
                        "updated": [
                            {
                                "id": f"d{i}",
                                "title": f"Task {i}",
                                "data": {"deadline": "2026-04-01"},
                            }
                        ],
                    },
                )
            _insert_chat_message(
                conn,
                "assistant",
                "Updated non-date",
                applied_changes={
                    "updated": [{"id": "nd1", "title": "No date thing"}],
                },
            )
        with db() as conn:
            results = aggregate_personality_patterns(conn)
        date_pat = [r for r in results if r.extra.get("pattern") == "date_engagement"]
        assert len(date_pat) == 1

    def test_low_date_engagement_no_pattern(self, patched_db):
        """When few updated Things have dates, no pattern fires."""
        with db() as conn:
            _insert_chat_message(
                conn,
                "assistant",
                "Updated date",
                applied_changes={
                    "updated": [
                        {"id": "d1", "title": "Event", "checkin_date": "2026-04-01"}
                    ],
                },
            )
            for i in range(5):
                _insert_chat_message(
                    conn,
                    "assistant",
                    f"Updated {i}",
                    applied_changes={
                        "updated": [{"id": f"nd{i}", "title": f"Task {i}"}],
                    },
                )
        with db() as conn:
            results = aggregate_personality_patterns(conn)
        date_pat = [r for r in results if r.extra.get("pattern") == "date_engagement"]
        assert len(date_pat) == 0

    def test_old_messages_excluded_by_lookback(self, patched_db):
        """Messages older than lookback_days are excluded from pattern analysis."""
        old_date = (date.today() - timedelta(days=60)).isoformat()
        with db() as conn:
            for i in range(6):
                _insert_chat_message(
                    conn,
                    "assistant",
                    f"Updated {i}",
                    applied_changes={
                        "updated": [
                            {"id": f"d{i}", "title": f"Event {i}", "checkin_date": "2026-04-01"}
                        ],
                    },
                    timestamp=old_date,
                )
        with db() as conn:
            results = aggregate_personality_patterns(conn, lookback_days=30)
        assert len(results) == 0


class TestCollectCandidatesPersonality:
    def test_personality_patterns_included(self, patched_db):
        """collect_candidates includes personality_pattern findings."""
        with db() as conn:
            for i in range(6):
                _insert_chat_message(
                    conn,
                    "assistant",
                    f"Created thing {i}",
                    applied_changes={
                        "created": [{"id": f"t{i}", "title": "Fix"}],
                    },
                )
        results = collect_candidates()
        types = {c.finding_type for c in results}
        assert "personality_pattern" in types
