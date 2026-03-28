"""Tests for the Reli MCP server."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from backend.mcp_server import (
    create_relationship,
    create_thing,
    delete_relationship,
    delete_thing,
    get_briefing,
    get_conflicts,
    get_mutations,
    get_thing,
    mcp,
    merge_things,
    pa_behavior_guide,
    proactive_surfacing_guide,
    relationship_patterns_guide,
    search_things,
    thing_creation_guide,
    update_thing,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(data: Any, status_code: int = 200) -> httpx.Response:
    """Build a fake httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        json=data if status_code != 204 else None,
        request=httpx.Request("GET", "http://test"),
    )


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
            params={
                "q": "test",
                "limit": 5,
                "active_only": True,
                "type_hint": "task",
            },
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
        thing = {
            "id": "abc-123",
            "title": "My Task",
            "type_hint": "task",
            "priority": 2,
        }
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
    @patch("backend.mcp_server._log_mutation")
    @patch("backend.mcp_server._api_post")
    def test_create_minimal(self, mock_post: MagicMock, mock_log: MagicMock) -> None:
        mock_post.return_value = {"id": "new-1", "title": "Hello"}
        result = create_thing(title="Hello")
        mock_post.assert_called_once_with(
            "/api/things",
            json_body={
                "title": "Hello",
                "priority": 3,
                "active": True,
                "surface": True,
            },
        )
        assert result["id"] == "new-1"
        mock_log.assert_called_once_with(
            "create_thing", thing_id="new-1", after_snapshot={"id": "new-1", "title": "Hello"}
        )

    @patch("backend.mcp_server._log_mutation")
    @patch("backend.mcp_server._api_post")
    def test_create_with_all_fields(self, mock_post: MagicMock, mock_log: MagicMock) -> None:
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
    @patch("backend.mcp_server._log_mutation")
    @patch("backend.mcp_server._api_get")
    @patch("backend.mcp_server._api_patch")
    def test_update_title(self, mock_patch: MagicMock, mock_get: MagicMock, mock_log: MagicMock) -> None:
        mock_get.return_value = {"id": "t1", "title": "Old"}
        mock_patch.return_value = {"id": "t1", "title": "Updated"}
        result = update_thing(thing_id="t1", title="Updated")
        mock_patch.assert_called_once_with("/api/things/t1", json_body={"title": "Updated"})
        assert result["title"] == "Updated"

    @patch("backend.mcp_server._log_mutation")
    @patch("backend.mcp_server._api_get")
    @patch("backend.mcp_server._api_patch")
    def test_update_multiple_fields(self, mock_patch: MagicMock, mock_get: MagicMock, mock_log: MagicMock) -> None:
        mock_get.return_value = {"id": "t1", "title": "Task", "priority": 3, "active": True}
        mock_patch.return_value = {
            "id": "t1",
            "title": "Task",
            "priority": 1,
            "active": False,
        }
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
    @patch("backend.mcp_server._log_mutation")
    @patch("backend.mcp_server._api_get")
    @patch("backend.mcp_server._api_patch")
    def test_soft_delete(self, mock_patch: MagicMock, mock_get: MagicMock, mock_log: MagicMock) -> None:
        mock_get.return_value = {"id": "t1", "title": "My Task", "active": True}
        mock_patch.return_value = {"id": "t1", "title": "My Task", "active": False}
        result = delete_thing(thing_id="t1")
        mock_patch.assert_called_once_with("/api/things/t1", json_body={"active": False})
        assert result["active"] is False
        assert result["id"] == "t1"

    @patch("backend.mcp_server._log_mutation")
    @patch("backend.mcp_server._api_get")
    @patch("backend.mcp_server._api_patch")
    def test_soft_delete_returns_thing(self, mock_patch: MagicMock, mock_get: MagicMock, mock_log: MagicMock) -> None:
        thing = {"id": "abc", "title": "Buy milk", "active": False, "type_hint": "task"}
        mock_get.return_value = {"id": "abc", "title": "Buy milk", "active": True, "type_hint": "task"}
        mock_patch.return_value = thing
        result = delete_thing(thing_id="abc")
        assert result["title"] == "Buy milk"
        assert result["active"] is False


