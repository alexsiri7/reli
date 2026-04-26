"""Tests for chat history endpoints."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient


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
