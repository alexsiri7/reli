"""Tests for the MCP server tool definitions."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def mock_httpx():
    """Mock httpx.Client to avoid real HTTP calls."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}
    mock_client.get.return_value = mock_response
    mock_client.post.return_value = mock_response
    mock_client.patch.return_value = mock_response
    mock_client.delete.return_value = mock_response
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("backend.mcp_server.httpx.Client", return_value=mock_client) as mock_cls:
        yield mock_client, mock_cls


class TestReliThinkTool:
    def test_reli_think_calls_think_endpoint(self, mock_httpx):
        from backend.mcp_server import reli_think

        client, _ = mock_httpx
        client.post.return_value.json.return_value = {
            "applied_changes": {"created": [], "updated": [], "deleted": []},
            "questions_for_user": [],
            "priority_question": "",
            "reasoning_summary": "Done.",
            "briefing_mode": False,
            "relevant_things": [],
        }

        result = reli_think(message="Remember my dentist appointment")

        client.post.assert_called_once()
        call_args = client.post.call_args
        assert call_args[0][0] == "/api/chat/think"
        body = call_args[1]["json"]
        assert body["message"] == "Remember my dentist appointment"

    def test_reli_think_passes_session_id(self, mock_httpx):
        from backend.mcp_server import reli_think

        client, _ = mock_httpx
        client.post.return_value.json.return_value = {}

        reli_think(message="What was that?", session_id="sess-42")

        body = client.post.call_args[1]["json"]
        assert body["session_id"] == "sess-42"

    def test_reli_think_passes_planning_mode(self, mock_httpx):
        from backend.mcp_server import reli_think

        client, _ = mock_httpx
        client.post.return_value.json.return_value = {}

        reli_think(message="Plan my vacation", mode="planning")

        body = client.post.call_args[1]["json"]
        assert body["mode"] == "planning"

    def test_reli_think_omits_defaults(self, mock_httpx):
        from backend.mcp_server import reli_think

        client, _ = mock_httpx
        client.post.return_value.json.return_value = {}

        reli_think(message="Hello")

        body = client.post.call_args[1]["json"]
        assert "session_id" not in body
        assert "mode" not in body


class TestCrudTools:
    def test_search_things(self, mock_httpx):
        from backend.mcp_server import search_things

        client, _ = mock_httpx
        client.get.return_value.json.return_value = [{"id": "t-1", "title": "Test"}]

        result = search_things(query="test")
        assert result == [{"id": "t-1", "title": "Test"}]

    def test_create_thing(self, mock_httpx):
        from backend.mcp_server import create_thing

        client, _ = mock_httpx
        client.post.return_value.json.return_value = {"id": "t-new", "title": "New"}

        result = create_thing(title="New", type_hint="task")
        assert result["id"] == "t-new"

    def test_reli_think_returns_structured_result(self, mock_httpx):
        from backend.mcp_server import reli_think

        client, _ = mock_httpx
        expected = {
            "applied_changes": {
                "created": [{"id": "t-1", "title": "Dentist"}],
                "updated": [],
                "deleted": [],
            },
            "questions_for_user": ["When?"],
            "priority_question": "When?",
            "reasoning_summary": "Created appointment.",
            "briefing_mode": False,
            "relevant_things": [],
        }
        client.post.return_value.json.return_value = expected

        result = reli_think(message="Dentist next week")
        assert result == expected
