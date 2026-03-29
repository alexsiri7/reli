"""Tests for the Reli MCP server."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from backend.mcp_server import (
    chat_history,
    context_agent_prompt,
    create_relationship,
    create_thing,
    delete_relationship,
    delete_thing,
    fetch_context,
    get_briefing,
    get_conflicts,
    get_open_questions,
    get_thing,
    list_relationships,
    mcp,
    merge_things,
    reasoning_agent_prompt,
    response_agent_prompt,
    thing_schema_reference,
    update_thing,
)

# ---------------------------------------------------------------------------
# fetch_context
# ---------------------------------------------------------------------------


class TestFetchContext:
    @patch("backend.mcp_server.shared_tools.fetch_context")
    def test_basic_fetch(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = {"things": [{"id": "t1", "title": "Buy milk"}], "relationships": [], "count": 1}
        result = fetch_context(search_queries=["milk"])
        mock_fetch.assert_called_once_with(
            search_queries_json='["milk"]', fetch_ids_json="[]",
            active_only=True, type_hint="", user_id="",
        )
        assert result["count"] == 1

    @patch("backend.mcp_server.shared_tools.fetch_context")
    def test_fetch_empty(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = {"things": [], "relationships": [], "count": 0}
        result = fetch_context()
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# get_thing
# ---------------------------------------------------------------------------


class TestGetThing:
    @patch("backend.mcp_server.shared_tools.get_thing")
    def test_get_existing(self, mock_get: MagicMock) -> None:
        thing = {
            "id": "abc-123",
            "title": "My Task",
            "type_hint": "task",
            "importance": 1,
        }
        mock_get.return_value = thing
        result = get_thing(thing_id="abc-123")
        mock_get.assert_called_once_with(thing_id="abc-123", user_id="")
        assert result["id"] == "abc-123"
        assert result["title"] == "My Task"

    @patch("backend.mcp_server.shared_tools.get_thing")
    def test_get_not_found(self, mock_get: MagicMock) -> None:
        mock_get.return_value = {"error": "Thing nonexistent not found"}
        result = get_thing(thing_id="nonexistent")
        assert "error" in result


# ---------------------------------------------------------------------------
# create_thing
# ---------------------------------------------------------------------------


class TestCreateThing:
    @patch("backend.mcp_server.shared_tools.create_thing")
    def test_create_minimal(self, mock_create: MagicMock) -> None:
        mock_create.return_value = {"id": "new-1", "title": "Hello"}
        result = create_thing(title="Hello")
        mock_create.assert_called_once_with(
            title="Hello",
            type_hint="",
            importance=2,
            checkin_date="",
            surface=True,
            data_json="{}",
            open_questions_json="[]",
            user_id="",
        )
        assert result["id"] == "new-1"

    @patch("backend.mcp_server.shared_tools.create_thing")
    def test_create_with_all_fields(self, mock_create: MagicMock) -> None:
        mock_create.return_value = {"id": "new-2", "title": "Meeting with Tom"}
        create_thing(
            title="Meeting with Tom",
            type_hint="event",
            data={"location": "Coffee shop"},
            importance=0,
            checkin_date="2026-03-25T09:00:00Z",
            open_questions=["What time?"],
        )
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["title"] == "Meeting with Tom"
        assert call_kwargs["type_hint"] == "event"
        assert json.loads(call_kwargs["data_json"]) == {"location": "Coffee shop"}
        assert call_kwargs["importance"] == 0
        assert call_kwargs["checkin_date"] == "2026-03-25T09:00:00Z"
        assert json.loads(call_kwargs["open_questions_json"]) == ["What time?"]

    @patch("backend.mcp_server.shared_tools.create_thing")
    def test_create_with_parent_id(self, mock_create: MagicMock) -> None:
        mock_create.return_value = {"id": "child-1", "title": "Sub-task", "parent_id": "parent-1"}
        create_thing(title="Sub-task", parent_id="parent-1")
        # parent_id is not passed through to shared_tools (not supported yet)
        mock_create.assert_called_once()

    @patch("backend.mcp_server.shared_tools.create_thing")
    def test_create_defaults(self, mock_create: MagicMock) -> None:
        mock_create.return_value = {"id": "new-3", "title": "Note"}
        create_thing(title="Note")
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["title"] == "Note"
        assert call_kwargs["type_hint"] == ""
        assert call_kwargs["data_json"] == "{}"


# ---------------------------------------------------------------------------
# update_thing
# ---------------------------------------------------------------------------


class TestUpdateThing:
    @patch("backend.mcp_server.shared_tools.update_thing")
    def test_update_title(self, mock_update: MagicMock) -> None:
        mock_update.return_value = {"id": "t1", "title": "Updated"}
        result = update_thing(thing_id="t1", title="Updated")
        mock_update.assert_called_once()
        assert result["title"] == "Updated"

    @patch("backend.mcp_server.shared_tools.update_thing")
    def test_update_multiple_fields(self, mock_update: MagicMock) -> None:
        mock_update.return_value = {
            "id": "t1",
            "title": "Task",
            "importance": 0,
            "active": False,
        }
        update_thing(thing_id="t1", importance=0, active=False)
        mock_update.assert_called_once()

    @patch("backend.mcp_server.shared_tools.update_thing")
    def test_update_all_optional_fields(self, mock_update: MagicMock) -> None:
        mock_update.return_value = {"id": "t2", "title": "Updated"}
        update_thing(
            thing_id="t2",
            title="Updated",
            type_hint="task",
            data={"note": "extra"},
            importance=1,
            parent_id="p-1",
            checkin_date="2026-04-01",
            active=True,
            surface=False,
            open_questions=["When?"],
        )
        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args[1]
        assert call_kwargs["thing_id"] == "t2"
        assert call_kwargs["title"] == "Updated"
        assert call_kwargs["type_hint"] == "task"

    def test_update_no_fields(self) -> None:
        result = update_thing(thing_id="t1")
        assert result == {"error": "No fields provided to update"}


# ---------------------------------------------------------------------------
# delete_thing
# ---------------------------------------------------------------------------


class TestDeleteThing:
    @patch("backend.mcp_server.shared_tools.update_thing")
    def test_soft_delete(self, mock_update: MagicMock) -> None:
        mock_update.return_value = {"id": "t1", "title": "My Task", "active": False}
        result = delete_thing(thing_id="t1")
        mock_update.assert_called_once_with(thing_id="t1", active=False, user_id="")
        assert result["active"] is False
        assert result["id"] == "t1"

    @patch("backend.mcp_server.shared_tools.update_thing")
    def test_soft_delete_returns_thing(self, mock_update: MagicMock) -> None:
        thing = {"id": "abc", "title": "Buy milk", "active": False, "type_hint": "task"}
        mock_update.return_value = thing
        result = delete_thing(thing_id="abc")
        assert result["title"] == "Buy milk"
        assert result["active"] is False


# ---------------------------------------------------------------------------
# merge_things
# ---------------------------------------------------------------------------


class TestMergeThings:
    @patch("backend.mcp_server.shared_tools.merge_things")
    def test_merge_basic(self, mock_merge: MagicMock) -> None:
        mock_merge.return_value = {
            "keep_id": "a",
            "remove_id": "b",
            "keep_title": "Alice Johnson",
            "remove_title": "A. Johnson",
        }
        result = merge_things(keep_id="a", remove_id="b")
        mock_merge.assert_called_once_with(keep_id="a", remove_id="b", user_id="")
        assert result["keep_id"] == "a"
        assert result["remove_id"] == "b"
        assert result["keep_title"] == "Alice Johnson"
        assert result["remove_title"] == "A. Johnson"

    @patch("backend.mcp_server.shared_tools.merge_things")
    def test_merge_returns_titles(self, mock_merge: MagicMock) -> None:
        mock_merge.return_value = {
            "keep_id": "x",
            "remove_id": "y",
            "keep_title": "Project Alpha",
            "remove_title": "proj alpha",
        }
        result = merge_things(keep_id="x", remove_id="y")
        assert result["keep_title"] == "Project Alpha"
        assert result["remove_title"] == "proj alpha"


# ---------------------------------------------------------------------------
# list_relationships
# ---------------------------------------------------------------------------


class TestListRelationships:
    @patch("backend.mcp_server.shared_tools.list_relationships")
    def test_list_returns_relationships(self, mock_list: MagicMock) -> None:
        mock_list.return_value = [
            {"id": "rel-1", "from_thing_id": "a", "to_thing_id": "b", "relationship_type": "works_with"},
            {"id": "rel-2", "from_thing_id": "c", "to_thing_id": "a", "relationship_type": "blocks"},
        ]
        result = list_relationships(thing_id="a")
        mock_list.assert_called_once_with(thing_id="a", user_id="")
        assert len(result) == 2
        assert result[0]["id"] == "rel-1"
        assert result[1]["relationship_type"] == "blocks"

    @patch("backend.mcp_server.shared_tools.list_relationships")
    def test_list_empty(self, mock_list: MagicMock) -> None:
        mock_list.return_value = []
        result = list_relationships(thing_id="no-rels")
        mock_list.assert_called_once_with(thing_id="no-rels", user_id="")
        assert result == []

    @patch("backend.mcp_server.shared_tools.list_relationships")
    def test_list_not_found(self, mock_list: MagicMock) -> None:
        mock_list.return_value = []
        result = list_relationships(thing_id="nonexistent")
        assert result == []


# ---------------------------------------------------------------------------
# create_relationship
# ---------------------------------------------------------------------------


class TestCreateRelationship:
    @patch("backend.mcp_server.shared_tools.create_relationship")
    def test_create_basic(self, mock_create: MagicMock) -> None:
        mock_create.return_value = {
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
        mock_create.assert_called_once_with(
            from_thing_id="a",
            to_thing_id="b",
            relationship_type="works_with",
            user_id="",
        )
        assert result["id"] == "rel-1"

    @patch("backend.mcp_server.shared_tools.create_relationship")
    def test_create_with_metadata(self, mock_create: MagicMock) -> None:
        mock_create.return_value = {"id": "rel-2"}
        create_relationship(
            from_thing_id="a",
            to_thing_id="b",
            relationship_type="depends_on",
            metadata={"priority": "high"},
        )
        # metadata is not passed through to shared_tools.create_relationship
        mock_create.assert_called_once_with(
            from_thing_id="a",
            to_thing_id="b",
            relationship_type="depends_on",
            user_id="",
        )


# ---------------------------------------------------------------------------
# delete_relationship
# ---------------------------------------------------------------------------


class TestDeleteRelationship:
    @patch("backend.mcp_server.shared_tools.delete_relationship")
    def test_delete(self, mock_delete: MagicMock) -> None:
        mock_delete.return_value = {"ok": True}
        result = delete_relationship(relationship_id="rel-1")
        mock_delete.assert_called_once_with(relationship_id="rel-1", user_id="")
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
            "fetch_context",
            "get_thing",
            "create_thing",
            "update_thing",
            "delete_thing",
            "merge_things",
            "list_relationships",
            "create_relationship",
            "delete_relationship",
            "get_briefing",
            "get_open_questions",
            "get_conflicts",
            "chat_history",
        }
        assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"


# ---------------------------------------------------------------------------
# Integration test with shared_tools
# ---------------------------------------------------------------------------


class TestIntegration:
    """Run MCP tool functions against shared_tools with a real DB."""

    @pytest.fixture()
    def api_server(self, patched_db):  # type: ignore[no-untyped-def]
        """No HTTP mocking needed — shared_tools hit the DB directly."""
        yield

    def test_crud_lifecycle(self, api_server: None) -> None:
        """Create, read, update, search, and soft-delete a Thing end-to-end."""
        # Create
        created = create_thing(title="MCP Test Thing", type_hint="task", importance=1)
        assert created["title"] == "MCP Test Thing"
        thing_id = created["id"]

        # Get
        fetched = get_thing(thing_id=thing_id)
        assert fetched["id"] == thing_id

        # Update
        updated = update_thing(thing_id=thing_id, title="Updated MCP Thing", importance=0)
        assert updated["title"] == "Updated MCP Thing"
        assert updated["importance"] == 0

        # Fetch context
        ctx = fetch_context(search_queries=["Updated MCP"])
        assert any(t["id"] == thing_id for t in ctx.get("things", []))

        # Soft-delete — returns deactivated Thing, does NOT hard-delete
        result = delete_thing(thing_id=thing_id)
        assert result["id"] == thing_id
        assert result["active"] in (False, 0)

        # Thing still exists in the DB (soft-deleted)
        fetched_after = get_thing(thing_id=thing_id)
        assert fetched_after["active"] in (False, 0)

    def test_merge_lifecycle(self, api_server: None) -> None:
        """Create two Things, merge them, verify the duplicate is gone."""
        keep = create_thing(title="Alice Johnson MCP", type_hint="person")
        remove = create_thing(title="A. Johnson MCP", type_hint="person")

        result = merge_things(keep_id=keep["id"], remove_id=remove["id"])
        assert result["keep_id"] == keep["id"]
        assert result["remove_id"] == remove["id"]
        assert result["keep_title"] == "Alice Johnson MCP"
        assert result["remove_title"] == "A. Johnson MCP"

        # Kept thing still exists
        kept = get_thing(thing_id=keep["id"])
        assert kept["id"] == keep["id"]

        # Removed thing is gone
        gone = get_thing(thing_id=remove["id"])
        assert "error" in gone

    def test_relationship_lifecycle(self, api_server: None) -> None:
        """Create two Things, link them, list, then delete the relationship."""
        t1 = create_thing(title="Thing A MCP", type_hint="person")
        t2 = create_thing(title="Thing B MCP", type_hint="project")

        # Create relationship
        rel = create_relationship(
            from_thing_id=t1["id"],
            to_thing_id=t2["id"],
            relationship_type="works_on",
        )
        assert rel["from_thing_id"] == t1["id"]
        assert rel["to_thing_id"] == t2["id"]
        assert rel["relationship_type"] == "works_on"

        # List relationships
        rels = list_relationships(thing_id=t1["id"])
        assert len(rels) == 1
        assert rels[0]["id"] == rel["id"]
        assert rels[0]["relationship_type"] == "works_on"

        # Delete relationship
        result = delete_relationship(relationship_id=rel["id"])
        assert result["ok"] is True

        # Verify deleted
        rels_after = list_relationships(thing_id=t1["id"])
        assert len(rels_after) == 0

        # Clean up (soft-delete)
        delete_thing(thing_id=t1["id"])
        delete_thing(thing_id=t2["id"])


# ---------------------------------------------------------------------------
# get_briefing
# ---------------------------------------------------------------------------


class TestGetBriefing:
    @patch("backend.mcp_server.shared_tools.get_briefing")
    def test_default_briefing(self, mock_get: MagicMock) -> None:
        briefing_data = {
            "date": "2026-03-22",
            "checkin_items": [{"id": "t1", "title": "Follow up with Tom"}],
            "findings": [{"id": "sf-1", "message": "Stale task", "priority": 2}],
            "total": 2,
        }
        mock_get.return_value = briefing_data
        result = get_briefing()
        mock_get.assert_called_once_with(as_of=None, user_id="")
        assert result["total"] == 2
        assert len(result["checkin_items"]) == 1
        assert len(result["findings"]) == 1

    @patch("backend.mcp_server.shared_tools.get_briefing")
    def test_briefing_with_date(self, mock_get: MagicMock) -> None:
        mock_get.return_value = {"date": "2026-03-20", "checkin_items": [], "findings": [], "total": 0}
        result = get_briefing(as_of="2026-03-20")
        mock_get.assert_called_once_with(as_of="2026-03-20", user_id="")
        assert result["date"] == "2026-03-20"
        assert result["total"] == 0

    @patch("backend.mcp_server.shared_tools.get_briefing")
    def test_briefing_empty(self, mock_get: MagicMock) -> None:
        mock_get.return_value = {"date": "2026-03-22", "checkin_items": [], "findings": [], "total": 0}
        result = get_briefing()
        assert result["checkin_items"] == []
        assert result["findings"] == []


# ---------------------------------------------------------------------------
# get_open_questions
# ---------------------------------------------------------------------------


class TestGetOpenQuestions:
    @patch("backend.mcp_server.shared_tools.get_open_questions")
    def test_returns_things_with_open_questions(self, mock_get: MagicMock) -> None:
        things = [
            {"id": "t1", "title": "Plan vacation", "open_questions": ["What destination?", "When?"]},
            {"id": "t2", "title": "Fix bug", "open_questions": ["Which release?"]},
        ]
        mock_get.return_value = things
        result = get_open_questions()
        mock_get.assert_called_once_with(limit=50, user_id="")
        assert len(result) == 2
        assert result[0]["id"] == "t1"

    @patch("backend.mcp_server.shared_tools.get_open_questions")
    def test_empty_when_no_open_questions(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        result = get_open_questions()
        assert result == []

    @patch("backend.mcp_server.shared_tools.get_open_questions")
    def test_custom_limit(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        get_open_questions(limit=10)
        mock_get.assert_called_once_with(limit=10, user_id="")

    @patch("backend.mcp_server.shared_tools.get_open_questions")
    def test_limit_clamped_min(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        get_open_questions(limit=0)
        mock_get.assert_called_once_with(limit=1, user_id="")

    @patch("backend.mcp_server.shared_tools.get_open_questions")
    def test_limit_clamped_max(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        get_open_questions(limit=999)
        mock_get.assert_called_once_with(limit=200, user_id="")


# ---------------------------------------------------------------------------
# get_conflicts
# ---------------------------------------------------------------------------


class TestGetConflicts:
    @patch("backend.mcp_server.shared_tools.get_conflicts")
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
        mock_get.assert_called_once_with(window=14, user_id="")
        assert len(result) == 1
        assert result[0]["alert_type"] == "blocking_chain"

    @patch("backend.mcp_server.shared_tools.get_conflicts")
    def test_custom_window(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        get_conflicts(window=30)
        mock_get.assert_called_once_with(window=30, user_id="")

    @patch("backend.mcp_server.shared_tools.get_conflicts")
    def test_window_clamped_min(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        get_conflicts(window=-5)
        mock_get.assert_called_once_with(window=1, user_id="")

    @patch("backend.mcp_server.shared_tools.get_conflicts")
    def test_window_clamped_max(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        get_conflicts(window=200)
        mock_get.assert_called_once_with(window=90, user_id="")

    @patch("backend.mcp_server.shared_tools.get_conflicts")
    def test_no_conflicts(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        result = get_conflicts()
        assert result == []

    @patch("backend.mcp_server.shared_tools.get_conflicts")
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
    """Tests for MCP prompt resources — real agent system prompts."""

    def test_context_agent_prompt_returns_string(self) -> None:
        result = context_agent_prompt()
        assert isinstance(result, str)
        assert "Librarian" in result

    def test_context_agent_prompt_covers_schema(self) -> None:
        result = context_agent_prompt()
        assert "search_queries" in result
        assert "fetch_ids" in result
        assert "needs_web_search" in result
        assert "include_calendar" in result

    def test_context_agent_prompt_covers_type_hints(self) -> None:
        result = context_agent_prompt()
        for hint in ("task", "note", "project", "person", "place", "event"):
            assert hint in result, f"Missing type_hint '{hint}'"

    def test_reasoning_agent_prompt_returns_string(self) -> None:
        result = reasoning_agent_prompt()
        assert isinstance(result, str)
        assert "Reasoning Agent" in result

    def test_reasoning_agent_prompt_covers_output_schema(self) -> None:
        result = reasoning_agent_prompt()
        assert "storage_changes" in result
        assert "create" in result
        assert "update" in result
        assert "delete" in result
        assert "merge" in result
        assert "relationships" in result

    def test_reasoning_agent_prompt_covers_entity_types(self) -> None:
        result = reasoning_agent_prompt()
        for hint in ("task", "note", "project", "person", "place", "event", "preference"):
            assert hint in result, f"Missing entity type '{hint}'"

    def test_reasoning_agent_prompt_covers_open_questions(self) -> None:
        result = reasoning_agent_prompt()
        assert "open_questions" in result

    def test_reasoning_agent_prompt_covers_possessive_patterns(self) -> None:
        result = reasoning_agent_prompt()
        assert "Possessive" in result
        assert "sister" in result

    def test_reasoning_agent_prompt_covers_relationships(self) -> None:
        result = reasoning_agent_prompt()
        for rtype in ("parent-of", "child-of", "depends-on", "blocks", "related-to", "involves"):
            assert rtype in result, f"Missing relationship type '{rtype}'"

    def test_response_agent_prompt_returns_string(self) -> None:
        result = response_agent_prompt()
        assert isinstance(result, str)
        assert "Voice of Reli" in result

    def test_response_agent_prompt_covers_personality(self) -> None:
        result = response_agent_prompt()
        assert "personality" in result.lower() or "Personality" in result

    def test_response_agent_prompt_covers_referenced_things(self) -> None:
        result = response_agent_prompt()
        assert "referenced_things" in result

    def test_response_agent_prompt_covers_briefing_mode(self) -> None:
        result = response_agent_prompt()
        assert "briefing_mode" in result or "Briefing mode" in result

    def test_thing_schema_reference_returns_string(self) -> None:
        result = thing_schema_reference()
        assert isinstance(result, str)
        assert "Thing Schema Reference" in result

    def test_thing_schema_reference_covers_all_fields(self) -> None:
        result = thing_schema_reference()
        for field in (
            "title",
            "type_hint",
            "parent_id",
            "checkin_date",
            "importance",
            "active",
            "surface",
            "data",
            "open_questions",
        ):
            assert field in result, f"Missing field '{field}'"

    def test_thing_schema_reference_covers_type_hints(self) -> None:
        result = thing_schema_reference()
        for hint in (
            "task",
            "note",
            "idea",
            "project",
            "goal",
            "person",
            "place",
            "event",
            "preference",
        ):
            assert hint in result, f"Missing type_hint '{hint}'"

    def test_thing_schema_reference_covers_confidence_levels(self) -> None:
        result = thing_schema_reference()
        assert "emerging" in result
        assert "moderate" in result
        assert "strong" in result
        assert "confidence" in result

    def test_thing_schema_reference_covers_relationship_types(self) -> None:
        result = thing_schema_reference()
        for rtype in ("parent-of", "child-of", "depends-on", "blocks", "related-to"):
            assert rtype in result, f"Missing relationship type '{rtype}'"

    def test_thing_schema_reference_covers_open_questions(self) -> None:
        result = thing_schema_reference()
        assert "open_questions" in result
        assert "knowledge gap" in result.lower() or "unresolved" in result.lower()

    def test_prompts_registered_on_mcp_server(self) -> None:
        """Verify all prompts are registered on the FastMCP server instance."""
        import asyncio

        prompts = asyncio.run(mcp.list_prompts())
        names = {p.name for p in prompts}
        assert "context-agent" in names
        assert "reasoning-agent" in names
        assert "response-agent" in names
        assert "thing-schema" in names

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
# MCP server tool tests (via REST API — testing the REST endpoints directly)
# ---------------------------------------------------------------------------


class TestMCPTools:
    """Test MCP tool functions via the REST API (simulating MCP tool flows)."""

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
            json={"title": "Buy groceries", "type_hint": "task", "importance": 1},
            headers=headers,
        )
        assert resp.status_code == 201
        thing = resp.json()
        thing_id = thing["id"]
        assert thing["title"] == "Buy groceries"
        assert thing["importance"] == 1

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

    def test_open_questions_endpoint(self, token_client_with_user):
        """Things with open_questions appear in the /api/things/open-questions endpoint."""
        headers = {"Authorization": "Bearer test-mcp-token"}

        # Create a thing WITH open questions
        resp = token_client_with_user.post(
            "/api/things",
            json={"title": "Plan birthday party", "type_hint": "task", "open_questions": ["Who to invite?", "Venue?"]},
            headers=headers,
        )
        assert resp.status_code == 201
        thing_id = resp.json()["id"]

        # Create a thing WITHOUT open questions
        token_client_with_user.post(
            "/api/things",
            json={"title": "Buy milk", "type_hint": "task"},
            headers=headers,
        )

        # Only the thing with open questions should appear
        resp = token_client_with_user.get("/api/things/open-questions", headers=headers)
        assert resp.status_code == 200
        results = resp.json()
        ids = [t["id"] for t in results]
        assert thing_id in ids
        thing = next(t for t in results if t["id"] == thing_id)
        assert thing["open_questions"] == ["Who to invite?", "Venue?"]


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


class TestSessionManagerRestart:
    """Regression test: session manager must restart after a previous run completes.

    Re: GH#312, #313 — "Task group is not initialized. Make sure to use run()."
    The bug: _has_started stays True after run() exits, so the lifespan skips
    run() on the next startup, leaving _task_group = None.
    """

    def test_session_manager_restarts_after_previous_run(self, patched_db) -> None:
        """Verify that a second TestClient (= second lifespan) still serves MCP."""
        from backend.main import app
        from backend.mcp_server import mcp

        # First app lifecycle: start and stop
        with TestClient(app):
            pass  # lifespan runs and exits; _has_started = True, _task_group = None

        sm = mcp._session_manager
        assert sm is not None
        assert sm._has_started, "session manager should have been started"
        assert sm._task_group is None, "task group should be None after shutdown"

        # Second app lifecycle: the lifespan must reset and restart the session manager
        with TestClient(app) as client:
            # If the fix is absent, any MCP request would raise
            # "Task group is not initialized" and the app would return 500.
            resp = client.get("/mcp/", headers={"Authorization": "Bearer "})
            # The session manager is running — it handles the request (400/422/200 are all ok;
            # 500 means the task group was not restarted).
            assert resp.status_code != 500, (
                f"MCP returned 500 — session manager task group was not restarted. "
                f"Response: {resp.text}"
            )
