"""Tests for POST /api/preferences/{thing_id}/feedback (SEC-27 / issue #1205 deduplication)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

import backend.db_engine as _engine_mod
from backend.auth import require_user
from backend.db_models import ThingRecord
from backend.main import app

THING_ID = "pref-test-1"
USER_ID = "user-sec27"


@pytest.fixture()
def client(patched_db) -> TestClient:
    app.dependency_overrides[require_user] = lambda: USER_ID
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(require_user, None)


@pytest.fixture()
def preference(patched_db):
    now = datetime.now(timezone.utc)
    with Session(_engine_mod.engine) as session:
        session.add(
            ThingRecord(
                id=THING_ID,
                title="Comm Style",
                type_hint="preference",
                active=True,
                user_id=USER_ID,
                created_at=now,
                updated_at=now,
                data={"confidence": 0.5},
            )
        )
        session.commit()


class TestPreferenceFeedbackDedup:
    def test_first_feedback_accepted(self, client, preference):
        resp = client.post(f"/api/preferences/{THING_ID}/feedback", json={"accurate": True})
        assert resp.status_code == 200
        assert resp.json()["updated"] is True

    def test_second_immediate_feedback_rejected(self, client, preference):
        client.post(f"/api/preferences/{THING_ID}/feedback", json={"accurate": True})
        # Same payload rejected
        resp = client.post(f"/api/preferences/{THING_ID}/feedback", json={"accurate": True})
        assert resp.status_code == 200
        assert resp.json() == {"id": THING_ID, "updated": False}
        # Opposite payload also rejected — cooldown is payload-agnostic
        resp2 = client.post(f"/api/preferences/{THING_ID}/feedback", json={"accurate": False})
        assert resp2.status_code == 200
        assert resp2.json() == {"id": THING_ID, "updated": False}

    def test_feedback_after_cooldown_accepted(self, client, preference):
        from backend.routers import preferences as pref_mod

        # Backdate last_feedback_at beyond the cooldown window
        past = datetime.now(timezone.utc) - timedelta(seconds=pref_mod._FEEDBACK_COOLDOWN_SECONDS + 1)
        with Session(_engine_mod.engine) as session:
            record = session.get(ThingRecord, THING_ID)
            data = dict(record.data or {})
            data["last_feedback_at"] = past.isoformat()
            record.data = data
            session.add(record)
            session.commit()

        resp = client.post(f"/api/preferences/{THING_ID}/feedback", json={"accurate": True})
        assert resp.status_code == 200
        assert resp.json()["updated"] is True

    def test_confidence_not_pumped_above_max(self, client, preference):
        from backend.routers import preferences as pref_mod

        # Force cooldown elapsed between calls by backdating each time
        for _ in range(15):
            past = datetime.now(timezone.utc) - timedelta(seconds=pref_mod._FEEDBACK_COOLDOWN_SECONDS + 1)
            with Session(_engine_mod.engine) as session:
                record = session.get(ThingRecord, THING_ID)
                data = dict(record.data or {})
                data["last_feedback_at"] = past.isoformat()
                record.data = data
                session.add(record)
                session.commit()
            client.post(f"/api/preferences/{THING_ID}/feedback", json={"accurate": True})

        with Session(_engine_mod.engine) as session:
            record = session.get(ThingRecord, THING_ID)
            assert record.data["confidence"] <= 1.0

    def test_not_found_returns_404(self, client):
        resp = client.post("/api/preferences/nonexistent/feedback", json={"accurate": True})
        assert resp.status_code == 404

    @pytest.mark.parametrize("bad_value", ["not-a-date", 123, "", "2026-99-99T00:00:00"])
    def test_malformed_last_feedback_at_proceeds_normally(self, client, preference, bad_value):
        # Arrange: store a malformed timestamp directly in the record
        with Session(_engine_mod.engine) as session:
            record = session.get(ThingRecord, THING_ID)
            data = dict(record.data or {})
            data["last_feedback_at"] = bad_value
            record.data = data
            session.add(record)
            session.commit()

        # Act: submit feedback — should not be blocked by the malformed value
        resp = client.post(f"/api/preferences/{THING_ID}/feedback", json={"accurate": True})

        # Assert: proceeds normally
        assert resp.status_code == 200
        assert resp.json()["updated"] is True

    def test_confidence_not_pumped_below_min(self, client, preference):
        from backend.routers import preferences as pref_mod

        # Force cooldown elapsed between calls by backdating each time
        for _ in range(15):
            past = datetime.now(timezone.utc) - timedelta(seconds=pref_mod._FEEDBACK_COOLDOWN_SECONDS + 1)
            with Session(_engine_mod.engine) as session:
                record = session.get(ThingRecord, THING_ID)
                data = dict(record.data or {})
                data["last_feedback_at"] = past.isoformat()
                record.data = data
                session.add(record)
                session.commit()
            client.post(f"/api/preferences/{THING_ID}/feedback", json={"accurate": False})

        with Session(_engine_mod.engine) as session:
            record = session.get(ThingRecord, THING_ID)
            assert record.data["confidence"] >= 0.0
