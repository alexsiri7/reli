"""Tests for POST /api/preferences/{thing_id}/feedback (SEC-27 deduplication)."""

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
        resp = client.post(f"/api/preferences/{THING_ID}/feedback", json={"accurate": True})
        assert resp.status_code == 200
        assert resp.json()["updated"] is False

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

    def test_not_found_returns_404(self, client, patched_db):
        resp = client.post("/api/preferences/nonexistent/feedback", json={"accurate": True})
        assert resp.status_code == 404