# ---------------------------------------------------------------------------
# merge_things
# ---------------------------------------------------------------------------


class TestMergeThings:
    @patch("backend.mcp_server._log_mutation")
    @patch("backend.mcp_server._api_get")
    @patch("backend.mcp_server._api_post")
    def test_merge_basic(self, mock_post: MagicMock, mock_get: MagicMock, mock_log: MagicMock) -> None:
        mock_get.side_effect = [
            {"id": "a", "title": "Alice Johnson"},
            {"id": "b", "title": "A. Johnson"},
        ]
        mock_post.return_value = {
            "keep_id": "a",
            "remove_id": "b",
            "keep_title": "Alice Johnson",
            "remove_title": "A. Johnson",
        }
        result = merge_things(keep_id="a", remove_id="b")
        mock_post.assert_called_once_with(
            "/api/things/merge",
            json_body={"keep_id": "a", "remove_id": "b"},
        )
        assert result["keep_id"] == "a"
        assert result["remove_id"] == "b"
        assert result["keep_title"] == "Alice Johnson"
        assert result["remove_title"] == "A. Johnson"

    @patch("backend.mcp_server._log_mutation")
    @patch("backend.mcp_server._api_get")
    @patch("backend.mcp_server._api_post")
    def test_merge_returns_titles(self, mock_post: MagicMock, mock_get: MagicMock, mock_log: MagicMock) -> None:
        mock_get.side_effect = [
            {"id": "x", "title": "Project Alpha"},
            {"id": "y", "title": "proj alpha"},
        ]
        mock_post.return_value = {
            "keep_id": "x",
            "remove_id": "y",
            "keep_title": "Project Alpha",
            "remove_title": "proj alpha",
        }
        result = merge_things(keep_id="x", remove_id="y")
        assert result["keep_title"] == "Project Alpha"
        assert result["remove_title"] == "proj alpha"


# ---------------------------------------------------------------------------
# create_relationship
# ---------------------------------------------------------------------------


class TestCreateRelationship:
    @patch("backend.mcp_server._log_mutation")
    @patch("backend.mcp_server._api_post")
    def test_create_basic(self, mock_post: MagicMock, mock_log: MagicMock) -> None:
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

    @patch("backend.mcp_server._log_mutation")
    @patch("backend.mcp_server._api_post")
    def test_create_with_metadata(self, mock_post: MagicMock, mock_log: MagicMock) -> None:
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
    @patch("backend.mcp_server._log_mutation")
    @patch("backend.mcp_server._api_delete")
    def test_delete(self, mock_delete: MagicMock, mock_log: MagicMock) -> None:
        mock_delete.return_value = {"ok": True}
        result = delete_relationship(relationship_id="rel-1")
        mock_delete.assert_called_once_with("/api/things/relationships/rel-1")
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# get_mutations
# ---------------------------------------------------------------------------


