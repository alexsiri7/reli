"""Tests for the /api/think endpoint and reli_think MCP tool."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

from backend.mcp_server import mcp, reli_think

# ---------------------------------------------------------------------------
# Think endpoint tests (via FastAPI test client)
# ---------------------------------------------------------------------------


class TestThinkEndpoint:
    """Test the /api/think REST endpoint."""

    @patch("backend.routers.think.run_think_agent", new_callable=AsyncMock)
    def test_basic_think_request(self, mock_agent: AsyncMock, client: Any) -> None:
        mock_agent.return_value = {
            "instructions": [
                {
                    "action": "create_thing",
                    "params": {"title": "Meeting with Tom", "type_hint": "event"},
                    "ref": "ref_0",
                }
            ],
            "questions_for_user": [],
            "reasoning_summary": "Creating a meeting event for Tom.",
        }
        resp = client.post("/api/think", json={"message": "I'm meeting Tom tomorrow"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["instructions"]) == 1
        assert data["instructions"][0]["action"] == "create_thing"
        assert data["instructions"][0]["params"]["title"] == "Meeting with Tom"
        assert data["reasoning_summary"] == "Creating a meeting event for Tom."

    @patch("backend.routers.think.run_think_agent", new_callable=AsyncMock)
    def test_think_with_context(self, mock_agent: AsyncMock, client: Any) -> None:
        mock_agent.return_value = {
            "instructions": [],
            "questions_for_user": ["When is the meeting?"],
            "reasoning_summary": "Need more info.",
        }
        resp = client.post(
            "/api/think",
            json={"message": "Schedule the meeting", "context": "User is planning a team sync"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["questions_for_user"] == ["When is the meeting?"]
        mock_agent.assert_called_once()
        call_kwargs = mock_agent.call_args
        assert call_kwargs.kwargs["context"] == "User is planning a team sync"

    @patch("backend.routers.think.run_think_agent", new_callable=AsyncMock)
    def test_think_multiple_instructions(self, mock_agent: AsyncMock, client: Any) -> None:
        mock_agent.return_value = {
            "instructions": [
                {
                    "action": "create_thing",
                    "params": {"title": "Tom", "type_hint": "person", "surface": False},
                    "ref": "ref_0",
                },
                {
                    "action": "create_thing",
                    "params": {"title": "Coffee with Tom", "type_hint": "event"},
                    "ref": "ref_1",
                },
                {
                    "action": "create_relationship",
                    "params": {
                        "from_thing_id": "ref_1",
                        "to_thing_id": "ref_0",
                        "relationship_type": "involves",
                    },
                },
            ],
            "questions_for_user": [],
            "reasoning_summary": "Created Tom as a person and linked to event.",
        }
        resp = client.post(
            "/api/think",
            json={"message": "I'm having coffee with Tom next Tuesday"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["instructions"]) == 3
        actions = [i["action"] for i in data["instructions"]]
        assert actions == ["create_thing", "create_thing", "create_relationship"]

    def test_think_empty_message(self, client: Any) -> None:
        resp = client.post("/api/think", json={"message": ""})
        assert resp.status_code == 422  # Validation error

    def test_think_missing_message(self, client: Any) -> None:
        resp = client.post("/api/think", json={})
        assert resp.status_code == 422

    @patch("backend.routers.think.run_think_agent", new_callable=AsyncMock)
    def test_think_with_context_things(self, mock_agent: AsyncMock, client: Any) -> None:
        mock_agent.return_value = {
            "instructions": [
                {
                    "action": "update_thing",
                    "params": {"thing_id": "abc-123", "active": False},
                }
            ],
            "questions_for_user": [],
            "reasoning_summary": "Marking task as done.",
            "context": {
                "things_found": 1,
                "things": [{"id": "abc-123", "title": "Buy milk", "type_hint": "task", "active": 1}],
            },
        }
        resp = client.post("/api/think", json={"message": "I bought the milk"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["context"]["things_found"] == 1
        assert data["instructions"][0]["params"]["thing_id"] == "abc-123"


# ---------------------------------------------------------------------------
# MCP tool tests
# ---------------------------------------------------------------------------


class TestReliThinkMcpTool:
    """Test the reli_think MCP tool wrapper."""

    def test_tool_registered(self) -> None:
        tool_names = {t.name for t in mcp._tool_manager.list_tools()}
        assert "reli_think" in tool_names

    @patch("backend.reasoning_agent.run_think_agent", new_callable=AsyncMock)
    def test_reli_think_basic(self, mock_agent: AsyncMock) -> None:
        mock_agent.return_value = {
            "instructions": [{"action": "create_thing", "params": {"title": "Test"}}],
            "questions_for_user": [],
            "reasoning_summary": "Test plan.",
        }
        result = asyncio.run(reli_think(message="Create a test thing"))
        mock_agent.assert_called_once_with(
            message="Create a test thing",
            context="",
        )
        assert len(result["instructions"]) == 1

    @patch("backend.reasoning_agent.run_think_agent", new_callable=AsyncMock)
    def test_reli_think_with_context(self, mock_agent: AsyncMock) -> None:
        mock_agent.return_value = {
            "instructions": [],
            "questions_for_user": ["What kind of task?"],
            "reasoning_summary": "Need clarification.",
        }
        asyncio.run(reli_think(message="Do the thing", context="User is busy today"))
        mock_agent.assert_called_once_with(
            message="Do the thing",
            context="User is busy today",
        )

    @patch("backend.reasoning_agent.run_think_agent", new_callable=AsyncMock)
    def test_reli_think_no_context(self, mock_agent: AsyncMock) -> None:
        mock_agent.return_value = {"instructions": [], "questions_for_user": [], "reasoning_summary": ""}
        asyncio.run(reli_think(message="Hello"))
        mock_agent.assert_called_once_with(
            message="Hello",
            context="",
        )


# ---------------------------------------------------------------------------
# MCP server metadata
# ---------------------------------------------------------------------------


class TestMcpMetadata:
    def test_server_name(self) -> None:
        assert mcp.name == "Reli"

    def test_has_all_tools(self) -> None:
        tool_names = {t.name for t in mcp._tool_manager.list_tools()}
        expected = {
            "fetch_context",
            "get_thing",
            "create_thing",
            "update_thing",
            "delete_thing",
            "create_relationship",
            "delete_relationship",
            "reli_think",
        }
        assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"
