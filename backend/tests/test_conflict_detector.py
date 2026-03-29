"""Tests for the real-time conflict detection engine."""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

import pytest
from sqlmodel import Session

import backend.db_engine as _engine_mod
from backend.conflict_detector import (
    detect_all_conflicts,
    detect_blocking_chains,
    detect_deadline_conflicts,
    detect_schedule_overlaps,
)
from backend.database import db


@pytest.fixture(autouse=True)
def _fresh_db(patched_db):
    """Use the shared patched_db fixture from conftest."""


def _insert_thing(
    title: str,
    data: dict | None = None,
    checkin_date: str | None = None,
    active: bool = True,
) -> str:
    thing_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            """INSERT INTO things
               (id, title, type_hint, importance, active, surface, data, checkin_date, created_at, updated_at)
               VALUES (?, ?, 'task', 2, ?, 1, ?, ?, datetime('now'), datetime('now'))""",
            (thing_id, title, int(active), json.dumps(data) if data else None, checkin_date),
        )
    return thing_id


def _insert_relationship(from_id: str, to_id: str, rel_type: str) -> str:
    rel_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type) VALUES (?, ?, ?, ?)",
            (rel_id, from_id, to_id, rel_type),
        )
    return rel_id


class TestBlockingChains:
    def test_detects_blocker_with_deadline(self):
        """Should detect when a blocked Thing has an approaching deadline."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        blocked = _insert_thing("Deploy feature", data={"deadline": tomorrow})
        blocker = _insert_thing("Code review")
        _insert_relationship(blocker, blocked, "blocks")

        with Session(_engine_mod.engine) as session:
            alerts = detect_blocking_chains(session)

        assert len(alerts) == 1
        assert alerts[0].alert_type == "blocking_chain"
        assert alerts[0].severity == "critical"
        assert "Deploy feature" in alerts[0].message
        assert "Code review" in alerts[0].message

    def test_detects_depends_on_relationship(self):
        """Should detect depends-on relationships as blockers."""
        next_week = (date.today() + timedelta(days=5)).isoformat()
        dependent = _insert_thing("Launch", data={"deadline": next_week})
        dependency = _insert_thing("Build API")
        _insert_relationship(dependent, dependency, "depends-on")

        with Session(_engine_mod.engine) as session:
            alerts = detect_blocking_chains(session)

        assert len(alerts) == 1
        assert "Launch" in alerts[0].message
        assert "Build API" in alerts[0].message

    def test_inactive_blocker_not_flagged(self):
        """Should not flag if blocker is inactive (completed)."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        blocked = _insert_thing("Deploy", data={"deadline": tomorrow})
        blocker = _insert_thing("Review", active=False)
        _insert_relationship(blocker, blocked, "blocks")

        with Session(_engine_mod.engine) as session:
            alerts = detect_blocking_chains(session)

        assert len(alerts) == 0

    def test_no_deadline_still_flagged_as_info(self):
        """Should flag active blockers even without a deadline, as info."""
        blocked = _insert_thing("Feature X")
        blocker = _insert_thing("Prerequisite Y")
        _insert_relationship(blocker, blocked, "blocks")

        with Session(_engine_mod.engine) as session:
            alerts = detect_blocking_chains(session)

        assert len(alerts) == 1
        assert alerts[0].severity == "info"

    def test_overdue_deadline_critical(self):
        """Should flag overdue blocked items as critical."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        blocked = _insert_thing("Overdue task", data={"deadline": yesterday})
        blocker = _insert_thing("Blocker")
        _insert_relationship(blocker, blocked, "blocks")

        with Session(_engine_mod.engine) as session:
            alerts = detect_blocking_chains(session, window_days=14)

        assert len(alerts) == 1
        assert alerts[0].severity == "critical"
        assert "overdue" in alerts[0].message


class TestScheduleOverlaps:
    def test_detects_overlap_between_related_things(self):
        """Should detect overlapping date ranges on related Things."""
        start1 = (date.today() + timedelta(days=1)).isoformat()
        end1 = (date.today() + timedelta(days=5)).isoformat()
        start2 = (date.today() + timedelta(days=3)).isoformat()
        end2 = (date.today() + timedelta(days=7)).isoformat()

        thing_a = _insert_thing("Meeting A", data={"start_date": start1, "end_date": end1})
        thing_b = _insert_thing("Meeting B", data={"start_date": start2, "end_date": end2})
        _insert_relationship(thing_a, thing_b, "related-to")

        with Session(_engine_mod.engine) as session:
            alerts = detect_schedule_overlaps(session)

        assert len(alerts) == 1
        assert alerts[0].alert_type == "schedule_overlap"
        assert "Meeting A" in alerts[0].message
        assert "Meeting B" in alerts[0].message

    def test_no_overlap_no_alert(self):
        """Should not flag non-overlapping date ranges."""
        start1 = (date.today() + timedelta(days=1)).isoformat()
        end1 = (date.today() + timedelta(days=2)).isoformat()
        start2 = (date.today() + timedelta(days=5)).isoformat()
        end2 = (date.today() + timedelta(days=7)).isoformat()

        thing_a = _insert_thing("Event A", data={"start_date": start1, "end_date": end1})
        thing_b = _insert_thing("Event B", data={"start_date": start2, "end_date": end2})
        _insert_relationship(thing_a, thing_b, "related-to")

        with Session(_engine_mod.engine) as session:
            alerts = detect_schedule_overlaps(session)

        assert len(alerts) == 0

    def test_unrelated_things_not_flagged(self):
        """Should not flag overlaps between unrelated Things."""
        start1 = (date.today() + timedelta(days=1)).isoformat()
        end1 = (date.today() + timedelta(days=5)).isoformat()

        _insert_thing("Event A", data={"start_date": start1, "end_date": end1})
        _insert_thing("Event B", data={"start_date": start1, "end_date": end1})

        with Session(_engine_mod.engine) as session:
            alerts = detect_schedule_overlaps(session)

        assert len(alerts) == 0


class TestDeadlineConflicts:
    def test_detects_dependency_deadline_after_dependent(self):
        """Should flag when a dependency is due after its dependent."""
        dep_deadline = (date.today() + timedelta(days=10)).isoformat()
        depn_deadline = (date.today() + timedelta(days=15)).isoformat()

        dependent = _insert_thing("Ship feature", data={"deadline": dep_deadline})
        dependency = _insert_thing("API ready", data={"deadline": depn_deadline})
        _insert_relationship(dependent, dependency, "depends-on")

        with Session(_engine_mod.engine) as session:
            alerts = detect_deadline_conflicts(session)

        assert len(alerts) == 1
        assert alerts[0].alert_type == "deadline_conflict"
        assert "Ship feature" in alerts[0].message
        assert "API ready" in alerts[0].message

    def test_no_conflict_when_dependency_due_first(self):
        """Should not flag when dependency deadline is before dependent."""
        dep_deadline = (date.today() + timedelta(days=15)).isoformat()
        depn_deadline = (date.today() + timedelta(days=5)).isoformat()

        dependent = _insert_thing("Ship", data={"deadline": dep_deadline})
        dependency = _insert_thing("Build", data={"deadline": depn_deadline})
        _insert_relationship(dependent, dependency, "depends-on")

        with Session(_engine_mod.engine) as session:
            alerts = detect_deadline_conflicts(session)

        assert len(alerts) == 0

    def test_blocks_relationship_detects_conflict(self):
        """Should detect deadline conflict via blocks relationship too."""
        blocker_deadline = (date.today() + timedelta(days=20)).isoformat()
        blocked_deadline = (date.today() + timedelta(days=10)).isoformat()

        blocker = _insert_thing("Prerequisite", data={"deadline": blocker_deadline})
        blocked = _insert_thing("Main task", data={"deadline": blocked_deadline})
        _insert_relationship(blocker, blocked, "blocks")

        with Session(_engine_mod.engine) as session:
            alerts = detect_deadline_conflicts(session)

        assert len(alerts) == 1
        assert alerts[0].alert_type == "deadline_conflict"


class TestDetectAll:
    def test_combined_and_deduplicated(self):
        """Should combine all detectors and deduplicate."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        next_month = (date.today() + timedelta(days=30)).isoformat()

        blocked = _insert_thing("Urgent task", data={"deadline": tomorrow})
        blocker = _insert_thing("Blocker task", data={"deadline": next_month})
        _insert_relationship(blocker, blocked, "blocks")

        alerts = detect_all_conflicts()
        # Should have both blocking_chain and deadline_conflict
        types = {a.alert_type for a in alerts}
        assert "blocking_chain" in types
        assert "deadline_conflict" in types

    def test_empty_db_no_alerts(self):
        """Should return empty list for empty database."""
        alerts = detect_all_conflicts()
        assert alerts == []


