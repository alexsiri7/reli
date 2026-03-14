"""Tests for POST /chat multi-agent pipeline endpoint."""

import json
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_CONTEXT_RESULT = {
    "search_queries": ["test query"],
    "filter_params": {"active_only": True, "type_hint": None},
}

MOCK_REASONING_RESULT = {
    "storage_changes": {"create": [], "update": [], "delete": []},
    "questions_for_user": [],
    "reasoning_summary": "No changes needed.",
}

MOCK_REPLY = "I understand, no changes were needed."


def _patch_agents(
    context_result=None,
    reasoning_result=None,
    reply=None,
):
    """Return a context manager patching all agent functions."""
    from unittest.mock import patch

    ctx = context_result or MOCK_CONTEXT_RESULT
    rea = reasoning_result or MOCK_REASONING_RESULT
    rep = reply or MOCK_REPLY

    return [
        patch("backend.routers.chat.run_context_agent", new=AsyncMock(return_value=ctx)),
        patch("backend.routers.chat.run_reasoning_agent", new=AsyncMock(return_value=rea)),
        patch("backend.routers.chat.run_response_agent", new=AsyncMock(return_value=rep)),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestChatPipeline:
    async def test_basic_chat_returns_200(self, async_client):
        patches = _patch_agents()
        with patches[0], patches[1], patches[2]:
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "s1", "message": "Hello"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "s1"
        assert data["reply"] == MOCK_REPLY
        assert "applied_changes" in data
        assert "questions_for_user" in data

    async def test_chat_persists_messages_to_history(self, async_client):
        patches = _patch_agents()
        with patches[0], patches[1], patches[2]:
            await async_client.post(
                "/api/chat",
                json={"session_id": "persist-sess", "message": "Remember this"},
            )
        # History should have both user and assistant messages
        resp = await async_client.get("/api/chat/history/persist-sess")
        msgs = resp.json()
        roles = [m["role"] for m in msgs]
        assert "user" in roles
        assert "assistant" in roles

    async def test_chat_with_storage_changes_create(self, async_client):
        reasoning_with_create = {
            "storage_changes": {
                "create": [
                    {"title": "New Pipeline Task", "type_hint": "task", "priority": 2}
                ],
                "update": [],
                "delete": [],
            },
            "questions_for_user": [],
            "reasoning_summary": "Creating a new task.",
        }
        patches = _patch_agents(reasoning_result=reasoning_with_create)
        with patches[0], patches[1], patches[2]:
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "create-sess", "message": "Add a new task"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["applied_changes"]["created"]) == 1
        assert data["applied_changes"]["created"][0]["title"] == "New Pipeline Task"

    async def test_chat_with_storage_changes_update(self, async_client):
        # First create a thing via REST
        create_resp = await async_client.post(
            "/api/things", json={"title": "Thing to Update"}
        )
        thing_id = create_resp.json()["id"]

        reasoning_with_update = {
            "storage_changes": {
                "create": [],
                "update": [{"id": thing_id, "changes": {"title": "Updated Title"}}],
                "delete": [],
            },
            "questions_for_user": [],
            "reasoning_summary": "Updating title.",
        }
        patches = _patch_agents(reasoning_result=reasoning_with_update)
        with patches[0], patches[1], patches[2]:
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "update-sess", "message": "Rename that thing"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["applied_changes"]["updated"]) == 1

    async def test_chat_with_storage_changes_delete(self, async_client):
        create_resp = await async_client.post(
            "/api/things", json={"title": "Thing to Delete"}
        )
        thing_id = create_resp.json()["id"]

        reasoning_with_delete = {
            "storage_changes": {
                "create": [],
                "update": [],
                "delete": [thing_id],
            },
            "questions_for_user": [],
            "reasoning_summary": "Deleting the thing.",
        }
        patches = _patch_agents(reasoning_result=reasoning_with_delete)
        with patches[0], patches[1], patches[2]:
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "delete-sess", "message": "Remove that thing"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert thing_id in data["applied_changes"]["deleted"]

    async def test_chat_with_questions_for_user(self, async_client):
        reasoning_with_questions = {
            "storage_changes": {"create": [], "update": [], "delete": []},
            "questions_for_user": ["What priority should this be?"],
            "reasoning_summary": "Ambiguous request, asking for clarification.",
        }
        patches = _patch_agents(reasoning_result=reasoning_with_questions)
        with patches[0], patches[1], patches[2]:
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "q-sess", "message": "Add something"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "What priority should this be?" in data["questions_for_user"]

    async def test_chat_uses_conversation_history(self, async_client):
        # Prime some history
        await async_client.post(
            "/api/chat/history",
            json={"session_id": "history-sess", "role": "user", "content": "Prior message"},
        )
        patches = _patch_agents()
        with patches[0], patches[1], patches[2] as mock_resp:
            # Also spy on reasoning agent to verify history is passed
            with patch(
                "backend.routers.chat.run_reasoning_agent",
                new=AsyncMock(return_value=MOCK_REASONING_RESULT),
            ) as mock_reason:
                await async_client.post(
                    "/api/chat",
                    json={"session_id": "history-sess", "message": "Follow up"},
                )
                # The reasoning agent should have been called with non-empty history
                call_args = mock_reason.call_args
                history_arg = call_args[0][1]  # positional arg index 1
                assert len(history_arg) > 0

    async def test_chat_ignores_unknown_delete_ids(self, async_client):
        """Deleting a non-existent ID should not raise an error."""
        reasoning_with_bad_delete = {
            "storage_changes": {
                "create": [],
                "update": [],
                "delete": ["nonexistent-id-xyz"],
            },
            "questions_for_user": [],
            "reasoning_summary": "Trying to delete unknown.",
        }
        patches = _patch_agents(reasoning_result=reasoning_with_bad_delete)
        with patches[0], patches[1], patches[2]:
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "bad-del-sess", "message": "Delete nothing"},
            )
        assert resp.status_code == 200
        # Unknown ID silently skipped — not in deleted list
        assert "nonexistent-id-xyz" not in resp.json()["applied_changes"]["deleted"]

    async def test_chat_invalid_request_returns_422(self, async_client):
        resp = await async_client.post("/api/chat", json={"session_id": "", "message": ""})
        assert resp.status_code == 422
