"""Tests for context-change auto-dismissal in dismiss_stale_findings."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.sweep import dismiss_stale_findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow():
    return datetime.now(timezone.utc)


def _insert_thing(conn, thing_id, title, *, active=True, updated_at=None):
    ts = updated_at or _utcnow().isoformat()
    conn.execute(
        """INSERT INTO things
           (id, title, active, surface, created_at, updated_at)
           VALUES (?, ?, ?, 1, ?, ?)""",
        (thing_id, title, int(active), ts, ts),
    )


def _insert_finding(
    conn,
    finding_id,
    *,
    thing_id=None,
    dismissed=0,
    expires_at=None,
    created_at=None,
    context_snapshot=None,
    user_id=None,
):
    ts = created_at or _utcnow().isoformat()
    conn.execute(
        """INSERT INTO sweep_findings
           (id, thing_id, finding_type, message, priority, dismissed,
            created_at, expires_at, context_snapshot, user_id)
           VALUES (?, ?, 'llm_insight', 'test message', 2, ?, ?, ?, ?, ?)""",
        (
            finding_id,
            thing_id,
            dismissed,
            ts,
            expires_at,
            json.dumps(context_snapshot) if context_snapshot else None,
            user_id,
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestContextChangeDismissal:
    def test_context_changed_dismisses_finding(self, patched_db, db):
        """Finding with context_snapshot is dismissed when Thing.updated_at advances."""
        past = (_utcnow() - timedelta(days=2)).isoformat()
        recent = _utcnow().isoformat()

        with db() as conn:
            _insert_thing(conn, "t1", "Updated Title", updated_at=recent)
            _insert_finding(
                conn,
                "sf-ctx1",
                thing_id="t1",
                created_at=past,
                context_snapshot={
                    "title": "Old Title",
                    "active": True,
                    "type_hint": None,
                    "importance": 2,
                    "updated_at": past,
                },
            )

        count = dismiss_stale_findings()

        with db() as conn:
            row = conn.execute(
                "SELECT dismissed, dismissed_reason FROM sweep_findings WHERE id = 'sf-ctx1'"
            ).fetchone()
        assert count == 1
        assert row["dismissed"] == 1
        assert row["dismissed_reason"] == "context_changed"

    def test_unchanged_thing_not_dismissed(self, patched_db, db):
        """Finding is NOT dismissed if Thing.updated_at equals snapshot updated_at."""
        ts = (_utcnow() - timedelta(days=2)).isoformat()

        with db() as conn:
            _insert_thing(conn, "t2", "Same Title", updated_at=ts)
            _insert_finding(
                conn,
                "sf-ctx2",
                thing_id="t2",
                created_at=ts,
                context_snapshot={
                    "title": "Same Title",
                    "active": True,
                    "type_hint": None,
                    "importance": 2,
                    "updated_at": ts,
                },
            )

        count = dismiss_stale_findings()
        assert count == 0

        with db() as conn:
            row = conn.execute(
                "SELECT dismissed FROM sweep_findings WHERE id = 'sf-ctx2'"
            ).fetchone()
        assert row["dismissed"] == 0

    def test_no_snapshot_not_dismissed_by_context_check(self, patched_db, db):
        """Findings with no context_snapshot are skipped by context-change check."""
        past = (_utcnow() - timedelta(days=2)).isoformat()
        recent = _utcnow().isoformat()

        with db() as conn:
            _insert_thing(conn, "t3", "Updated", active=True, updated_at=recent)
            _insert_finding(
                conn,
                "sf-no-snap",
                thing_id="t3",
                created_at=past,
                context_snapshot=None,
            )

        count = dismiss_stale_findings()
        assert count == 0

        with db() as conn:
            row = conn.execute(
                "SELECT dismissed FROM sweep_findings WHERE id = 'sf-no-snap'"
            ).fetchone()
        assert row["dismissed"] == 0

    def test_expired_finding_dismissed_with_reason(self, patched_db, db):
        """Expired findings get dismissed_reason='expired'."""
        past = (_utcnow() - timedelta(days=1)).isoformat()

        with db() as conn:
            _insert_finding(conn, "sf-exp", expires_at=past)

        count = dismiss_stale_findings()

        with db() as conn:
            row = conn.execute(
                "SELECT dismissed, dismissed_reason FROM sweep_findings WHERE id = 'sf-exp'"
            ).fetchone()
        assert count == 1
        assert row["dismissed"] == 1
        assert row["dismissed_reason"] == "expired"

    def test_inactive_thing_dismissed_with_reason(self, patched_db, db):
        """Findings linked to inactive Things get dismissed_reason='linked_thing_inactive'."""
        with db() as conn:
            _insert_thing(conn, "t-dead", "Dead Thing", active=False)
            _insert_finding(conn, "sf-dead", thing_id="t-dead")

        count = dismiss_stale_findings()

        with db() as conn:
            row = conn.execute(
                "SELECT dismissed, dismissed_reason FROM sweep_findings WHERE id = 'sf-dead'"
            ).fetchone()
        assert count == 1
        assert row["dismissed"] == 1
        assert row["dismissed_reason"] == "linked_thing_inactive"
