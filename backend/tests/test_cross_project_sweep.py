"""Tests for cross-project pattern detection."""

import json
from datetime import date

import pytest

from backend.cross_project_sweep import (
    FINDING_TYPE_HINT,
    SWEEP_FINDING_TAG,
    collect_cross_project_findings,
    find_duplicated_effort,
    find_resource_conflicts,
    find_shared_blockers,
    find_thematic_connections,
    persist_findings,
)
from backend.database import db


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
    active: bool = True,
    data: dict | None = None,
) -> None:
    now = date.today().isoformat()
    conn.execute(
        """INSERT INTO things
           (id, title, type_hint, parent_id, active, surface,
            data, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
        (
            thing_id,
            title,
            type_hint,
            parent_id,
            int(active),
            json.dumps(data) if data else None,
            now,
            now,
        ),
    )


def _insert_relationship(
    conn, rel_id: str, from_id: str, to_id: str, rel_type: str = "related_to"
) -> None:
    conn.execute(
        """INSERT INTO thing_relationships
           (id, from_thing_id, to_thing_id, relationship_type)
           VALUES (?, ?, ?, ?)""",
        (rel_id, from_id, to_id, rel_type),
    )


def _setup_two_projects(conn):
    """Create two active projects with active children."""
    _insert_thing(conn, "proj-a", "Project Alpha", type_hint="project")
    _insert_thing(conn, "proj-b", "Project Beta", type_hint="project")
    _insert_thing(conn, "task-a1", "Task A1", parent_id="proj-a")
    _insert_thing(conn, "task-a2", "Task A2", parent_id="proj-a")
    _insert_thing(conn, "task-b1", "Task B1", parent_id="proj-b")
    _insert_thing(conn, "task-b2", "Task B2", parent_id="proj-b")


# ---------------------------------------------------------------------------
# Shared blockers
# ---------------------------------------------------------------------------


class TestSharedBlockers:
    def test_blocker_across_two_projects(self, patched_db):
        with db() as conn:
            _setup_two_projects(conn)
            _insert_thing(conn, "blocker-1", "External API Outage")
            # blocker-1 blocks task-a1 (proj-a) and task-b1 (proj-b)
            _insert_relationship(conn, "r1", "blocker-1", "task-a1", "blocks")
            _insert_relationship(conn, "r2", "blocker-1", "task-b1", "blocks")

        with db() as conn:
            results = find_shared_blockers(conn)

        assert len(results) == 1
        assert results[0].finding_type == "shared_blocker"
        assert "External API Outage" in results[0].message
        assert "proj-a" in results[0].related_project_ids
        assert "proj-b" in results[0].related_project_ids

    def test_blocker_same_project_not_detected(self, patched_db):
        with db() as conn:
            _setup_two_projects(conn)
            _insert_thing(conn, "blocker-1", "Local Issue")
            # Blocks two tasks in same project
            _insert_relationship(conn, "r1", "blocker-1", "task-a1", "blocks")
            _insert_relationship(conn, "r2", "blocker-1", "task-a2", "blocks")

        with db() as conn:
            results = find_shared_blockers(conn)

        assert len(results) == 0

    def test_inactive_blocked_task_excluded(self, patched_db):
        with db() as conn:
            _setup_two_projects(conn)
            _insert_thing(
                conn, "task-a3", "Inactive Task", parent_id="proj-a", active=False
            )
            _insert_thing(conn, "blocker-1", "Some Blocker")
            _insert_relationship(conn, "r1", "blocker-1", "task-a3", "blocks")
            _insert_relationship(conn, "r2", "blocker-1", "task-b1", "blocks")

        with db() as conn:
            results = find_shared_blockers(conn)

        assert len(results) == 0


# ---------------------------------------------------------------------------
# Resource conflicts
# ---------------------------------------------------------------------------


class TestResourceConflicts:
    def test_person_assigned_across_projects(self, patched_db):
        with db() as conn:
            _setup_two_projects(conn)
            _insert_thing(conn, "person-1", "Alice", type_hint="person")
            _insert_relationship(conn, "r1", "person-1", "task-a1", "assigned_to")
            _insert_relationship(conn, "r2", "person-1", "task-b1", "assigned_to")

        with db() as conn:
            results = find_resource_conflicts(conn)

        assert len(results) == 1
        assert results[0].finding_type == "resource_conflict"
        assert "Alice" in results[0].message

    def test_person_in_single_project_ok(self, patched_db):
        with db() as conn:
            _setup_two_projects(conn)
            _insert_thing(conn, "person-1", "Bob", type_hint="person")
            _insert_relationship(conn, "r1", "person-1", "task-a1", "assigned_to")
            _insert_relationship(conn, "r2", "person-1", "task-a2", "assigned_to")

        with db() as conn:
            results = find_resource_conflicts(conn)

        assert len(results) == 0


# ---------------------------------------------------------------------------
# Thematic connections
# ---------------------------------------------------------------------------


class TestThematicConnections:
    def test_similar_titles_detected(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "proj-a", "Project Alpha", type_hint="project")
            _insert_thing(conn, "proj-b", "Project Beta", type_hint="project")
            _insert_thing(
                conn,
                "task-a1",
                "Implement user authentication login system",
                parent_id="proj-a",
            )
            _insert_thing(
                conn,
                "task-b1",
                "Build user authentication login flow",
                parent_id="proj-b",
            )

        with db() as conn:
            results = find_thematic_connections(conn, min_word_overlap=3)

        assert len(results) == 1
        assert results[0].finding_type == "thematic_connection"
        assert "user" in results[0].extra["overlap_words"]
        assert "authentication" in results[0].extra["overlap_words"]
        assert "login" in results[0].extra["overlap_words"]

    def test_different_titles_not_detected(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "proj-a", "Project Alpha", type_hint="project")
            _insert_thing(conn, "proj-b", "Project Beta", type_hint="project")
            _insert_thing(conn, "task-a1", "Fix database migration", parent_id="proj-a")
            _insert_thing(conn, "task-b1", "Design landing page", parent_id="proj-b")

        with db() as conn:
            results = find_thematic_connections(conn, min_word_overlap=3)

        assert len(results) == 0

    def test_same_project_tasks_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "proj-a", "Project Alpha", type_hint="project")
            _insert_thing(
                conn,
                "task-a1",
                "Implement user authentication login system",
                parent_id="proj-a",
            )
            _insert_thing(
                conn,
                "task-a2",
                "Build user authentication login flow",
                parent_id="proj-a",
            )

        with db() as conn:
            results = find_thematic_connections(conn, min_word_overlap=3)

        assert len(results) == 0


# ---------------------------------------------------------------------------
# Duplicated effort
# ---------------------------------------------------------------------------


class TestDuplicatedEffort:
    def test_highly_similar_tasks_detected(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "proj-a", "Project Alpha", type_hint="project")
            _insert_thing(conn, "proj-b", "Project Beta", type_hint="project")
            _insert_thing(
                conn, "task-a1", "Setup CI/CD pipeline deployment", parent_id="proj-a"
            )
            _insert_thing(
                conn, "task-b1", "Setup CI/CD pipeline deployment", parent_id="proj-b"
            )

        with db() as conn:
            results = find_duplicated_effort(conn)

        assert len(results) == 1
        assert results[0].finding_type == "duplicated_effort"
        assert results[0].extra["similarity"] >= 0.6

    def test_somewhat_different_tasks_not_detected(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "proj-a", "Project Alpha", type_hint="project")
            _insert_thing(conn, "proj-b", "Project Beta", type_hint="project")
            _insert_thing(
                conn, "task-a1", "Setup CI/CD pipeline", parent_id="proj-a"
            )
            _insert_thing(
                conn,
                "task-b1",
                "Design database schema migration strategy",
                parent_id="proj-b",
            )

        with db() as conn:
            results = find_duplicated_effort(conn)

        assert len(results) == 0


# ---------------------------------------------------------------------------
# collect_cross_project_findings
# ---------------------------------------------------------------------------


class TestCollectCrossProjectFindings:
    def test_empty_db(self, patched_db):
        results = collect_cross_project_findings()
        assert results == []

    def test_single_project_returns_empty(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "proj-a", "Only Project", type_hint="project")
            _insert_thing(conn, "task-a1", "Task 1", parent_id="proj-a")

        results = collect_cross_project_findings()
        assert results == []

    def test_two_projects_with_patterns(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "proj-a", "Project Alpha", type_hint="project")
            _insert_thing(conn, "proj-b", "Project Beta", type_hint="project")
            # Identical tasks → duplicated effort
            _insert_thing(
                conn,
                "task-a1",
                "Setup monitoring alerting dashboard system",
                parent_id="proj-a",
            )
            _insert_thing(
                conn,
                "task-b1",
                "Setup monitoring alerting dashboard system",
                parent_id="proj-b",
            )

        results = collect_cross_project_findings()
        types = {f.finding_type for f in results}
        # Should detect both thematic + duplicated for identical tasks
        assert "duplicated_effort" in types


# ---------------------------------------------------------------------------
# persist_findings
# ---------------------------------------------------------------------------


class TestPersistFindings:
    def test_creates_things_with_correct_attributes(self, patched_db):
        from backend.cross_project_sweep import CrossProjectFinding

        findings = [
            CrossProjectFinding(
                finding_type="shared_blocker",
                title="Shared blocker: API outage",
                message="API outage blocks 2 projects",
                related_thing_ids=["task-a1", "task-b1"],
                related_project_ids=["proj-a", "proj-b"],
                priority=2,
            )
        ]

        # Create the related Things first so FK constraints pass
        with db() as conn:
            _insert_thing(conn, "proj-a", "Project A", type_hint="project")
            _insert_thing(conn, "proj-b", "Project B", type_hint="project")
            _insert_thing(conn, "task-a1", "Task A1", parent_id="proj-a")
            _insert_thing(conn, "task-b1", "Task B1", parent_id="proj-b")

        created = persist_findings(findings)

        assert len(created) == 1
        assert created[0]["finding_type"] == "shared_blocker"

        # Verify the Thing was stored correctly
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM things WHERE type_hint = ?", (FINDING_TYPE_HINT,)
            ).fetchone()

        assert row is not None
        assert row["active"] == 1
        assert row["surface"] == 1
        data = json.loads(row["data"])
        assert SWEEP_FINDING_TAG in data["tags"]
        assert data["finding_type"] == "shared_blocker"

    def test_deactivates_previous_findings(self, patched_db):
        from backend.cross_project_sweep import CrossProjectFinding

        with db() as conn:
            _insert_thing(conn, "proj-a", "Project A", type_hint="project")
            _insert_thing(conn, "proj-b", "Project B", type_hint="project")
            _insert_thing(conn, "task-a1", "Task A1", parent_id="proj-a")
            _insert_thing(conn, "task-b1", "Task B1", parent_id="proj-b")

        findings_v1 = [
            CrossProjectFinding(
                finding_type="shared_blocker",
                title="Old finding",
                message="Old msg",
                related_thing_ids=["task-a1"],
                related_project_ids=["proj-a"],
            )
        ]
        persist_findings(findings_v1)

        # Second run should deactivate the first finding
        findings_v2 = [
            CrossProjectFinding(
                finding_type="duplicated_effort",
                title="New finding",
                message="New msg",
                related_thing_ids=["task-b1"],
                related_project_ids=["proj-b"],
            )
        ]
        persist_findings(findings_v2)

        with db() as conn:
            active = conn.execute(
                "SELECT COUNT(*) FROM things WHERE type_hint = ? AND active = 1",
                (FINDING_TYPE_HINT,),
            ).fetchone()[0]
            inactive = conn.execute(
                "SELECT COUNT(*) FROM things WHERE type_hint = ? AND active = 0",
                (FINDING_TYPE_HINT,),
            ).fetchone()[0]

        assert active == 1  # only v2
        assert inactive == 1  # v1 deactivated

    def test_creates_relationships(self, patched_db):
        from backend.cross_project_sweep import CrossProjectFinding

        with db() as conn:
            _insert_thing(conn, "proj-a", "Project A", type_hint="project")
            _insert_thing(conn, "task-a1", "Task A1", parent_id="proj-a")
            _insert_thing(conn, "task-a2", "Task A2", parent_id="proj-a")

        findings = [
            CrossProjectFinding(
                finding_type="thematic_connection",
                title="Theme link",
                message="Connected themes",
                related_thing_ids=["task-a1", "task-a2"],
                related_project_ids=["proj-a"],
            )
        ]
        created = persist_findings(findings)

        with db() as conn:
            rels = conn.execute(
                """SELECT * FROM thing_relationships
                   WHERE from_thing_id = ? AND relationship_type = 'sweep_finding_about'""",
                (created[0]["id"],),
            ).fetchall()

        assert len(rels) == 2
        to_ids = {r["to_thing_id"] for r in rels}
        assert to_ids == {"task-a1", "task-a2"}
