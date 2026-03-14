"""Tests for chat history endpoints."""

import pytest
from fastapi.testclient import TestClient


def _append(client: TestClient, session_id: str, role: str, content: str, **kwargs) -> dict:
    payload = {"session_id": session_id, "role": role, "content": content, **kwargs}
    resp = client.post("/chat/history", json=payload)
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

    def test_invalid_role_returns_422(self, client):
        resp = client.post(
            "/chat/history",
            json={"session_id": "s1", "role": "system", "content": "oops"},
        )
        assert resp.status_code == 422

    def test_empty_session_id_returns_422(self, client):
        resp = client.post(
            "/chat/history",
            json={"session_id": "", "role": "user", "content": "hi"},
        )
        assert resp.status_code == 422


class TestGetHistory:
    def test_get_empty_history(self, client):
        resp = client.get("/chat/history/empty-session")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_history_in_order(self, client):
        _append(client, "sess-order", "user", "First")
        _append(client, "sess-order", "assistant", "Second")
        _append(client, "sess-order", "user", "Third")
        resp = client.get("/chat/history/sess-order")
        msgs = resp.json()
        assert len(msgs) == 3
        assert msgs[0]["content"] == "First"
        assert msgs[1]["content"] == "Second"
        assert msgs[2]["content"] == "Third"

    def test_history_isolated_by_session(self, client):
        _append(client, "sess-A", "user", "Session A message")
        _append(client, "sess-B", "user", "Session B message")
        resp = client.get("/chat/history/sess-A")
        contents = [m["content"] for m in resp.json()]
        assert "Session A message" in contents
        assert "Session B message" not in contents

    def test_get_history_pagination_limit(self, client):
        for i in range(10):
            _append(client, "sess-page", "user", f"Message {i}")
        resp = client.get("/chat/history/sess-page?limit=3")
        assert len(resp.json()) == 3

    def test_get_history_pagination_offset(self, client):
        for i in range(5):
            _append(client, "sess-offset", "user", f"Message {i}")
        resp_first = client.get("/chat/history/sess-offset?limit=2&offset=0")
        resp_second = client.get("/chat/history/sess-offset?limit=2&offset=2")
        first_ids = [m["id"] for m in resp_first.json()]
        second_ids = [m["id"] for m in resp_second.json()]
        assert not set(first_ids) & set(second_ids)  # no overlap


class TestDeleteHistory:
    def test_delete_existing_session(self, client):
        _append(client, "sess-del", "user", "Delete me")
        resp = client.delete("/chat/history/sess-del")
        assert resp.status_code == 204
        # Confirm gone
        assert client.get("/chat/history/sess-del").json() == []

    def test_delete_nonexistent_session_returns_404(self, client):
        resp = client.delete("/chat/history/no-such-session")
        assert resp.status_code == 404

    def test_delete_only_affects_target_session(self, client):
        _append(client, "keep-me", "user", "Keep this")
        _append(client, "delete-me", "user", "Delete this")
        client.delete("/chat/history/delete-me")
        assert len(client.get("/chat/history/keep-me").json()) == 1
