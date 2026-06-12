"""Tests for chat history endpoints."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session
from sqlmodel import select as sel

import backend.db_engine as _engine_mod
from backend.db_models import ChatHistoryRecord, ChatMessageUsageRecord
from backend.routers.chat import _maybe_purge_old_messages


def _append(client: TestClient, session_id: str, role: str, content: str, **kwargs) -> dict:
    payload = {"session_id": session_id, "role": role, "content": content, **kwargs}
    resp = client.post("/api/chat/history", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestAppendMessage:
    def test_append_user_message(self, client):
        msg = _append(client, "sess-1", "user", "Hello!")
        assert msg["session_id"] == "sess-1"
        assert msg["role"] == "user"
        assert msg["content"] == "Hello!"
        assert msg["id"]
        assert msg["timestamp"]

    def test_append_assistant_message(self, client):
        msg = _append(client, "sess-1", "assistant", "Hi there!")
        assert msg["role"] == "assistant"

    def test_append_with_applied_changes(self, client):
        changes = {"created": [{"id": "abc", "title": "New Thing"}]}
        msg = _append(client, "sess-2", "assistant", "Done.", applied_changes=changes)
        assert msg["applied_changes"] == changes

    def test_append_with_datetime_in_applied_changes(self, client):
        """Regression test for #547: datetime objects in applied_changes must not
        raise 'TypeError: Object of type datetime is not JSON serializable'."""
        now = datetime.now(timezone.utc)
        changes = {
            "created": [
                {
                    "id": "dt-thing",
                    "title": "Datetime Thing",
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                }
            ],
        }
        # Should not raise a 500 — datetime values serialized to ISO strings
        msg = _append(client, "sess-dt", "assistant", "Done.", applied_changes=changes)
        assert msg["applied_changes"]["created"][0]["id"] == "dt-thing"

    def test_invalid_role_returns_422(self, client):
        resp = client.post(
            "/api/chat/history",
            json={"session_id": "s1", "role": "admin", "content": "oops"},
        )
        assert resp.status_code == 422

    def test_system_role_accepted(self, client):
        resp = client.post(
            "/api/chat/history",
            json={"session_id": "s1", "role": "system", "content": "briefing context"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "system"

    def test_empty_session_id_returns_422(self, client):
        resp = client.post(
            "/api/chat/history",
            json={"session_id": "", "role": "user", "content": "hi"},
        )
        assert resp.status_code == 422


class TestGetHistory:
    def test_get_empty_history(self, client):
        resp = client.get("/api/chat/history/empty-session")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_history_in_order(self, client):
        _append(client, "sess-order", "user", "First")
        _append(client, "sess-order", "assistant", "Second")
        _append(client, "sess-order", "user", "Third")
        resp = client.get("/api/chat/history/sess-order")
        msgs = resp.json()
        assert len(msgs) == 3
        assert msgs[0]["content"] == "First"
        assert msgs[1]["content"] == "Second"
        assert msgs[2]["content"] == "Third"

    def test_history_isolated_by_session(self, client):
        _append(client, "sess-A", "user", "Session A message")
        _append(client, "sess-B", "user", "Session B message")
        resp = client.get("/api/chat/history/sess-A")
        contents = [m["content"] for m in resp.json()]
        assert "Session A message" in contents
        assert "Session B message" not in contents

    def test_get_history_pagination_limit(self, client):
        for i in range(10):
            _append(client, "sess-page", "user", f"Message {i}")
        resp = client.get("/api/chat/history/sess-page?limit=3")
        msgs = resp.json()
        assert len(msgs) == 3
        # Default (no before) returns most recent messages
        assert msgs[0]["content"] == "Message 7"
        assert msgs[2]["content"] == "Message 9"

    def test_get_history_pagination_before(self, client):
        for i in range(5):
            _append(client, "sess-before", "user", f"Message {i}")
        # Get latest 2 messages
        resp_latest = client.get("/api/chat/history/sess-before?limit=2")
        latest_msgs = resp_latest.json()
        assert len(latest_msgs) == 2
        oldest_id = latest_msgs[0]["id"]
        # Get 2 messages before the oldest loaded
        resp_older = client.get(f"/api/chat/history/sess-before?limit=2&before={oldest_id}")
        older_msgs = resp_older.json()
        assert len(older_msgs) == 2
        # No overlap between the two pages
        latest_ids = {m["id"] for m in latest_msgs}
        older_ids = {m["id"] for m in older_msgs}
        assert not latest_ids & older_ids


class TestChatSessions:
    def test_create_session_returns_201(self, client):
        resp = client.post("/api/chat/sessions", json={"title": "Morning briefing", "origin": "morning_briefing"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Morning briefing"
        assert data["origin"] == "morning_briefing"
        assert data["id"]
        assert data["created_at"]
        assert data["last_active_at"]

    def test_create_session_default_title(self, client):
        resp = client.post("/api/chat/sessions", json={})
        assert resp.status_code == 201
        assert resp.json()["title"] == "New chat"

    def test_create_session_null_origin(self, client):
        resp = client.post("/api/chat/sessions", json={"title": "Ad-hoc"})
        assert resp.status_code == 201
        assert resp.json()["origin"] is None

    def test_create_session_title_too_long_returns_422(self, client):
        resp = client.post("/api/chat/sessions", json={"title": "x" * 501})
        assert resp.status_code == 422

    def test_create_session_origin_too_long_returns_422(self, client):
        resp = client.post("/api/chat/sessions", json={"title": "t", "origin": "x" * 101})
        assert resp.status_code == 422

    def test_list_sessions_empty(self, client):
        resp = client.get("/api/chat/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_sessions_returns_created(self, client):
        client.post("/api/chat/sessions", json={"title": "Session A"})
        client.post("/api/chat/sessions", json={"title": "Session B"})
        resp = client.get("/api/chat/sessions")
        assert resp.status_code == 200
        titles = [s["title"] for s in resp.json()]
        assert "Session A" in titles
        assert "Session B" in titles


class TestDeleteHistory:
    def test_delete_existing_session(self, client):
        _append(client, "sess-del", "user", "Delete me")
        resp = client.delete("/api/chat/history/sess-del")
        assert resp.status_code == 204
        # Confirm gone
        assert client.get("/api/chat/history/sess-del").json() == []

    def test_delete_nonexistent_session_returns_404(self, client):
        resp = client.delete("/api/chat/history/no-such-session")
        assert resp.status_code == 404

    def test_delete_only_affects_target_session(self, client):
        _append(client, "keep-me", "user", "Keep this")
        _append(client, "delete-me", "user", "Delete this")
        client.delete("/api/chat/history/delete-me")
        assert len(client.get("/api/chat/history/keep-me").json()) == 1


class TestChatRetentionPurge:
    """Tests for chat retention purge behavior.

    Note: tests call _maybe_purge_old_messages directly via asyncio to exercise
    the real function end-to-end. The async task is driven to completion with
    asyncio.sleep(0) inside run_until_complete.
    """

    @staticmethod
    def _run_purge(user_id: str, retention: str) -> None:
        async def _drive():
            _maybe_purge_old_messages(user_id)
            await asyncio.sleep(0)

        with patch("backend.routers.settings.get_user_setting", return_value=retention):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_drive())
            finally:
                loop.close()

    def test_purge_deletes_old_messages(self, patched_db):
        user_id = "test-user-retention"
        old_ts = datetime.now(timezone.utc) - timedelta(days=400)

        with Session(_engine_mod.engine) as session:
            session.add(ChatHistoryRecord(
                session_id="purge-sess", role="user", content="Old message",
                user_id=user_id, timestamp=old_ts,
            ))
            session.add(ChatHistoryRecord(
                session_id="purge-sess", role="user", content="Recent message",
                user_id=user_id, timestamp=datetime.now(timezone.utc),
            ))
            session.commit()

        self._run_purge(user_id, "365")

        with Session(_engine_mod.engine) as session:
            records = session.exec(
                sel(ChatHistoryRecord).where(ChatHistoryRecord.user_id == user_id)
            ).all()
        contents = [r.content for r in records]
        assert "Old message" not in contents
        assert "Recent message" in contents

    def test_purge_skipped_when_retention_zero(self, patched_db):
        user_id = "test-user-retention-zero"
        old_ts = datetime.now(timezone.utc) - timedelta(days=400)

        with Session(_engine_mod.engine) as session:
            session.add(ChatHistoryRecord(
                session_id="no-purge-sess", role="user", content="Stay forever",
                user_id=user_id, timestamp=old_ts,
            ))
            session.commit()

        # retention=0 means unlimited — no messages should be deleted
        self._run_purge(user_id, "0")

        with Session(_engine_mod.engine) as session:
            records = session.exec(
                sel(ChatHistoryRecord).where(ChatHistoryRecord.user_id == user_id)
            ).all()
        assert any(r.content == "Stay forever" for r in records)

    def test_purge_skipped_when_retention_negative(self, patched_db):
        user_id = "test-user-retention-negative"
        old_ts = datetime.now(timezone.utc) - timedelta(days=400)

        with Session(_engine_mod.engine) as session:
            session.add(ChatHistoryRecord(
                session_id="neg-purge-sess", role="user", content="Stay forever negative",
                user_id=user_id, timestamp=old_ts,
            ))
            session.commit()

        # Negative retention (guard: <= 0) — no messages should be deleted
        self._run_purge(user_id, "-1")

        with Session(_engine_mod.engine) as session:
            records = session.exec(
                sel(ChatHistoryRecord).where(ChatHistoryRecord.user_id == user_id)
            ).all()
        assert any(r.content == "Stay forever negative" for r in records)

    def test_purge_also_deletes_usage_rows(self, patched_db):
        user_id = "test-user-usage-purge"
        old_ts = datetime.now(timezone.utc) - timedelta(days=400)

        with Session(_engine_mod.engine) as session:
            msg = ChatHistoryRecord(
                session_id="purge-usage-sess", role="user", content="Old msg with usage",
                user_id=user_id, timestamp=old_ts,
            )
            session.add(msg)
            session.flush()
            session.add(ChatMessageUsageRecord(
                chat_message_id=msg.id, model="test-model", input_tokens=10, output_tokens=5,
            ))
            session.commit()
            msg_id = msg.id

        self._run_purge(user_id, "365")

        with Session(_engine_mod.engine) as session:
            orphans = session.exec(
                sel(ChatMessageUsageRecord).where(
                    ChatMessageUsageRecord.chat_message_id == msg_id
                )
            ).all()
        assert orphans == [], "Usage rows must be purged alongside their parent messages"

    def test_purge_function_skips_when_no_user(self):
        # Should return immediately without calling get_user_setting
        with patch("backend.routers.settings.get_user_setting") as mock_get:
            _maybe_purge_old_messages("")
            mock_get.assert_not_called()
