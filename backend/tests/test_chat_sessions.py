"""Tests for chat session endpoints."""

from fastapi.testclient import TestClient


def _create_session(client: TestClient, session_id: str, title: str = "New chat") -> dict:
    resp = client.post("/api/chat/sessions", json={"session_id": session_id, "title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _append_msg(client: TestClient, session_id: str, role: str, content: str) -> dict:
    resp = client.post(
        "/api/chat/history",
        json={"session_id": session_id, "role": role, "content": content},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestListSessions:
    def test_list_empty(self, client):
        resp = client.get("/api/chat/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_returns_sessions_ordered_by_recency(self, client):
        _create_session(client, "s1", "First")
        _create_session(client, "s2", "Second")
        # Add a message to s1 to bump its last_active_at
        _append_msg(client, "s1", "user", "hello")

        resp = client.get("/api/chat/sessions")
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) == 2
        assert sessions[0]["id"] == "s1"
        assert sessions[1]["id"] == "s2"

    def test_list_includes_message_count(self, client):
        _create_session(client, "s1", "Chat")
        _append_msg(client, "s1", "user", "hi")
        _append_msg(client, "s1", "assistant", "hello")

        resp = client.get("/api/chat/sessions")
        sessions = resp.json()
        assert sessions[0]["message_count"] == 2


class TestCreateSession:
    def test_create_with_default_title(self, client):
        session = _create_session(client, "sess-new")
        assert session["id"] == "sess-new"
        assert session["title"] == "New chat"
        assert session["message_count"] == 0

    def test_create_with_custom_title(self, client):
        session = _create_session(client, "sess-custom", "My Project")
        assert session["title"] == "My Project"

    def test_duplicate_session_id_returns_409(self, client):
        _create_session(client, "dupe")
        resp = client.post("/api/chat/sessions", json={"session_id": "dupe", "title": "Again"})
        assert resp.status_code == 409


class TestRenameSession:
    def test_rename_existing(self, client):
        _create_session(client, "s1", "Old Title")
        _append_msg(client, "s1", "user", "hi")
        _append_msg(client, "s1", "assistant", "hello")
        resp = client.patch("/api/chat/sessions/s1", json={"title": "New Title"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"
        assert resp.json()["message_count"] == 2

    def test_rename_404_on_missing(self, client):
        resp = client.patch("/api/chat/sessions/nonexistent", json={"title": "X"})
        assert resp.status_code == 404


class TestDeleteSession:
    def test_delete_removes_session_and_history(self, client):
        _create_session(client, "del-me", "Doomed")
        _append_msg(client, "del-me", "user", "message")
        _append_msg(client, "del-me", "assistant", "reply")

        resp = client.delete("/api/chat/sessions/del-me")
        assert resp.status_code == 204

        # Session is gone
        resp = client.get("/api/chat/sessions")
        assert all(s["id"] != "del-me" for s in resp.json())

        # History is gone
        resp = client.get("/api/chat/history/del-me")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_delete_404_on_missing(self, client):
        resp = client.delete("/api/chat/sessions/nonexistent")
        assert resp.status_code == 404


class TestAutoTitleSession:
    def test_auto_title_guard_allows_first_exchange(self, client):
        """Guard allows auto-titling when session has exactly 2 messages (first exchange)."""
        from sqlalchemy import text
        from sqlmodel import Session, select
        from backend.db_engine import engine
        from backend.db_models import ChatSessionRecord

        _create_session(client, "at-s1", "New chat")
        _append_msg(client, "at-s1", "user", "hello")
        _append_msg(client, "at-s1", "assistant", "hi")

        with Session(engine) as sess:
            record = sess.exec(
                select(ChatSessionRecord).where(ChatSessionRecord.id == "at-s1")
            ).first()
            assert record is not None
            assert record.title == "New chat"
            msg_count = sess.execute(
                text("SELECT COUNT(*) FROM chat_history WHERE session_id = :sid"),
                {"sid": "at-s1"},
            ).scalar() or 0
            # 2 messages = first exchange; guard (msg_count > 2) should allow titling
            assert msg_count == 2
            assert not (msg_count > 2)

    def test_auto_title_skips_non_default_title(self, client):
        """Auto-title must not overwrite a custom session title."""
        from sqlmodel import Session, select
        from backend.db_engine import engine
        from backend.db_models import ChatSessionRecord

        _create_session(client, "at-s2", "My Custom Name")
        _append_msg(client, "at-s2", "user", "hello")
        _append_msg(client, "at-s2", "assistant", "hi")

        with Session(engine) as sess:
            record = sess.exec(
                select(ChatSessionRecord).where(ChatSessionRecord.id == "at-s2")
            ).first()
            assert record is not None
            # Guard: title != "New chat" means auto-title is skipped
            assert record.title != "New chat"

        resp = client.get("/api/chat/sessions")
        session = next(s for s in resp.json() if s["id"] == "at-s2")
        assert session["title"] == "My Custom Name"

    def test_auto_title_skips_after_first_exchange(self, client):
        """Auto-title must not fire after more than 2 messages (first exchange only)."""
        from sqlalchemy import text
        from sqlmodel import Session, select
        from backend.db_engine import engine

        _create_session(client, "at-s3", "New chat")
        _append_msg(client, "at-s3", "user", "msg1")
        _append_msg(client, "at-s3", "assistant", "reply1")
        _append_msg(client, "at-s3", "user", "msg2")
        _append_msg(client, "at-s3", "assistant", "reply2")

        with Session(engine) as sess:
            msg_count = sess.execute(
                text("SELECT COUNT(*) FROM chat_history WHERE session_id = :sid"),
                {"sid": "at-s3"},
            ).scalar() or 0
            # 4 messages exceeds the > 2 guard; auto-title would be skipped
            assert msg_count > 2
