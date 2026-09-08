"""Tests for the GDPR export and right-to-erasure endpoints.

Uses a single authenticated client (``other_client``) plus direct ORM
seeding for the "other" user's data, per the conftest warning against
holding two authenticated-client fixtures (and their app.dependency_overrides
mutations) at once.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

import backend.db_engine as engine_module
from backend.db_models import ChatSessionRecord, ThingRecord


def _seed_thing(user_id: str, title: str) -> str:
    with Session(engine_module.engine) as session:
        record = ThingRecord(title=title, user_id=user_id)
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


def _seed_chat_session(user_id: str, title: str) -> str:
    with Session(engine_module.engine) as session:
        record = ChatSessionRecord(user_id=user_id, title=title)
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


class TestGdprExport:
    def test_export_returns_only_the_requesting_users_data(self, other_client, patched_db):
        _seed_thing("user-a", "User A's private thing")
        _seed_chat_session("user-a", "User A's private chat")
        other_thing_id = _seed_thing("other-user", "Other user's thing")
        other_session_id = _seed_chat_session("other-user", "Other user's chat")

        resp = other_client.get("/api/gdpr/export")
        assert resp.status_code == 200
        data = resp.json()

        thing_ids = {t["id"] for t in data["things"]}
        session_ids = {s["id"] for s in data["chat_sessions"]}
        assert thing_ids == {other_thing_id}
        assert session_ids == {other_session_id}


class TestGdprDeleteAll:
    def test_erasure_deletes_requesting_users_rows(self, other_client, patched_db):
        thing_id = _seed_thing("other-user", "Other user's thing")
        session_id = _seed_chat_session("other-user", "Other user's chat")

        resp = other_client.delete("/api/gdpr/delete-all")
        assert resp.status_code == 200

        with Session(engine_module.engine) as session:
            assert session.get(ThingRecord, thing_id) is None
            assert session.get(ChatSessionRecord, session_id) is None

    def test_user_bs_data_survives_user_as_erasure(self, other_client, patched_db):
        survivor_thing_id = _seed_thing("user-a", "User A's thing")
        survivor_session_id = _seed_chat_session("user-a", "User A's chat")
        _seed_thing("other-user", "Other user's thing")

        resp = other_client.delete("/api/gdpr/delete-all")
        assert resp.status_code == 200

        with Session(engine_module.engine) as session:
            assert session.get(ThingRecord, survivor_thing_id) is not None
            assert session.get(ChatSessionRecord, survivor_session_id) is not None

    def test_unauthenticated_request_is_rejected(self, patched_db):
        with patch("backend.auth.SECRET_KEY", "test-secret-key"):
            from backend.main import app

            with TestClient(app) as client:
                resp = client.delete("/api/gdpr/delete-all")

        assert resp.status_code == 401
