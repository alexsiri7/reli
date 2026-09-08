"""Tests for cross-user isolation in chat session endpoints.

Verifies that User B cannot see or modify User A's chat sessions.
Uses direct DB setup + single authenticated client to avoid fixture conflicts.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import backend.db_engine as _engine_mod
from backend.db_models import ChatHistoryRecord, ChatSessionRecord, UsageLogRecord
from backend.response_agent import ResponseResult

_MOCK_REASONING_RESULT = {
    "applied_changes": {"created": [], "updated": [], "deleted": [], "merged": [], "relationships_created": []},
    "fetched_context": {"things": [], "relationships": []},
    "questions_for_user": [],
    "priority_question": "",
    "reasoning_summary": "No changes needed.",
    "briefing_mode": False,
}


def _seed_session_for_user(user_id: str, title: str = "User A Session") -> str:
    """Insert a chat session directly via ORM for the given user."""
    import uuid

    session_id = str(uuid.uuid4())
    with Session(_engine_mod.engine) as session:
        record = ChatSessionRecord(id=session_id, user_id=user_id, title=title)
        session.add(record)
        session.commit()
    return session_id


def _seed_chat_history(user_id: str, session_id: str, content: str = "hello") -> int:
    """Insert a chat history row directly via ORM for the given user/session."""
    with Session(_engine_mod.engine) as session:
        record = ChatHistoryRecord(session_id=session_id, role="user", content=content, user_id=user_id)
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


def _seed_usage_log(user_id: str, session_id: str) -> int:
    """Insert a usage log row directly via ORM for the given user/session."""
    with Session(_engine_mod.engine) as session:
        record = UsageLogRecord(session_id=session_id, model="test-model", user_id=user_id)
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


class TestChatSessionIsolation:
    def test_user_b_cannot_see_user_a_sessions(self, other_client, patched_db):
        """User B lists sessions → must see 0 of User A's sessions."""
        # Seed a session owned by user-a directly in DB
        _seed_session_for_user("user-a", "User A's private chat")

        # other_client is authenticated as "other-user" — should see 0 sessions
        resp = other_client.get("/api/chat/sessions")
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    def test_user_b_cannot_rename_user_a_session(self, other_client, patched_db):
        """User B attempting to rename User A's session gets 404."""
        session_id = _seed_session_for_user("user-a", "Original Title")

        # other_client tries to rename
        resp = other_client.patch(
            f"/api/chat/sessions/{session_id}",
            json={"title": "hacked"},
        )
        assert resp.status_code == 404

        # Verify title unchanged via direct DB read
        with Session(_engine_mod.engine) as session:
            record = session.get(ChatSessionRecord, session_id)
            assert record.title == "Original Title"

    def test_user_b_cannot_delete_user_a_session(self, other_client, patched_db):
        """User B attempting to delete User A's session gets 404."""
        session_id = _seed_session_for_user("user-a", "Protected Session")

        # other_client tries to delete
        resp = other_client.delete(f"/api/chat/sessions/{session_id}")
        assert resp.status_code == 404

        # Verify session still exists via direct DB read
        with Session(_engine_mod.engine) as session:
            record = session.get(ChatSessionRecord, session_id)
            assert record is not None


class TestMigrateSessionIsolation:
    def test_user_b_cannot_migrate_user_as_session(self, other_client, patched_db):
        """User B migrating User A's session gets 403 and nothing moves."""
        old_session_id = _seed_session_for_user("user-a", "User A's chat")
        history_id = _seed_chat_history("user-a", old_session_id)
        usage_id = _seed_usage_log("user-a", old_session_id)
        new_session_id = "new-session-id"

        resp = other_client.post(
            "/api/chat/migrate-session",
            json={"old_session_id": old_session_id, "new_session_id": new_session_id},
        )
        assert resp.status_code == 403

        with Session(_engine_mod.engine) as session:
            history = session.get(ChatHistoryRecord, history_id)
            usage = session.get(UsageLogRecord, usage_id)
            assert history.session_id == old_session_id
            assert usage.session_id == old_session_id

    def test_user_migrates_own_session_history_and_usage(self, other_client, patched_db):
        """Migrating your own session moves its history and usage rows to the new session id."""
        old_session_id = _seed_session_for_user("other-user", "Old chat")
        new_session_id = _seed_session_for_user("other-user", "New chat")
        history_id = _seed_chat_history("other-user", old_session_id)
        usage_id = _seed_usage_log("other-user", old_session_id)

        resp = other_client.post(
            "/api/chat/migrate-session",
            json={"old_session_id": old_session_id, "new_session_id": new_session_id},
        )
        assert resp.status_code == 200
        assert resp.json()["migrated"] == 2

        with Session(_engine_mod.engine) as session:
            history = session.get(ChatHistoryRecord, history_id)
            usage = session.get(UsageLogRecord, usage_id)
            assert history.session_id == new_session_id
            assert usage.session_id == new_session_id


class TestChatExchangeCrossUserSessionId:
    @pytest.mark.xfail(
        reason=(
            "_persist_exchange (chat.py:664-677) detects a session_id owned by another "
            "user and tries to insert a new ChatSessionRecord with the SAME id instead of "
            "a fresh one, which the DB's primary key constraint rejects — crashes with "
            "IntegrityError instead of forking a new session. Reported to mayor."
        ),
        strict=False,
    )
    def test_posting_to_another_users_session_id_does_not_corrupt_it(self, patched_db):
        """POST /api/chat as user A with a session_id owned by user B must not touch B's data.

        Today this crashes (see xfail reason) rather than cleanly forking a new session for A.
        """
        victim_session_id = _seed_session_for_user("other-user", "Victim's chat")
        victim_history_id = _seed_chat_history("other-user", victim_session_id, "Victim's message")

        from backend.auth import require_user
        from backend.main import app

        saved = app.dependency_overrides.get(require_user)
        app.dependency_overrides[require_user] = lambda: "user-a"
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                with (
                    patch("backend.pipeline.run_reasoning_agent", new=AsyncMock(return_value=_MOCK_REASONING_RESULT)),
                    patch("backend.pipeline.run_response_agent", new=AsyncMock(return_value=ResponseResult(text="hi"))),
                ):
                    resp = c.post("/api/chat", json={"session_id": victim_session_id, "message": "hijack attempt"})
        finally:
            if saved is None:
                app.dependency_overrides.pop(require_user, None)
            else:
                app.dependency_overrides[require_user] = saved

        assert resp.status_code == 200

        with Session(_engine_mod.engine) as session:
            victim_session = session.get(ChatSessionRecord, victim_session_id)
            assert victim_session.user_id == "other-user"
            victim_history = session.exec(
                select(ChatHistoryRecord).where(ChatHistoryRecord.session_id == victim_session_id)
            ).all()
            assert {h.id for h in victim_history} == {victim_history_id}
