"""Tests for POST /chat/stream SSE endpoint."""

from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MOCK_REASONING_RESULT = {
    "applied_changes": {
        "created": [], "updated": [], "deleted": [],
        "merged": [], "relationships_created": [],
    },
    "fetched_context": {"things": [], "relationships": []},
    "questions_for_user": [],
    "priority_question": "",
    "reasoning_summary": "No changes needed.",
    "briefing_mode": False,
}


async def _mock_response_stream(*args, **kwargs):
    """Yield tokens one at a time like run_response_agent_stream."""
    for token in ["Hello", ", ", "world", "!"]:
        yield token


def _patch_agents(reasoning_result=None):
    """Return context managers patching all agent functions for the stream endpoint."""
    rea = reasoning_result or MOCK_REASONING_RESULT

    return [
        patch("backend.pipeline.run_reasoning_agent", new=AsyncMock(return_value=rea)),
        patch("backend.pipeline.run_response_agent_stream", return_value=_mock_response_stream()),
    ]


def _parse_sse(text: str) -> list[dict]:
    """Parse SSE text into a list of {event, data} dicts."""
    import json
    events = []
    current_event = None
    for line in text.split("\n"):
        if line.startswith("event: "):
            current_event = line[len("event: "):]
        elif line.startswith("data: ") and current_event is not None:
            events.append({"event": current_event, "data": json.loads(line[len("data: "):])})
            current_event = None
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestChatStream:
    async def test_stream_returns_200_with_sse_content_type(self, async_client):
        patches = _patch_agents()
        with patches[0], patches[1]:
            resp = await async_client.post(
                "/api/chat/stream",
                json={"session_id": "s1", "message": "Hello"},
            )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

    async def test_stream_emits_stage_events(self, async_client):
        patches = _patch_agents()
        with patches[0], patches[1]:
            resp = await async_client.post(
                "/api/chat/stream",
                json={"session_id": "stage-sess", "message": "Hello"},
            )
        events = _parse_sse(resp.text)
        stage_events = [e for e in events if e["event"] == "stage"]

        # Should have reasoning started/complete, response started/complete
        stages = [(e["data"]["stage"], e["data"]["status"]) for e in stage_events]
        assert ("reasoning", "started") in stages
        assert ("reasoning", "complete") in stages
        assert ("response", "started") in stages
        assert ("response", "complete") in stages

    async def test_stream_emits_token_events(self, async_client):
        patches = _patch_agents()
        with patches[0], patches[1]:
            resp = await async_client.post(
                "/api/chat/stream",
                json={"session_id": "token-sess", "message": "Hello"},
            )
        events = _parse_sse(resp.text)
        token_events = [e for e in events if e["event"] == "token"]

        # Should have token events matching our mock stream
        tokens = [e["data"]["text"] for e in token_events]
        assert tokens == ["Hello", ", ", "world", "!"]

    async def test_stream_emits_complete_event_with_full_response(self, async_client):
        patches = _patch_agents()
        with patches[0], patches[1]:
            resp = await async_client.post(
                "/api/chat/stream",
                json={"session_id": "complete-sess", "message": "Hello"},
            )
        events = _parse_sse(resp.text)
        complete_events = [e for e in events if e["event"] == "complete"]

        assert len(complete_events) == 1
        data = complete_events[0]["data"]
        assert data["session_id"] == "complete-sess"
        assert data["reply"] == "Hello, world!"
        assert "applied_changes" in data
        assert "questions_for_user" in data

    async def test_stream_persists_messages_to_history(self, async_client):
        patches = _patch_agents()
        with patches[0], patches[1]:
            await async_client.post(
                "/api/chat/stream",
                json={"session_id": "persist-stream", "message": "Remember this"},
            )
        resp = await async_client.get("/api/chat/history/persist-stream")
        msgs = resp.json()
        roles = [m["role"] for m in msgs]
        assert "user" in roles
        assert "assistant" in roles
        # The assistant reply should be the reassembled tokens
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        assert assistant_msgs[0]["content"] == "Hello, world!"

    async def test_stream_event_ordering(self, async_client):
        """Events should follow: reasoning stages, response stages with tokens, complete."""
        patches = _patch_agents()
        with patches[0], patches[1]:
            resp = await async_client.post(
                "/api/chat/stream",
                json={"session_id": "order-sess", "message": "Hello"},
            )
        events = _parse_sse(resp.text)
        event_types = [e["event"] for e in events]

        # The first event should be a stage start for reasoning
        assert event_types[0] == "stage"
        assert events[0]["data"]["stage"] == "reasoning"

        # The last event should be complete
        assert event_types[-1] == "complete"

        # Tokens should appear between response started and response complete
        response_start_idx = next(
            i for i, e in enumerate(events)
            if e["event"] == "stage" and e["data"].get("stage") == "response"
            and e["data"].get("status") == "started"
        )
        response_complete_idx = next(
            i for i, e in enumerate(events)
            if e["event"] == "stage" and e["data"].get("stage") == "response"
            and e["data"].get("status") == "complete"
        )
        token_indices = [i for i, e in enumerate(events) if e["event"] == "token"]
        assert all(response_start_idx < idx < response_complete_idx for idx in token_indices)

    async def test_stream_error_emits_error_event(self, async_client):
        """When an agent raises an exception, the stream emits an error event."""
        error_reasoning = patch(
            "backend.pipeline.run_reasoning_agent",
            new=AsyncMock(side_effect=RuntimeError("LLM API failed")),
        )
        patches = _patch_agents()
        with error_reasoning, patches[1]:
            resp = await async_client.post(
                "/api/chat/stream",
                json={"session_id": "err-sess", "message": "Hello"},
            )
        events = _parse_sse(resp.text)
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) == 1
        assert "LLM API failed" in error_events[0]["data"]["message"]

    async def test_stream_invalid_request_returns_422(self, async_client):
        resp = await async_client.post(
            "/api/chat/stream",
            json={"session_id": "", "message": ""},
        )
        assert resp.status_code == 422
