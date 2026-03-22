"""Tests for the Reli MCP server."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.mcp_server import (
    create_relationship,
    create_thing,
    delete_relationship,
    delete_thing,
    get_briefing,
    get_conflicts,
    get_thing,
    mcp,
    search_things,
    update_thing,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(data: Any, status_code: int = 200) -> httpx.Response:
    """Build a fake httpx.Response."""
    resp = httpx.Response(
        status_code=status_code,
        json=data if status_code != 204 else None,
        request=httpx.Request("GET", "http://test"),
    )
    return resp


def _mock_204() -> httpx.Response:
    return httpx.Response(status_code=204, request=httpx.Request("DELETE", "http://test"))


# ---------------------------------------------------------------------------
# search_things
# ---------------------------------------------------------------------------


class TestSearchThings:
    @patch("backend.mcp_server._api_get")
    def test_basic_search(self, mock_get: MagicMock) -> None:
        mock_get.return_value = [{"id": "t1", "title": "Buy milk"}]
        result = search_things(query="milk")
        mock_get.assert_called_once_with("/api/things/search", params={"q": "milk", "limit": 20})
        assert len(result) == 1
        assert result[0]["title"] == "Buy milk"

    @patch("backend.mcp_server._api_get")
    def test_search_with_filters(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        search_things(query="test", active_only=True, type_hint="task", limit=5)
        mock_get.assert_called_once_with(
            "/api/things/search",
            params={"q": "test", "limit": 5, "active_only": True, "type_hint": "task"},
        )

    @patch("backend.mcp_server._api_get")
    def test_search_empty_results(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        result = search_things(query="nonexistent")
        assert result == []


# ---------------------------------------------------------------------------
# get_thing
# ---------------------------------------------------------------------------


class TestGetThing:
    @patch("backend.mcp_server._api_get")
    def test_get_existing(self, mock_get: MagicMock) -> None:
        thing = {"id": "abc-123", "title": "My Task", "type_hint": "task", "priority": 2}
        mock_get.return_value = thing
        result = get_thing(thing_id="abc-123")
        mock_get.assert_called_once_with("/api/things/abc-123")
        assert result["id"] == "abc-123"
        assert result["title"] == "My Task"

    @patch("backend.mcp_server._api_get")
    def test_get_not_found(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = httpx.HTTPStatusError(
            "Not Found",
            request=httpx.Request("GET", "http://test"),
            response=httpx.Response(404),
        )
        with pytest.raises(httpx.HTTPStatusError):
            get_thing(thing_id="nonexistent")


# ---------------------------------------------------------------------------
# create_thing
# ---------------------------------------------------------------------------


class TestCreateThing:
    @patch("backend.mcp_server._api_post")
    def test_create_minimal(self, mock_post: MagicMock) -> None:
        mock_post.return_value = {"id": "new-1", "title": "Hello"}
        result = create_thing(title="Hello")
        mock_post.assert_called_once_with(
            "/api/things",
            json_body={"title": "Hello", "priority": 3, "active": True, "surface": True},
        )
        assert result["id"] == "new-1"

    @patch("backend.mcp_server._api_post")
    def test_create_with_all_fields(self, mock_post: MagicMock) -> None:
        mock_post.return_value = {"id": "new-2", "title": "Meeting with Tom"}
        create_thing(
            title="Meeting with Tom",
            type_hint="event",
            data={"location": "Coffee shop"},
            priority=1,
            checkin_date="2026-03-25T09:00:00Z",
            open_questions=["What time?"],
        )
        call_body = mock_post.call_args[1]["json_body"]
        assert call_body["title"] == "Meeting with Tom"
        assert call_body["type_hint"] == "event"
        assert call_body["data"] == {"location": "Coffee shop"}
        assert call_body["priority"] == 1
        assert call_body["checkin_date"] == "2026-03-25T09:00:00Z"
        assert call_body["open_questions"] == ["What time?"]


# ---------------------------------------------------------------------------
# update_thing
# ---------------------------------------------------------------------------


class TestUpdateThing:
    @patch("backend.mcp_server._api_patch")
    def test_update_title(self, mock_patch: MagicMock) -> None:
        mock_patch.return_value = {"id": "t1", "title": "Updated"}
        result = update_thing(thing_id="t1", title="Updated")
        mock_patch.assert_called_once_with("/api/things/t1", json_body={"title": "Updated"})
        assert result["title"] == "Updated"

    @patch("backend.mcp_server._api_patch")
    def test_update_multiple_fields(self, mock_patch: MagicMock) -> None:
        mock_patch.return_value = {"id": "t1", "title": "Task", "priority": 1, "active": False}
        update_thing(thing_id="t1", priority=1, active=False)
        call_body = mock_patch.call_args[1]["json_body"]
        assert call_body == {"priority": 1, "active": False}

    def test_update_no_fields(self) -> None:
        result = update_thing(thing_id="t1")
        assert result == {"error": "No fields provided to update"}


# ---------------------------------------------------------------------------
# delete_thing
# ---------------------------------------------------------------------------


class TestDeleteThing:
    @patch("backend.mcp_server._api_delete")
    def test_delete(self, mock_delete: MagicMock) -> None:
        mock_delete.return_value = {"ok": True}
        result = delete_thing(thing_id="t1")
        mock_delete.assert_called_once_with("/api/things/t1")
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# create_relationship
# ---------------------------------------------------------------------------


class TestCreateRelationship:
    @patch("backend.mcp_server._api_post")
    def test_create_basic(self, mock_post: MagicMock) -> None:
        mock_post.return_value = {
            "id": "rel-1",
            "from_thing_id": "a",
            "to_thing_id": "b",
            "relationship_type": "works_with",
        }
        result = create_relationship(
            from_thing_id="a",
            to_thing_id="b",
            relationship_type="works_with",
        )
        mock_post.assert_called_once_with(
            "/api/things/relationships",
            json_body={
                "from_thing_id": "a",
                "to_thing_id": "b",
                "relationship_type": "works_with",
            },
        )
        assert result["id"] == "rel-1"

    @patch("backend.mcp_server._api_post")
    def test_create_with_metadata(self, mock_post: MagicMock) -> None:
        mock_post.return_value = {"id": "rel-2"}
        create_relationship(
            from_thing_id="a",
            to_thing_id="b",
            relationship_type="depends_on",
            metadata={"priority": "high"},
        )
        call_body = mock_post.call_args[1]["json_body"]
        assert call_body["metadata"] == {"priority": "high"}


# ---------------------------------------------------------------------------
# delete_relationship
# ---------------------------------------------------------------------------


class TestDeleteRelationship:
    @patch("backend.mcp_server._api_delete")
    def test_delete(self, mock_delete: MagicMock) -> None:
        mock_delete.return_value = {"ok": True}
        result = delete_relationship(relationship_id="rel-1")
        mock_delete.assert_called_once_with("/api/things/relationships/rel-1")
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


class TestHttpHelpers:
    @patch("backend.mcp_server._make_client")
    def test_api_get_success(self, mock_client_factory: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response({"id": "1"})
        mock_client_factory.return_value = mock_client

        from backend.mcp_server import _api_get

        result = _api_get("/api/things/1")
        assert result["id"] == "1"

    @patch("backend.mcp_server._make_client")
    def test_api_delete_204(self, mock_client_factory: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.delete.return_value = _mock_204()
        mock_client_factory.return_value = mock_client

        from backend.mcp_server import _api_delete

        result = _api_delete("/api/things/1")
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# MCP server metadata
# ---------------------------------------------------------------------------


class TestMcpMetadata:
    def test_server_name(self) -> None:
        assert mcp.name == "Reli"

    def test_has_all_tools(self) -> None:
        tool_names = {t.name for t in mcp._tool_manager.list_tools()}
        expected = {
            "search_things",
            "get_thing",
            "create_thing",
            "update_thing",
            "delete_thing",
            "create_relationship",
            "delete_relationship",
            "get_briefing",
            "get_conflicts",
        }
        assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"


# ---------------------------------------------------------------------------
# Integration test with real FastAPI test client
# ---------------------------------------------------------------------------


class TestIntegration:
    """Run MCP tool functions against a real Reli API test server."""

    @pytest.fixture()
    def api_server(self, client):  # type: ignore[no-untyped-def]
        """Patch MCP HTTP helpers to use the FastAPI test client."""

        def _get(path: str, params: dict[str, Any] | None = None) -> Any:
            resp = client.get(path, params=params)
            resp.raise_for_status()
            if resp.status_code == 204:
                return {"ok": True}
            return resp.json()

        def _post(path: str, json_body: dict[str, Any] | None = None) -> Any:
            resp = client.post(path, json=json_body)
            resp.raise_for_status()
            if resp.status_code == 204:
                return {"ok": True}
            return resp.json()

        def _patch(path: str, json_body: dict[str, Any] | None = None) -> Any:
            resp = client.patch(path, json=json_body)
            resp.raise_for_status()
            return resp.json()

        def _delete(path: str) -> dict[str, Any]:
            resp = client.delete(path)
            resp.raise_for_status()
            return {"ok": True}

        with (
            patch("backend.mcp_server._api_get", side_effect=_get),
            patch("backend.mcp_server._api_post", side_effect=_post),
            patch("backend.mcp_server._api_patch", side_effect=_patch),
            patch("backend.mcp_server._api_delete", side_effect=_delete),
        ):
            yield

    def test_crud_lifecycle(self, api_server: None) -> None:
        """Create, read, update, search, and delete a Thing end-to-end."""
        # Create
        created = create_thing(title="MCP Test Thing", type_hint="task", priority=2)
        assert created["title"] == "MCP Test Thing"
        thing_id = created["id"]

        # Get
        fetched = get_thing(thing_id=thing_id)
        assert fetched["id"] == thing_id
        assert fetched["type_hint"] == "task"

        # Update
        updated = update_thing(thing_id=thing_id, title="Updated MCP Thing", priority=1)
        assert updated["title"] == "Updated MCP Thing"
        assert updated["priority"] == 1

        # Search
        results = search_things(query="Updated MCP")
        assert any(r["id"] == thing_id for r in results)

        # Delete
        result = delete_thing(thing_id=thing_id)
        assert result["ok"] is True

    def test_relationship_lifecycle(self, api_server: None) -> None:
        """Create two Things, link them, then delete the relationship."""
        t1 = create_thing(title="Thing A", type_hint="person")
        t2 = create_thing(title="Thing B", type_hint="project")

        # Create relationship
        rel = create_relationship(
            from_thing_id=t1["id"],
            to_thing_id=t2["id"],
            relationship_type="works_on",
        )
        assert rel["from_thing_id"] == t1["id"]
        assert rel["to_thing_id"] == t2["id"]
        assert rel["relationship_type"] == "works_on"

        # Delete relationship
        result = delete_relationship(relationship_id=rel["id"])
        assert result["ok"] is True

        # Clean up
        delete_thing(thing_id=t1["id"])
        delete_thing(thing_id=t2["id"])


# ---------------------------------------------------------------------------
# get_briefing
# ---------------------------------------------------------------------------


class TestGetBriefing:
    @patch("backend.mcp_server._api_get")
    def test_default_briefing(self, mock_get: MagicMock) -> None:
        briefing_data = {
            "date": "2026-03-22",
            "things": [{"id": "t1", "title": "Follow up with Tom"}],
            "findings": [{"id": "sf-1", "message": "Stale task", "priority": 2}],
            "total": 2,
        }
        mock_get.return_value = briefing_data
        result = get_briefing()
        mock_get.assert_called_once_with("/api/briefing", params={})
        assert result["total"] == 2
        assert len(result["things"]) == 1
        assert len(result["findings"]) == 1

    @patch("backend.mcp_server._api_get")
    def test_briefing_with_date(self, mock_get: MagicMock) -> None:
        mock_get.return_value = {"date": "2026-03-20", "things": [], "findings": [], "total": 0}
        result = get_briefing(as_of="2026-03-20")
        mock_get.assert_called_once_with("/api/briefing", params={"as_of": "2026-03-20"})
        assert result["date"] == "2026-03-20"
        assert result["total"] == 0

    @patch("backend.mcp_server._api_get")
    def test_briefing_empty(self, mock_get: MagicMock) -> None:
        mock_get.return_value = {"date": "2026-03-22", "things": [], "findings": [], "total": 0}
        result = get_briefing()
        assert result["things"] == []
        assert result["findings"] == []


# ---------------------------------------------------------------------------
# get_conflicts
# ---------------------------------------------------------------------------


class TestGetConflicts:
    @patch("backend.mcp_server._api_get")
    def test_default_window(self, mock_get: MagicMock) -> None:
        conflicts = [
            {
                "alert_type": "blocking_chain",
                "severity": "warning",
                "message": "Task A blocks Task B (due in 3 days)",
                "thing_ids": ["t1", "t2"],
                "thing_titles": ["Task A", "Task B"],
            }
        ]
        mock_get.return_value = conflicts
        result = get_conflicts()
        mock_get.assert_called_once_with("/api/conflicts", params={"window": 14})
        assert len(result) == 1
        assert result[0]["alert_type"] == "blocking_chain"

    @patch("backend.mcp_server._api_get")
    def test_custom_window(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        get_conflicts(window=30)
        mock_get.assert_called_once_with("/api/conflicts", params={"window": 30})

    @patch("backend.mcp_server._api_get")
    def test_window_clamped_min(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        get_conflicts(window=-5)
        mock_get.assert_called_once_with("/api/conflicts", params={"window": 1})

    @patch("backend.mcp_server._api_get")
    def test_window_clamped_max(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        get_conflicts(window=200)
        mock_get.assert_called_once_with("/api/conflicts", params={"window": 90})

    @patch("backend.mcp_server._api_get")
    def test_no_conflicts(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        result = get_conflicts()
        assert result == []

    @patch("backend.mcp_server._api_get")
    def test_multiple_conflict_types(self, mock_get: MagicMock) -> None:
        conflicts = [
            {
                "alert_type": "blocking_chain",
                "severity": "critical",
                "message": "X blocks Y",
                "thing_ids": ["t1", "t2"],
                "thing_titles": ["X", "Y"],
            },
            {
                "alert_type": "schedule_overlap",
                "severity": "warning",
                "message": "A and B overlap",
                "thing_ids": ["t3", "t4"],
                "thing_titles": ["A", "B"],
            },
        ]
        mock_get.return_value = conflicts
        result = get_conflicts(window=7)
        assert len(result) == 2
        assert result[0]["severity"] == "critical"
        assert result[1]["alert_type"] == "schedule_overlap"