class TestConflictsEndpoint:
    def test_get_conflicts_returns_list(self, client):
        resp = client.get("/api/conflicts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_conflicts_with_data(self, client):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        blocked = _insert_thing("Task A", data={"deadline": tomorrow})
        blocker = _insert_thing("Task B")
        _insert_relationship(blocker, blocked, "blocks")

        resp = client.get("/api/conflicts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        assert data[0]["alert_type"] == "blocking_chain"
        assert "thing_ids" in data[0]
        assert "severity" in data[0]

    def test_proactivity_off_returns_empty(self, client):
        """Setting proactivity_level to 'off' should return no alerts."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        blocked = _insert_thing("Task A", data={"deadline": tomorrow})
        blocker = _insert_thing("Task B")
        _insert_relationship(blocker, blocked, "blocks")

        # Set proactivity to off via the settings API
        resp = client.put(
            "/api/settings/user",
            json={"proactivity_level": "off"},
        )
        assert resp.status_code in (200, 401)  # 401 if auth required

        # If auth prevents setting, test the filter function directly instead
        if resp.status_code == 401:
            from backend.conflict_detector import detect_all_conflicts
            from backend.routers.conflicts import _filter_by_proactivity

            alerts = detect_all_conflicts()
            filtered = _filter_by_proactivity(alerts, "off")
            assert filtered == []
        else:
            resp = client.get("/api/conflicts")
            assert resp.status_code == 200
            assert resp.json() == []
