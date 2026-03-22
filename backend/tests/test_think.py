"""Tests for POST /api/chat/think reasoning-as-a-service endpoint."""

from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_REASONING_RESULT = {
    "applied_changes": {
        "created": [{"id": "t-1", "title": "Dentist appointment", "type_hint": "event"}],
        "updated": [],
        "deleted": [],
        "merged": [],
        "relationships_created": [],
    },
    "fetched_context": {"things": [{"id": "t-user", "title": "User", "type_hint": "person"}], "relationships": []},
    "questions_for_user": ["What time is the appointment?"],
    "priority_question": "What time is the appointment?",
    "reasoning_summary": "Created a dentist appointment Thing.",
    "briefing_mode": False,
}

MOCK_EMPTY_REASONING = {
    "applied_changes": {
        "created": [],
        "updated": [],
        "deleted": [],
        "merged": [],
        "relationships_created": [],
    },
    "fetched_context": {"things": [], "relationships": []},
    "questions_for_user": [],
    "priority_question": "",
    "reasoning_summary": "No changes needed.",
    "briefing_mode": False,
}


def _patch_reasoning(reasoning_result=None):
    """Patch only the reasoning agent (think endpoint skips response agent)."""
    result = reasoning_result or MOCK_REASONING_RESULT
    return patch("backend.pipeline.run_reasoning_agent", new=AsyncMock(return_value=result))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestThinkEndpoint:
    async def test_think_returns_200(self, async_client):
        with _patch_reasoning():
            resp = await async_client.post(
                "/api/chat/think",
                json={"message": "Remember my dentist appointment"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "applied_changes" in data
        assert "questions_for_user" in data
        assert "priority_question" in data
        assert "reasoning_summary" in data
        assert "briefing_mode" in data
        assert "relevant_things" in data

    async def test_think_returns_applied_changes(self, async_client):
        with _patch_reasoning():
            resp = await async_client.post(
                "/api/chat/think",
                json={"message": "Remember my dentist appointment"},
            )
        data = resp.json()
        created = data["applied_changes"]["created"]
        assert len(created) == 1
        assert created[0]["title"] == "Dentist appointment"

    async def test_think_returns_questions(self, async_client):
        with _patch_reasoning():
            resp = await async_client.post(
                "/api/chat/think",
                json={"message": "Remember my dentist appointment"},
            )
        data = resp.json()
        assert data["questions_for_user"] == ["What time is the appointment?"]
        assert data["priority_question"] == "What time is the appointment?"

    async def test_think_returns_relevant_things(self, async_client):
        with _patch_reasoning():
            resp = await async_client.post(
                "/api/chat/think",
                json={"message": "Remember my dentist appointment"},
            )
        data = resp.json()
        assert len(data["relevant_things"]) == 1
        assert data["relevant_things"][0]["id"] == "t-user"

    async def test_think_empty_result(self, async_client):
        with _patch_reasoning(MOCK_EMPTY_REASONING):
            resp = await async_client.post(
                "/api/chat/think",
                json={"message": "Hello"},
            )
        data = resp.json()
        assert data["applied_changes"]["created"] == []
        assert data["questions_for_user"] == []
        assert data["priority_question"] == ""
        assert data["reasoning_summary"] == "No changes needed."

    async def test_think_with_session_id(self, async_client):
        with _patch_reasoning() as mock_agent:
            resp = await async_client.post(
                "/api/chat/think",
                json={"message": "What did I say earlier?", "session_id": "sess-123"},
            )
        assert resp.status_code == 200

    async def test_think_with_planning_mode(self, async_client):
        with _patch_reasoning() as mock_agent:
            resp = await async_client.post(
                "/api/chat/think",
                json={"message": "Plan my vacation", "mode": "planning"},
            )
        assert resp.status_code == 200

    async def test_think_rejects_empty_message(self, async_client):
        resp = await async_client.post(
            "/api/chat/think",
            json={"message": ""},
        )
        assert resp.status_code == 422

    async def test_think_requires_message(self, async_client):
        resp = await async_client.post(
            "/api/chat/think",
            json={},
        )
        assert resp.status_code == 422

    async def test_think_does_not_call_response_agent(self, async_client):
        """Verify the think endpoint only runs reasoning, not the response agent."""
        with (
            _patch_reasoning(),
            patch("backend.pipeline.run_response_agent", new=AsyncMock(return_value="should not be called")) as mock_resp,
        ):
            resp = await async_client.post(
                "/api/chat/think",
                json={"message": "Test message"},
            )
        assert resp.status_code == 200
        mock_resp.assert_not_called()