class TestGetMutations:
    @patch("backend.mcp_server._api_get")
    def test_basic(self, mock_get: MagicMock) -> None:
        mock_get.return_value = [
            {
                "id": "m1",
                "operation": "create_thing",
                "thing_id": "t1",
                "before_snapshot": None,
                "after_snapshot": {"id": "t1", "title": "Hello"},
            }
        ]
        result = get_mutations()
        mock_get.assert_called_once_with("/api/things/mutations", params={"limit": 50})
        assert len(result) == 1
        assert result[0]["operation"] == "create_thing"

    @patch("backend.mcp_server._api_get")
    def test_with_filters(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        get_mutations(thing_id="t1", limit=10, since="2026-01-01T00:00:00Z")
        mock_get.assert_called_once_with(
            "/api/things/mutations",
            params={"limit": 10, "thing_id": "t1", "since": "2026-01-01T00:00:00Z"},
        )

    @patch("backend.mcp_server._api_get")
    def test_limit_clamped(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        get_mutations(limit=9999)
        params = mock_get.call_args[1]["params"]
        assert params["limit"] == 500


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
            "merge_things",
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

        def _delete(path: str) -> Any:
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
        """Create, read, update, search, and soft-delete a Thing end-to-end."""
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

        # Soft-delete — returns deactivated Thing, does NOT hard-delete
        result = delete_thing(thing_id=thing_id)
        assert result["id"] == thing_id
        assert result["active"] is False

        # Thing still exists in the DB (soft-deleted)
        fetched_after = get_thing(thing_id=thing_id)
        assert fetched_after["active"] is False

    def test_merge_lifecycle(self, api_server: None) -> None:
        """Create two Things, merge them, verify the duplicate is gone."""
        keep = create_thing(title="Alice Johnson", type_hint="person")
        remove = create_thing(title="A. Johnson", type_hint="person")

        result = merge_things(keep_id=keep["id"], remove_id=remove["id"])
        assert result["keep_id"] == keep["id"]
        assert result["remove_id"] == remove["id"]
        assert result["keep_title"] == "Alice Johnson"
        assert result["remove_title"] == "A. Johnson"

        # Kept thing still exists
        kept = get_thing(thing_id=keep["id"])
        assert kept["id"] == keep["id"]

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

        # Clean up (soft-delete)
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


# MCP Prompt Resources (Phase 2)
# ---------------------------------------------------------------------------


class TestPromptResources:
    """Tests for PA behavior prompt resources."""

    def test_thing_creation_guide_returns_string(self) -> None:
        result = thing_creation_guide()
        assert isinstance(result, str)
        assert "Thing Creation Guide" in result

    def test_thing_creation_guide_covers_type_hints(self) -> None:
        result = thing_creation_guide()
        for hint in (
            "task",
            "note",
            "idea",
            "project",
            "goal",
            "person",
            "place",
            "event",
        ):
            assert hint in result, f"Missing type_hint '{hint}'"

    def test_thing_creation_guide_covers_open_questions(self) -> None:
        result = thing_creation_guide()
        assert "open_questions" in result

    def test_thing_creation_guide_covers_surface_defaults(self) -> None:
        result = thing_creation_guide()
        assert "surface" in result
        assert "false" in result

    def test_relationship_patterns_returns_string(self) -> None:
        result = relationship_patterns_guide()
        assert isinstance(result, str)
        assert "Relationship Patterns" in result

    def test_relationship_patterns_covers_types(self) -> None:
        result = relationship_patterns_guide()
        for rtype in (
            "parent-of",
            "child-of",
            "depends-on",
            "blocks",
            "related-to",
            "involves",
        ):
            assert rtype in result, f"Missing relationship type '{rtype}'"

    def test_relationship_patterns_covers_possessive(self) -> None:
        result = relationship_patterns_guide()
        assert "Possessive" in result
        assert "sister" in result

    def test_proactive_surfacing_returns_string(self) -> None:
        result = proactive_surfacing_guide()
        assert isinstance(result, str)
        assert "Proactive Surfacing" in result

    def test_proactive_surfacing_covers_date_types(self) -> None:
        result = proactive_surfacing_guide()
        for key in ("birthday", "deadline", "due_date", "anniversary"):
            assert key in result, f"Missing date key '{key}'"

    def test_proactive_surfacing_covers_briefing_mode(self) -> None:
        result = proactive_surfacing_guide()
        assert "Briefing Mode" in result or "briefing" in result.lower()

    def test_pa_behavior_returns_string(self) -> None:
        result = pa_behavior_guide()
        assert isinstance(result, str)
        assert "PA Behavior Guide" in result

    def test_pa_behavior_covers_core_principles(self) -> None:
        result = pa_behavior_guide()
        assert "Things as State" in result
        assert "Search Before Creating" in result
        assert "One Question at a Time" in result

    def test_pa_behavior_covers_data_model(self) -> None:
        result = pa_behavior_guide()
        for field in (
            "title",
            "type_hint",
            "data",
            "priority",
            "active",
            "surface",
            "open_questions",
        ):
            assert field in result, f"Missing data model field '{field}'"

    def test_pa_behavior_covers_personality_overrides(self) -> None:
        result = pa_behavior_guide()
        assert "overridable" in result.lower() or "override" in result.lower()
        assert "preference" in result.lower()

    def test_prompts_registered_on_mcp_server(self) -> None:
        """Verify all prompts are registered on the FastMCP server instance."""
        import asyncio

        prompts = asyncio.run(mcp.list_prompts())
        names = {p.name for p in prompts}
        assert "thing-creation" in names
        assert "relationship-patterns" in names
        assert "proactive-surfacing" in names
        assert "pa-behavior" in names

    def test_prompts_have_descriptions(self) -> None:
        """Each prompt must have a non-empty description."""
        import asyncio

        prompts = asyncio.run(mcp.list_prompts())
        for p in prompts:
            assert p.description, f"Prompt '{p.name}' has no description"


# ---------------------------------------------------------------------------
# Bearer token auth (re-j102)
# ---------------------------------------------------------------------------


@pytest.fixture()
def token_client(patched_db):
    """TestClient with both SECRET_KEY and RELI_API_TOKEN configured."""
    with (
        patch("backend.auth.SECRET_KEY", "test-secret-key"),
        patch("backend.auth._API_TOKEN", "test-mcp-token"),
    ):
        from backend.main import app

        with TestClient(app) as c:
            yield c


@pytest.fixture()
def token_client_with_user(patched_db):
    """TestClient with token auth and a user in the database."""
    from backend.database import db

    # Insert a test user
    with db() as conn:
        conn.execute(
            "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
            ("u-test-123", "test@example.com", "google-test", "Test User"),
        )

    with (
        patch("backend.auth.SECRET_KEY", "test-secret-key"),
        patch("backend.auth._API_TOKEN", "test-mcp-token"),
    ):
        from backend.main import app

        with TestClient(app) as c:
            yield c


class TestBearerTokenAuth:
    def test_valid_bearer_token_accepted(self, token_client_with_user):
        resp = token_client_with_user.get(
            "/api/things",
            headers={"Authorization": "Bearer test-mcp-token"},
        )
        assert resp.status_code == 200

    def test_invalid_bearer_token_rejected(self, token_client):
        resp = token_client.get(
            "/api/things",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401
        assert "Invalid API token" in resp.json()["detail"]

    def test_bearer_token_resolves_user(self, token_client_with_user):
        """Bearer token auth should resolve to the first user in the DB."""
        # Create a thing via bearer auth
        resp = token_client_with_user.post(
            "/api/things",
            json={"title": "MCP test thing"},
            headers={"Authorization": "Bearer test-mcp-token"},
        )
        assert resp.status_code == 201
        thing = resp.json()
        assert thing["title"] == "MCP test thing"

    def test_cookie_auth_still_works_alongside_token(self, token_client_with_user):
        """Cookie-based JWT auth should still work when token auth is configured."""

        payload = {"sub": "u-test-123", "email": "test@example.com", "exp": 9999999999}
        token = jwt.encode(payload, "test-secret-key", algorithm="HS256")
        token_client_with_user.cookies.set("reli_session", token)
        resp = token_client_with_user.get("/api/things")
        assert resp.status_code == 200

    def test_no_auth_header_falls_through_to_cookie(self, token_client):
        """Without Authorization header, should fall through to cookie check."""
        resp = token_client.get("/api/things")
        assert resp.status_code == 401
        assert "Not authenticated" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# MCP server tool tests (via mocked httpx)
# ---------------------------------------------------------------------------


class TestMCPTools:
    """Test MCP tool functions with mocked HTTP calls."""

    def test_search_things(self, token_client_with_user):
        """Create a thing then search for it via REST API (simulating MCP flow)."""
        headers = {"Authorization": "Bearer test-mcp-token"}
        # Create
        token_client_with_user.post(
            "/api/things",
            json={"title": "Alice Johnson", "type_hint": "person"},
            headers=headers,
        )
        # Search
        resp = token_client_with_user.get(
            "/api/things/search",
            params={"q": "Alice", "limit": 10},
            headers=headers,
        )
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        assert any("Alice" in t["title"] for t in results)

    def test_crud_lifecycle(self, token_client_with_user):
        """Test full CRUD lifecycle via REST API (simulating MCP tool calls)."""
        headers = {"Authorization": "Bearer test-mcp-token"}

        # Create
        resp = token_client_with_user.post(
            "/api/things",
            json={"title": "Buy groceries", "type_hint": "task", "priority": 2},
            headers=headers,
        )
        assert resp.status_code == 201
        thing = resp.json()
        thing_id = thing["id"]
        assert thing["title"] == "Buy groceries"
        assert thing["priority"] == 2

        # Get
        resp = token_client_with_user.get(f"/api/things/{thing_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["title"] == "Buy groceries"

        # Update
        resp = token_client_with_user.patch(
            f"/api/things/{thing_id}",
            json={"title": "Buy organic groceries", "active": False},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Buy organic groceries"
        assert resp.json()["active"] is False

        # Delete
        resp = token_client_with_user.delete(f"/api/things/{thing_id}", headers=headers)
        assert resp.status_code == 204

        # Verify deleted
        resp = token_client_with_user.get(f"/api/things/{thing_id}", headers=headers)
        assert resp.status_code == 404

    def test_relationship_lifecycle(self, token_client_with_user):
        """Test create/delete relationship via REST API (simulating MCP tool calls)."""
        headers = {"Authorization": "Bearer test-mcp-token"}

        # Create two things
        resp_a = token_client_with_user.post(
            "/api/things",
            json={"title": "Alice", "type_hint": "person"},
            headers=headers,
        )
        resp_b = token_client_with_user.post(
            "/api/things",
            json={"title": "Acme Corp", "type_hint": "organization"},
            headers=headers,
        )
        id_a = resp_a.json()["id"]
        id_b = resp_b.json()["id"]

        # Create relationship
        resp = token_client_with_user.post(
            "/api/things/relationships",
            json={
                "from_thing_id": id_a,
                "to_thing_id": id_b,
                "relationship_type": "works_at",
            },
            headers=headers,
        )
        assert resp.status_code == 201
        rel = resp.json()
        assert rel["relationship_type"] == "works_at"
        rel_id = rel["id"]

        # Delete relationship
        resp = token_client_with_user.delete(
            f"/api/things/relationships/{rel_id}",
            headers=headers,
        )
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Mutations REST endpoint — integration tests
# ---------------------------------------------------------------------------


class TestMutationsEndpoint:
    """Integration tests for POST/GET /api/things/mutations."""

    def test_log_and_query_mutations(self, token_client_with_user: TestClient) -> None:
        headers = {"Authorization": "Bearer test-mcp-token"}

        # Create a thing to reference
        resp = token_client_with_user.post(
            "/api/things",
            json={"title": "Auditable Thing"},
            headers=headers,
        )
        assert resp.status_code == 201
        thing_id = resp.json()["id"]

        # Log a mutation via POST
        resp = token_client_with_user.post(
            "/api/things/mutations",
            json={
                "operation": "create_thing",
                "thing_id": thing_id,
                "after_snapshot": {"id": thing_id, "title": "Auditable Thing"},
                "client_id": "test-client",
            },
            headers=headers,
        )
        assert resp.status_code == 201
        assert "id" in resp.json()

        # Query mutations via GET (no filter)
        resp = token_client_with_user.get("/api/things/mutations", headers=headers)
        assert resp.status_code == 200
        mutations = resp.json()
        assert len(mutations) >= 1
        ops = [m["operation"] for m in mutations]
        assert "create_thing" in ops

    def test_query_mutations_by_thing_id(self, token_client_with_user: TestClient) -> None:
        headers = {"Authorization": "Bearer test-mcp-token"}

        # Create a thing
        resp = token_client_with_user.post(
            "/api/things", json={"title": "Filtered Thing"}, headers=headers
        )
        thing_id = resp.json()["id"]

        # Log two mutations with different thing_ids
        token_client_with_user.post(
            "/api/things/mutations",
            json={"operation": "update_thing", "thing_id": thing_id},
            headers=headers,
        )
        token_client_with_user.post(
            "/api/things/mutations",
            json={"operation": "delete_thing", "thing_id": "other-id"},
            headers=headers,
        )

        # Filter by thing_id
        resp = token_client_with_user.get(
            f"/api/things/mutations?thing_id={thing_id}", headers=headers
        )
        assert resp.status_code == 200
        mutations = resp.json()
        assert all(m["thing_id"] == thing_id for m in mutations)

    def test_log_mutation_with_before_after_snapshots(self, token_client_with_user: TestClient) -> None:
        headers = {"Authorization": "Bearer test-mcp-token"}
        before = {"id": "t1", "title": "Before", "active": True}
        after = {"id": "t1", "title": "After", "active": False}

        resp = token_client_with_user.post(
            "/api/things/mutations",
            json={
                "operation": "update_thing",
                "thing_id": "t1",
                "before_snapshot": before,
                "after_snapshot": after,
            },
            headers=headers,
        )
        assert resp.status_code == 201

        # Retrieve and verify snapshots
        resp = token_client_with_user.get("/api/things/mutations?thing_id=t1", headers=headers)
        found = [m for m in resp.json() if m.get("thing_id") == "t1"]
        assert len(found) >= 1
        m = found[0]
        assert m["before_snapshot"]["title"] == "Before"
        assert m["after_snapshot"]["active"] is False


# ---------------------------------------------------------------------------
# _TokenAuthMiddleware — unit tests
# ---------------------------------------------------------------------------


class TestTokenAuthMiddleware:
    """Test the ASGI middleware that guards the /mcp endpoint."""

    def _make_client(self, mcp_api_token: str) -> TestClient:
        """Wrap a trivial echo app with _TokenAuthMiddleware."""
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        from backend.mcp_server import _TokenAuthMiddleware

        def echo(request: Request) -> PlainTextResponse:
            return PlainTextResponse("ok")

        inner = Starlette(routes=[Route("/", echo)])
        wrapped = _TokenAuthMiddleware(inner, mcp_api_token)
        return TestClient(wrapped, raise_server_exceptions=True)

    def test_correct_token_allowed(self) -> None:
        client = self._make_client("secret-token")
        resp = client.get("/", headers={"Authorization": "Bearer secret-token"})
        assert resp.status_code == 200
        assert resp.text == "ok"

    def test_wrong_token_rejected(self) -> None:
        client = self._make_client("secret-token")
        resp = client.get("/", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401

    def test_missing_auth_header_rejected(self) -> None:
        client = self._make_client("secret-token")
        resp = client.get("/")
        assert resp.status_code == 401

    def test_empty_token_allows_all(self) -> None:
        """Empty MCP_API_TOKEN = dev mode, no auth required."""
        client = self._make_client("")
        resp = client.get("/")
        assert resp.status_code == 200

    def test_www_authenticate_header_on_401(self) -> None:
        client = self._make_client("secret-token")
        resp = client.get("/", headers={"Authorization": "Bearer bad"})
        assert resp.status_code == 401
        assert "Bearer" in resp.headers.get("www-authenticate", "")
