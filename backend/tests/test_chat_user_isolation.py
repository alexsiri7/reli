"""Tests for cross-user isolation in chat session endpoints.

Verifies that User B cannot see or modify User A's chat sessions.
Uses direct DB setup + single authenticated client to avoid fixture conflicts.
"""

from sqlmodel import Session

import backend.db_engine as _engine_mod
from backend.db_models import ChatSessionRecord


def _seed_session_for_user(user_id: str, title: str = "User A Session") -> str:
    """Insert a chat session directly via ORM for the given user."""
    import uuid

    session_id = str(uuid.uuid4())
    with Session(_engine_mod.engine) as session:
        record = ChatSessionRecord(id=session_id, user_id=user_id, title=title)
        session.add(record)
        session.commit()
    return session_id


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
