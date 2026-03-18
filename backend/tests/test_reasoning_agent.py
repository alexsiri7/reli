"""Tests for the ADK LlmAgent-based reasoning agent with tool calling."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: I001

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_event(text: str, *, partial: bool = False, usage: bool = False):
    """Build a mock ADK Event with text content and optional usage metadata."""
    part = MagicMock()
    part.text = text
    content = MagicMock()
    content.parts = [part]

    event = MagicMock()
    event.content = content
    event.partial = partial
    event.model_version = "google/gemini-2.5-flash"

    if usage:
        um = MagicMock()
        um.prompt_token_count = 20
        um.candidates_token_count = 10
        um.total_token_count = 30
        event.usage_metadata = um
    else:
        event.usage_metadata = None

    return event


async def _mock_run_async_factory(events):
    """Create an async generator that yields mock events."""
    for e in events:
        yield e


# ---------------------------------------------------------------------------
# Tool factory tests
# ---------------------------------------------------------------------------


class TestMakeReasoningTools:
    """Tests for _make_reasoning_tools and individual tool functions."""

    def _get_tools(self, user_id: str = "test-user"):
        """Create tools with all DB operations mocked."""
        with patch("backend.reasoning_agent.db") as mock_db, \
             patch("backend.reasoning_agent.upsert_thing"), \
             patch("backend.reasoning_agent.vs_delete"):
            from backend.reasoning_agent import _make_reasoning_tools
            tools, applied = _make_reasoning_tools(user_id)
            return tools, applied, mock_db

    def test_returns_six_tools(self):
        tools, applied, _ = self._get_tools()
        assert len(tools) == 6
        names = [t.__name__ for t in tools]
        assert "fetch_context" in names
        assert "create_thing" in names
        assert "update_thing" in names
        assert "delete_thing" in names
        assert "merge_things" in names
        assert "create_relationship" in names

    def test_applied_starts_empty(self):
        _, applied, _ = self._get_tools()
        assert applied == {
            "created": [],
            "updated": [],
            "deleted": [],
            "merged": [],
            "relationships_created": [],
            "context_things": [],
            "context_relationships": [],
        }


# ---------------------------------------------------------------------------
# create_thing tool tests
# ---------------------------------------------------------------------------


class TestCreateThingTool:
    def test_create_thing_empty_title_returns_error(self):
        from backend.reasoning_agent import _make_reasoning_tools

        tools, applied = _make_reasoning_tools("test-user")
        create_fn = tools[1]
        result = create_fn(title="   ")
        assert "error" in result
        assert applied["created"] == []

    def test_create_thing_dedup_existing(self):
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        with patch("backend.reasoning_agent.db", return_value=mock_db_ctx), \
             patch("backend.reasoning_agent.upsert_thing"), \
             patch("backend.reasoning_agent.vs_delete"):
            from backend.reasoning_agent import _make_reasoning_tools
            tools, applied = _make_reasoning_tools("test-user")
            create_fn = tools[1]

            # Simulate existing Thing with same title
            existing_row = {
                "id": "existing-uuid",
                "title": "Test Thing",
                "data": '{"notes": "old"}',
                "checkin_date": None,
                "open_questions": None,
            }
            mock_existing = MagicMock()
            mock_existing.__getitem__ = lambda self, key: existing_row[key]
            mock_existing.keys = lambda: existing_row.keys()

            updated_row = {**existing_row, "data": '{"notes": "old", "extra": "new"}'}
            mock_updated = MagicMock()
            mock_updated.__getitem__ = lambda self, key: updated_row[key]
            mock_updated.keys = lambda: updated_row.keys()

            mock_conn.execute.return_value.fetchone = MagicMock(
                side_effect=[mock_existing, mock_updated]
            )

            create_fn(
                title="Test Thing",
                data_json='{"extra": "new"}',
            )

            assert len(applied["updated"]) == 1
            assert applied["created"] == []

    def test_create_thing_new(self):
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        with patch("backend.reasoning_agent.db", return_value=mock_db_ctx), \
             patch("backend.reasoning_agent.upsert_thing") as mock_upsert, \
             patch("backend.reasoning_agent.vs_delete"):
            from backend.reasoning_agent import _make_reasoning_tools
            tools, applied = _make_reasoning_tools("test-user")
            create_fn = tools[1]

            new_row = {
                "id": "new-uuid",
                "title": "Brand New",
                "type_hint": "task",
                "data": "{}",
                "active": 1,
                "surface": 1,
                "open_questions": None,
            }
            mock_new = MagicMock()
            mock_new.__getitem__ = lambda self, key: new_row[key]
            mock_new.keys = lambda: new_row.keys()

            mock_conn.execute.return_value.fetchone = MagicMock(
                side_effect=[None, mock_new]
            )

            create_fn(title="Brand New", type_hint="task")

            assert len(applied["created"]) == 1
            mock_upsert.assert_called_once()

    def test_create_entity_defaults_surface_false(self):
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        with patch("backend.reasoning_agent.db", return_value=mock_db_ctx), \
             patch("backend.reasoning_agent.upsert_thing"), \
             patch("backend.reasoning_agent.vs_delete"):
            from backend.reasoning_agent import _make_reasoning_tools
            tools, applied = _make_reasoning_tools("test-user")
            create_fn = tools[1]

            new_row = {
                "id": "person-uuid",
                "title": "Alice",
                "type_hint": "person",
                "data": "{}",
                "active": 1,
                "surface": 0,
                "open_questions": None,
            }
            mock_new = MagicMock()
            mock_new.__getitem__ = lambda self, key: new_row[key]
            mock_new.keys = lambda: new_row.keys()

            mock_conn.execute.return_value.fetchone = MagicMock(
                side_effect=[None, mock_new]
            )

            create_fn(title="Alice", type_hint="person", surface=True)

            # The INSERT call should have surface=0 for entity types
            insert_call = None
            for call in mock_conn.execute.call_args_list:
                if "INSERT INTO things" in str(call):
                    insert_call = call
                    break
            assert insert_call is not None
            args = insert_call[0][1]
            # surface is at index 6 in the INSERT params
            assert args[6] == 0


# ---------------------------------------------------------------------------
# delete_thing tool tests
# ---------------------------------------------------------------------------


class TestDeleteThingTool:
    def test_delete_not_found(self):
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        with patch("backend.reasoning_agent.db", return_value=mock_db_ctx), \
             patch("backend.reasoning_agent.upsert_thing"), \
             patch("backend.reasoning_agent.vs_delete"):
            from backend.reasoning_agent import _make_reasoning_tools
            tools, applied = _make_reasoning_tools("test-user")
            delete_fn = tools[3]

            mock_conn.execute.return_value.fetchone = MagicMock(return_value=None)
            result = delete_fn(thing_id="nonexistent")
            assert "error" in result
            assert applied["deleted"] == []

    def test_delete_success(self):
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        with patch("backend.reasoning_agent.db", return_value=mock_db_ctx), \
             patch("backend.reasoning_agent.upsert_thing"), \
             patch("backend.reasoning_agent.vs_delete") as mock_vs_delete:
            from backend.reasoning_agent import _make_reasoning_tools
            tools, applied = _make_reasoning_tools("test-user")
            delete_fn = tools[3]

            row = {"id": "del-uuid", "title": "Delete Me"}
            mock_row = MagicMock()
            mock_row.__getitem__ = lambda self, key: row[key]

            mock_conn.execute.return_value.fetchone = MagicMock(return_value=mock_row)

            result = delete_fn(thing_id="del-uuid")
            assert result["deleted"] == "del-uuid"
            assert "del-uuid" in applied["deleted"]
            mock_vs_delete.assert_called_once_with("del-uuid")


# ---------------------------------------------------------------------------
# create_relationship tool tests
# ---------------------------------------------------------------------------


class TestCreateRelationshipTool:
    def test_self_referential_rejected(self):
        from backend.reasoning_agent import _make_reasoning_tools
        tools, applied = _make_reasoning_tools("test-user")
        rel_fn = tools[5]
        result = rel_fn(
            from_thing_id="same-id",
            to_thing_id="same-id",
            relationship_type="related-to",
        )
        assert "error" in result

    def test_missing_thing_returns_error(self):
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        with patch("backend.reasoning_agent.db", return_value=mock_db_ctx), \
             patch("backend.reasoning_agent.upsert_thing"), \
             patch("backend.reasoning_agent.vs_delete"):
            from backend.reasoning_agent import _make_reasoning_tools
            tools, applied = _make_reasoning_tools("test-user")
            rel_fn = tools[5]

            mock_conn.execute.return_value.fetchone = MagicMock(
                side_effect=[None, None, None]
            )

            result = rel_fn(
                from_thing_id="from-uuid",
                to_thing_id="to-uuid",
                relationship_type="involves",
            )
            assert "error" in result

    def test_duplicate_skipped(self):
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        with patch("backend.reasoning_agent.db", return_value=mock_db_ctx), \
             patch("backend.reasoning_agent.upsert_thing"), \
             patch("backend.reasoning_agent.vs_delete"):
            from backend.reasoning_agent import _make_reasoning_tools
            tools, applied = _make_reasoning_tools("test-user")
            rel_fn = tools[5]

            dup_row = MagicMock()
            dup_row.__getitem__ = lambda self, key: "dup-id"
            mock_conn.execute.return_value.fetchone = MagicMock(return_value=dup_row)

            result = rel_fn(
                from_thing_id="a",
                to_thing_id="b",
                relationship_type="sister",
            )
            assert result["status"] == "duplicate"
            assert applied["relationships_created"] == []

    def test_create_success(self):
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        with patch("backend.reasoning_agent.db", return_value=mock_db_ctx), \
             patch("backend.reasoning_agent.upsert_thing"), \
             patch("backend.reasoning_agent.vs_delete"):
            from backend.reasoning_agent import _make_reasoning_tools
            tools, applied = _make_reasoning_tools("test-user")
            rel_fn = tools[5]

            from_row = MagicMock()
            from_row.__getitem__ = lambda self, key: "from-uuid"
            to_row = MagicMock()
            to_row.__getitem__ = lambda self, key: "to-uuid"

            mock_conn.execute.return_value.fetchone = MagicMock(
                side_effect=[None, from_row, to_row]
            )

            result = rel_fn(
                from_thing_id="from-uuid",
                to_thing_id="to-uuid",
                relationship_type="sister",
            )
            assert result["relationship_type"] == "sister"
            assert len(applied["relationships_created"]) == 1


# ---------------------------------------------------------------------------
# run_reasoning_agent — ADK path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reasoning_agent_returns_metadata_from_adk():
    """run_reasoning_agent parses metadata JSON from ADK agent text output."""
    metadata = {
        "questions_for_user": ["What's the deadline?"],
        "priority_question": "What's the deadline?",
        "reasoning_summary": "User wants to create a task.",
        "briefing_mode": False,
    }

    with patch("backend.reasoning_agent._run_agent_for_text") as mock_run:
        mock_run.return_value = json.dumps(metadata)

        # Mock _make_reasoning_tools to avoid DB access
        mock_tools = [MagicMock() for _ in range(6)]
        mock_applied = {
            "created": [], "updated": [], "deleted": [],
            "merged": [], "relationships_created": [],
            "context_things": [], "context_relationships": [],
        }

        with patch("backend.reasoning_agent._make_reasoning_tools",
                    return_value=(mock_tools, mock_applied)):
            from backend.reasoning_agent import run_reasoning_agent

            result = await run_reasoning_agent(
                "Create a task for buying groceries",
                [],
                [],
                api_key="test-key",
                model="google/gemini-2.5-flash",
                user_id="test-user",
            )

    assert result["questions_for_user"] == ["What's the deadline?"]
    assert result["priority_question"] == "What's the deadline?"
    assert result["reasoning_summary"] == "User wants to create a task."
    assert result["briefing_mode"] is False
    assert result["applied_changes"] == mock_applied


@pytest.mark.asyncio
async def test_reasoning_agent_invalid_json_returns_defaults():
    """run_reasoning_agent returns defaults on invalid JSON text output."""
    with patch("backend.reasoning_agent._run_agent_for_text") as mock_run:
        mock_run.return_value = "not valid json {{"

        mock_tools = [MagicMock() for _ in range(6)]
        mock_applied = {
            "created": [{"id": "new-uuid", "title": "Test"}],
            "updated": [], "deleted": [],
            "merged": [], "relationships_created": [],
            "context_things": [], "context_relationships": [],
        }

        with patch("backend.reasoning_agent._make_reasoning_tools",
                    return_value=(mock_tools, mock_applied)):
            from backend.reasoning_agent import run_reasoning_agent

            result = await run_reasoning_agent(
                "hello", [], [], api_key="k", user_id="u",
            )

    # Metadata should have defaults
    assert result["questions_for_user"] == []
    assert result["priority_question"] == ""
    assert result["reasoning_summary"] == ""
    assert result["briefing_mode"] is False
    # But applied_changes should still reflect what the tools did
    assert len(result["applied_changes"]["created"]) == 1


@pytest.mark.asyncio
async def test_reasoning_agent_tracks_usage():
    """run_reasoning_agent accumulates usage stats from ADK events."""
    from backend.agents import UsageStats

    metadata = {"reasoning_summary": "test"}

    with patch("backend.reasoning_agent._run_agent_for_text") as mock_run:
        mock_run.return_value = json.dumps(metadata)

        mock_tools = [MagicMock() for _ in range(6)]
        mock_applied = {
            "created": [], "updated": [], "deleted": [],
            "merged": [], "relationships_created": [],
            "context_things": [], "context_relationships": [],
        }

        with patch("backend.reasoning_agent._make_reasoning_tools",
                    return_value=(mock_tools, mock_applied)):
            from backend.reasoning_agent import run_reasoning_agent

            usage = UsageStats()
            await run_reasoning_agent(
                "test", [], [], usage_stats=usage, api_key="k", user_id="u",
            )

    # _run_agent_for_text was called with usage_stats
    mock_run.assert_called_once()
    call_args = mock_run.call_args
    assert call_args[0][2] is usage  # third positional arg is usage_stats


@pytest.mark.asyncio
async def test_reasoning_agent_ollama_fallback():
    """run_reasoning_agent falls back to ADK when Ollama fails."""
    metadata = {
        "questions_for_user": [],
        "reasoning_summary": "ADK path",
    }

    with (
        patch("backend.reasoning_agent.OLLAMA_MODEL", "test-ollama"),
        patch(
            "backend.reasoning_agent._chat_ollama",
            new_callable=AsyncMock,
            side_effect=Exception("Ollama down"),
        ),
        patch("backend.reasoning_agent._run_agent_for_text") as mock_run,
        patch("backend.reasoning_agent._make_reasoning_tools") as mock_make_tools,
    ):
        mock_run.return_value = json.dumps(metadata)
        mock_tools = [MagicMock() for _ in range(6)]
        mock_applied = {
            "created": [], "updated": [], "deleted": [],
            "merged": [], "relationships_created": [],
            "context_things": [], "context_relationships": [],
        }
        mock_make_tools.return_value = (mock_tools, mock_applied)

        from backend.reasoning_agent import run_reasoning_agent

        result = await run_reasoning_agent(
            "test", [], [], api_key="k", user_id="u",
        )

    assert result["reasoning_summary"] == "ADK path"
    mock_run.assert_called_once()  # ADK path was used


@pytest.mark.asyncio
async def test_reasoning_agent_ollama_success():
    """run_reasoning_agent uses Ollama when it succeeds."""
    ollama_result = {
        "storage_changes": {
            "create": [{"title": "Groceries", "type_hint": "task"}],
            "update": [],
            "delete": [],
            "merge": [],
            "relationships": [],
        },
        "questions_for_user": [],
        "priority_question": "",
        "reasoning_summary": "Created task",
        "briefing_mode": False,
    }

    with (
        patch("backend.reasoning_agent.OLLAMA_MODEL", "test-ollama"),
        patch(
            "backend.reasoning_agent._chat_ollama",
            new_callable=AsyncMock,
            return_value=json.dumps(ollama_result),
        ),
        patch("backend.reasoning_agent.apply_storage_changes") as mock_apply,
        patch("backend.reasoning_agent._run_agent_for_text") as mock_run,
    ):
        mock_apply.return_value = {
            "created": [{"id": "new-uuid", "title": "Groceries"}],
            "updated": [], "deleted": [], "merged": [],
            "relationships_created": [],
            "context_things": [], "context_relationships": [],
        }

        from backend.reasoning_agent import run_reasoning_agent

        result = await run_reasoning_agent(
            "Buy groceries", [], [], api_key="k", user_id="u",
        )

    # Ollama path used, ADK not called
    mock_run.assert_not_called()
    assert result["reasoning_summary"] == "Created task"
    assert len(result["applied_changes"]["created"]) == 1


@pytest.mark.asyncio
async def test_reasoning_agent_priority_question_fallback():
    """priority_question falls back to first question if not set."""
    metadata = {
        "questions_for_user": ["First question", "Second question"],
        "priority_question": "",
        "reasoning_summary": "test",
    }

    with patch("backend.reasoning_agent._run_agent_for_text") as mock_run, \
         patch("backend.reasoning_agent._make_reasoning_tools") as mock_make:
        mock_run.return_value = json.dumps(metadata)
        mock_make.return_value = (
            [MagicMock() for _ in range(5)],
            {"created": [], "updated": [], "deleted": [], "merged": [], "relationships_created": []},
        )

        from backend.reasoning_agent import run_reasoning_agent

        result = await run_reasoning_agent(
            "test", [], [], api_key="k", user_id="u",
        )

    assert result["priority_question"] == "First question"


# ---------------------------------------------------------------------------
# fetch_context tool tests
# ---------------------------------------------------------------------------


class TestFetchContextTool:
    """Tests for the fetch_context tool function."""

    def test_fetch_context_no_fetcher_returns_error(self):
        """fetch_context returns error when no context_fetcher is provided."""
        from backend.reasoning_agent import _make_reasoning_tools

        tools, applied = _make_reasoning_tools("test-user", context_fetcher=None)
        fetch_fn = tools[0]
        result = fetch_fn(query="test")
        assert "error" in result

    def test_fetch_context_empty_query_returns_error(self):
        """fetch_context returns error for empty query."""
        from backend.reasoning_agent import _make_reasoning_tools

        def mock_fetcher(queries, filter_params):
            return [], []

        tools, applied = _make_reasoning_tools("test-user", context_fetcher=mock_fetcher)
        fetch_fn = tools[0]
        result = fetch_fn(query="   ")
        assert "error" in result

    def test_fetch_context_returns_things(self):
        """fetch_context returns things from the fetcher."""
        from backend.reasoning_agent import _make_reasoning_tools

        mock_things = [
            {"id": "t1", "title": "Task 1", "type_hint": "task", "data": "{}", "active": 1, "priority": 2},
            {"id": "t2", "title": "Task 2", "type_hint": "task", "data": "{}", "active": 1, "priority": 3},
        ]
        mock_rels = [{"from_thing_id": "t1", "to_thing_id": "t2", "relationship_type": "related-to"}]

        def mock_fetcher(queries, filter_params):
            return mock_things, mock_rels

        tools, applied = _make_reasoning_tools("test-user", context_fetcher=mock_fetcher)
        fetch_fn = tools[0]
        result = fetch_fn(query="task")

        assert result["things_found"] == 2
        assert len(result["things"]) == 2
        assert result["things"][0]["id"] == "t1"
        assert len(result["relationships"]) == 1
        # Applied should track context things
        assert len(applied["context_things"]) == 2
        assert len(applied["context_relationships"]) == 1

    def test_fetch_context_deduplicates_across_calls(self):
        """Multiple fetch_context calls don't duplicate tracked things."""
        from backend.reasoning_agent import _make_reasoning_tools

        call_count = 0

        def mock_fetcher(queries, filter_params):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"id": "t1", "title": "Task 1"}], []
            return [{"id": "t1", "title": "Task 1"}, {"id": "t2", "title": "Task 2"}], []

        tools, applied = _make_reasoning_tools("test-user", context_fetcher=mock_fetcher)
        fetch_fn = tools[0]

        fetch_fn(query="first")
        assert len(applied["context_things"]) == 1

        fetch_fn(query="second")
        assert len(applied["context_things"]) == 2  # t1 not duplicated

    def test_fetch_context_passes_filter_params(self):
        """fetch_context passes filter params to the fetcher."""
        from backend.reasoning_agent import _make_reasoning_tools

        received_params = {}

        def mock_fetcher(queries, filter_params):
            received_params.update(filter_params)
            return [], []

        tools, applied = _make_reasoning_tools("test-user", context_fetcher=mock_fetcher)
        fetch_fn = tools[0]
        fetch_fn(query="test", active_only=False, type_hint="person")

        assert received_params["active_only"] is False
        assert received_params["type_hint"] == "person"


# ---------------------------------------------------------------------------
# System prompt tests
# ---------------------------------------------------------------------------


def test_tool_system_prompt_mentions_tools():
    """The tool-calling system prompt references all six tools."""
    from backend.reasoning_agent import REASONING_AGENT_TOOL_SYSTEM

    assert "fetch_context" in REASONING_AGENT_TOOL_SYSTEM
    assert "create_thing" in REASONING_AGENT_TOOL_SYSTEM
    assert "update_thing" in REASONING_AGENT_TOOL_SYSTEM
    assert "delete_thing" in REASONING_AGENT_TOOL_SYSTEM
    assert "merge_things" in REASONING_AGENT_TOOL_SYSTEM
    assert "create_relationship" in REASONING_AGENT_TOOL_SYSTEM


def test_tool_system_prompt_no_json_output_schema():
    """The tool system prompt should not contain the old JSON storage_changes schema."""
    from backend.reasoning_agent import REASONING_AGENT_TOOL_SYSTEM

    assert '"storage_changes"' not in REASONING_AGENT_TOOL_SYSTEM


# ---------------------------------------------------------------------------
# Thinking disabled regression test (re-xai6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reasoning_agent_disables_thinking():
    """LiteLlm model for reasoning agent must disable thinking to avoid
    thought_signature errors when routing through OpenAI-compatible providers."""
    metadata = {"reasoning_summary": "test"}

    with patch("backend.reasoning_agent._run_agent_for_text") as mock_run, \
         patch("backend.reasoning_agent._make_reasoning_tools") as mock_make, \
         patch("backend.reasoning_agent._make_litellm_model") as mock_factory, \
         patch("backend.reasoning_agent.LlmAgent"):
        mock_run.return_value = json.dumps(metadata)
        mock_make.return_value = (
            [MagicMock() for _ in range(5)],
            {"created": [], "updated": [], "deleted": [], "merged": [], "relationships_created": []},
        )
        mock_factory.return_value = MagicMock()

        from backend.reasoning_agent import run_reasoning_agent

        await run_reasoning_agent(
            "test", [], [], api_key="k", user_id="u",
        )

    # Verify _make_litellm_model was called with thinking disabled
    mock_factory.assert_called_once()
    call_kwargs = mock_factory.call_args
    extra_body = call_kwargs.kwargs.get("extra_body")
    assert extra_body is not None, "extra_body must be passed to disable thinking"
    assert extra_body.get("thinking_config", {}).get("thinking_budget") == 0, \
        "thinking_budget must be 0 to prevent thought_signature errors"


# ---------------------------------------------------------------------------
# Regression: data_json as non-dict JSON (string, list, number)
# ---------------------------------------------------------------------------


class TestDataJsonStringRegression:
    """Regression tests for TypeError when LLM passes a JSON string as data_json.

    The LLM can pass data_json='"some string"' which is valid JSON but
    json.loads returns a str, not a dict. This caused:
        TypeError: 'str' object is not a mapping
    at the dict merge: {**old_data, **new_data}
    """

    def test_create_thing_with_string_data_json_returns_error(self):
        """create_thing returns error when data_json is a JSON string."""
        from backend.reasoning_agent import _make_reasoning_tools
        tools, applied = _make_reasoning_tools("test-user")
        create_fn = tools[1]

        result = create_fn(title="Test", data_json='"just a string"')
        assert "error" in result
        assert "JSON object" in result["error"]
        assert applied["created"] == []

    def test_update_thing_with_string_data_json_returns_error(self):
        """update_thing returns error when data_json is a JSON string."""
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        with patch("backend.reasoning_agent.db", return_value=mock_db_ctx), \
             patch("backend.reasoning_agent.upsert_thing"), \
             patch("backend.reasoning_agent.vs_delete"):
            from backend.reasoning_agent import _make_reasoning_tools
            tools, applied = _make_reasoning_tools("test-user")
            update_fn = tools[2]

            existing_row = {"id": "ex-uuid", "title": "Existing", "data": '{}'}
            mock_existing = MagicMock()
            mock_existing.__getitem__ = lambda self, key: existing_row[key]
            mock_conn.execute.return_value.fetchone = MagicMock(
                return_value=mock_existing
            )

            result = update_fn(thing_id="ex-uuid", data_json='"string value"')
            assert "error" in result
            assert "JSON object" in result["error"]

    def test_update_thing_with_list_data_json_returns_error(self):
        """update_thing returns error when data_json is a JSON array."""
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        with patch("backend.reasoning_agent.db", return_value=mock_db_ctx), \
             patch("backend.reasoning_agent.upsert_thing"), \
             patch("backend.reasoning_agent.vs_delete"):
            from backend.reasoning_agent import _make_reasoning_tools
            tools, applied = _make_reasoning_tools("test-user")
            update_fn = tools[2]

            existing_row = {"id": "ex-uuid", "title": "Existing", "data": '{}'}
            mock_existing = MagicMock()
            mock_existing.__getitem__ = lambda self, key: existing_row[key]
            mock_conn.execute.return_value.fetchone = MagicMock(
                return_value=mock_existing
            )

            result = update_fn(thing_id="ex-uuid", data_json='[1, 2, 3]')
            assert "error" in result
            assert "JSON object" in result["error"]

    def test_merge_things_with_string_merged_data_json_returns_error(self):
        """merge_things returns error when merged_data_json is a JSON string."""
        from backend.reasoning_agent import _make_reasoning_tools
        tools, applied = _make_reasoning_tools("test-user")
        merge_fn = tools[4]

        result = merge_fn(keep_id="keep-uuid",
                          remove_id="remove-uuid",
                          merged_data_json='"not a dict"')
        assert "error" in result
        assert "JSON object" in result["error"]


class TestToolCatchallErrorHandling:
    """Test that _traced_tool wrapper catches exceptions and returns error dicts."""

    def test_tool_exception_returns_error_dict(self):
        """A tool that raises should return an error dict, not crash."""
        from backend.reasoning_agent import _traced_tool

        def bad_tool(x: str = "") -> dict:
            raise ValueError("something broke")

        wrapped = _traced_tool(bad_tool)
        result = wrapped(x="test")
        assert "error" in result
        assert "something broke" in result["error"]

    def test_tool_type_error_returns_error_dict(self):
        """TypeError from bad data should return error dict, not crash."""
        from backend.reasoning_agent import _traced_tool

        def merge_tool(data: str = "{}") -> dict:
            parsed = {"a": 1}
            return {**parsed, **data}  # type: ignore[dict-item]  # intentional TypeError

        wrapped = _traced_tool(merge_tool)
        result = wrapped(data="not a dict")
        assert "error" in result
        assert "failed" in result["error"]
