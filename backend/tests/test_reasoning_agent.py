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
        with (
            patch("backend.reasoning_agent.db") as mock_db,
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, applied, _fetched = _make_reasoning_tools(user_id)
            return tools, applied, mock_db

    def test_returns_eight_tools(self):
        tools, applied, _ = self._get_tools()
        assert len(tools) == 8
        names = [t.__name__ for t in tools]
        assert "fetch_context" in names
        assert "chat_history" in names
        assert "create_thing" in names
        assert "update_thing" in names
        assert "delete_thing" in names
        assert "merge_things" in names
        assert "create_relationship" in names
        assert "detect_personality_signal" in names

    def test_applied_starts_empty(self):
        _, applied, _ = self._get_tools()
        assert applied == {
            "created": [],
            "updated": [],
            "deleted": [],
            "merged": [],
            "relationships_created": [],
        }


# ---------------------------------------------------------------------------
# chat_history tool tests
# ---------------------------------------------------------------------------


class TestChatHistoryTool:
    def test_chat_history_no_session_returns_empty(self):
        """chat_history with no session_id returns empty results."""
        from backend.reasoning_agent import _make_reasoning_tools

        tools, _, _fetched = _make_reasoning_tools("test-user", session_id="")
        history_fn = tools[1]
        result = history_fn()
        assert result["messages"] == []
        assert result["count"] == 0
        assert "error" in result

    def test_chat_history_returns_messages(self):
        """chat_history retrieves messages from the DB."""
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        mock_rows = [
            {"role": "user", "content": "hello", "timestamp": "2026-03-22T00:00:00"},
            {"role": "assistant", "content": "hi there", "timestamp": "2026-03-22T00:00:01"},
        ]
        # Rows come back in DESC order, reversed by the tool
        mock_conn.execute.return_value.fetchall.return_value = list(reversed(mock_rows))

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, _, _fetched = _make_reasoning_tools("test-user", session_id="test-session")
            history_fn = tools[1]
            result = history_fn(n=10)

        assert result["count"] == 2
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][1]["role"] == "assistant"

    def test_chat_history_with_search_query(self):
        """chat_history filters by search_query."""
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchall.return_value = [
            {"role": "user", "content": "budget meeting", "timestamp": "2026-03-22T00:00:00"},
        ]

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, _, _fetched = _make_reasoning_tools("test-user", session_id="test-session")
            history_fn = tools[1]
            result = history_fn(n=5, search_query="budget")

        assert result["count"] == 1
        # Verify the SQL used LIKE with the search query
        call_args = mock_conn.execute.call_args
        assert "%budget%" in call_args[0][1]

    def test_chat_history_clamps_n(self):
        """chat_history clamps n to 1-50 range."""
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, _, _fetched = _make_reasoning_tools("test-user", session_id="s")
            history_fn = tools[1]

            # n=100 should be clamped to 50
            history_fn(n=100)
            call_args = mock_conn.execute.call_args
            assert call_args[0][1][-1] == 50

            # n=-5 should be clamped to 1
            history_fn(n=-5)
            call_args = mock_conn.execute.call_args
            assert call_args[0][1][-1] == 1


# ---------------------------------------------------------------------------
# create_thing tool tests
# ---------------------------------------------------------------------------


class TestCreateThingTool:
    def test_create_thing_empty_title_returns_error(self):
        from backend.reasoning_agent import _make_reasoning_tools

        tools, applied, _fetched = _make_reasoning_tools("test-user")
        create_fn = tools[2]
        result = create_fn(title="   ")
        assert "error" in result
        assert applied["created"] == []

    def test_create_thing_dedup_existing(self):
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, applied, _fetched = _make_reasoning_tools("test-user")
            create_fn = tools[2]

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

            mock_conn.execute.return_value.fetchone = MagicMock(side_effect=[mock_existing, mock_updated])

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

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing") as mock_upsert,
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, applied, _fetched = _make_reasoning_tools("test-user")
            create_fn = tools[2]

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

            mock_conn.execute.return_value.fetchone = MagicMock(side_effect=[None, mock_new])

            create_fn(title="Brand New", type_hint="task")

            assert len(applied["created"]) == 1
            mock_upsert.assert_called_once()

    def test_create_entity_defaults_surface_false(self):
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, applied, _fetched = _make_reasoning_tools("test-user")
            create_fn = tools[2]

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

            mock_conn.execute.return_value.fetchone = MagicMock(side_effect=[None, mock_new])

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

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, applied, _fetched = _make_reasoning_tools("test-user")
            delete_fn = tools[4]

            mock_conn.execute.return_value.fetchone = MagicMock(return_value=None)
            result = delete_fn(thing_id="nonexistent")
            assert "error" in result
            assert applied["deleted"] == []

    def test_delete_success(self):
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete") as mock_vs_delete,
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, applied, _fetched = _make_reasoning_tools("test-user")
            delete_fn = tools[4]

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

        tools, applied, _fetched = _make_reasoning_tools("test-user")
        rel_fn = tools[6]
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

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, applied, _fetched = _make_reasoning_tools("test-user")
            rel_fn = tools[6]

            mock_conn.execute.return_value.fetchone = MagicMock(side_effect=[None, None, None])

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

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, applied, _fetched = _make_reasoning_tools("test-user")
            rel_fn = tools[6]

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

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, applied, _fetched = _make_reasoning_tools("test-user")
            rel_fn = tools[6]

            from_row = MagicMock()
            from_row.__getitem__ = lambda self, key: "from-uuid"
            to_row = MagicMock()
            to_row.__getitem__ = lambda self, key: "to-uuid"

            mock_conn.execute.return_value.fetchone = MagicMock(side_effect=[None, from_row, to_row])

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
            "created": [],
            "updated": [],
            "deleted": [],
            "merged": [],
            "relationships_created": [],
        }

        with patch("backend.reasoning_agent._make_reasoning_tools", return_value=(mock_tools, mock_applied, {})):
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
            "updated": [],
            "deleted": [],
            "merged": [],
            "relationships_created": [],
        }

        with patch("backend.reasoning_agent._make_reasoning_tools", return_value=(mock_tools, mock_applied, {})):
            from backend.reasoning_agent import run_reasoning_agent

            result = await run_reasoning_agent(
                "hello",
                [],
                [],
                api_key="k",
                user_id="u",
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
            "created": [],
            "updated": [],
            "deleted": [],
            "merged": [],
            "relationships_created": [],
        }

        with patch("backend.reasoning_agent._make_reasoning_tools", return_value=(mock_tools, mock_applied, {})):
            from backend.reasoning_agent import run_reasoning_agent

            usage = UsageStats()
            await run_reasoning_agent(
                "test",
                [],
                [],
                usage_stats=usage,
                api_key="k",
                user_id="u",
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
            "created": [],
            "updated": [],
            "deleted": [],
            "merged": [],
            "relationships_created": [],
        }
        mock_make_tools.return_value = (mock_tools, mock_applied, {})

        from backend.reasoning_agent import run_reasoning_agent

        result = await run_reasoning_agent(
            "test",
            [],
            [],
            api_key="k",
            user_id="u",
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
            "updated": [],
            "deleted": [],
            "merged": [],
            "relationships_created": [],
        }

        from backend.reasoning_agent import run_reasoning_agent

        result = await run_reasoning_agent(
            "Buy groceries",
            [],
            [],
            api_key="k",
            user_id="u",
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

    with (
        patch("backend.reasoning_agent._run_agent_for_text") as mock_run,
        patch("backend.reasoning_agent._make_reasoning_tools") as mock_make,
    ):
        mock_run.return_value = json.dumps(metadata)
        mock_make.return_value = (
            [MagicMock() for _ in range(6)],
            {"created": [], "updated": [], "deleted": [], "merged": [], "relationships_created": []},
            {},
        )

        from backend.reasoning_agent import run_reasoning_agent

        result = await run_reasoning_agent(
            "test",
            [],
            [],
            api_key="k",
            user_id="u",
        )

    assert result["priority_question"] == "First question"


# ---------------------------------------------------------------------------
# System prompt tests
# ---------------------------------------------------------------------------


def test_tool_system_prompt_mentions_tools():
    """The tool-calling system prompt references all five tools."""
    from backend.reasoning_agent import REASONING_AGENT_TOOL_SYSTEM

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

    with (
        patch("backend.reasoning_agent._run_agent_for_text") as mock_run,
        patch("backend.reasoning_agent._make_reasoning_tools") as mock_make,
        patch("backend.reasoning_agent._make_litellm_model") as mock_factory,
        patch("backend.reasoning_agent.LlmAgent"),
    ):
        mock_run.return_value = json.dumps(metadata)
        mock_make.return_value = (
            [MagicMock() for _ in range(6)],
            {"created": [], "updated": [], "deleted": [], "merged": [], "relationships_created": []},
            {},
        )
        mock_factory.return_value = MagicMock()

        from backend.reasoning_agent import run_reasoning_agent

        await run_reasoning_agent(
            "test",
            [],
            [],
            api_key="k",
            user_id="u",
        )

    # Verify _make_litellm_model was called with thinking enabled (re-zo fix)
    mock_factory.assert_called_once()
    call_kwargs = mock_factory.call_args
    extra_body = call_kwargs.kwargs.get("extra_body")
    assert extra_body is not None, "extra_body must be passed to enable thinking"
    assert extra_body.get("thinking_config", {}).get("thinking_budget") == 1000, (
        "thinking_budget must be 1000 to enable reasoning capabilities"
    )


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

        tools, applied, _fetched = _make_reasoning_tools("test-user")
        create_fn = tools[2]

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

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, applied, _fetched = _make_reasoning_tools("test-user")
            update_fn = tools[3]

            existing_row = {"id": "ex-uuid", "title": "Existing", "data": "{}"}
            mock_existing = MagicMock()
            mock_existing.__getitem__ = lambda self, key: existing_row[key]
            mock_conn.execute.return_value.fetchone = MagicMock(return_value=mock_existing)

            result = update_fn(thing_id="ex-uuid", data_json='"string value"')
            assert "error" in result
            assert "JSON object" in result["error"]

    def test_update_thing_with_list_data_json_returns_error(self):
        """update_thing returns error when data_json is a JSON array."""
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, applied, _fetched = _make_reasoning_tools("test-user")
            update_fn = tools[3]

            existing_row = {"id": "ex-uuid", "title": "Existing", "data": "{}"}
            mock_existing = MagicMock()
            mock_existing.__getitem__ = lambda self, key: existing_row[key]
            mock_conn.execute.return_value.fetchone = MagicMock(return_value=mock_existing)

            result = update_fn(thing_id="ex-uuid", data_json="[1, 2, 3]")
            assert "error" in result
            assert "JSON object" in result["error"]

    def test_merge_things_with_string_merged_data_json_returns_error(self):
        """merge_things returns error when merged_data_json is a JSON string."""
        from backend.reasoning_agent import _make_reasoning_tools

        tools, applied, _fetched = _make_reasoning_tools("test-user")
        merge_fn = tools[5]

        result = merge_fn(keep_id="keep-uuid", remove_id="remove-uuid", merged_data_json='"not a dict"')
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


# ---------------------------------------------------------------------------
# thought_signature helpers (GH #158 / Sentry RELI-ZO-5)
# ---------------------------------------------------------------------------


class TestIsThoughtSignatureError:
    """Test _is_thought_signature_error detects Gemini thought_signature errors."""

    def test_detects_missing_thought_signature(self):
        from backend.reasoning_agent import _is_thought_signature_error

        exc = Exception(
            "BadRequestError: Error code: 400 - {'error': {'origin': 'provider', "
            "'message': 'Function call is missing a thought_signature in functionCall parts.'}}"
        )
        assert _is_thought_signature_error(exc) is True

    def test_ignores_unrelated_bad_request(self):
        from backend.reasoning_agent import _is_thought_signature_error

        exc = Exception("BadRequestError: invalid model parameter")
        assert _is_thought_signature_error(exc) is False

    def test_ignores_generic_exception(self):
        from backend.reasoning_agent import _is_thought_signature_error

        assert _is_thought_signature_error(ValueError("oops")) is False


class TestRunAdkWithThoughtSignatureFallback:
    """Test _run_adk_with_thought_signature_fallback retries on thought_signature errors."""

    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        from backend.reasoning_agent import _run_adk_with_thought_signature_fallback

        agent = MagicMock()
        with patch("backend.reasoning_agent._run_agent_for_text", new=AsyncMock(return_value="ok")):
            result = await _run_adk_with_thought_signature_fallback(
                agent,
                "full prompt",
                "fallback prompt",
            )
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_falls_back_to_skip_validator_on_persistent_error(self):
        from backend.reasoning_agent import _run_adk_with_thought_signature_fallback

        agent = MagicMock()
        agent.model.model = "openai/google/gemini-3-flash-preview"
        call_count = 0

        async def mock_run(ag, prompt, stats=None):
            nonlocal call_count
            call_count += 1
            # Fail both first try (history) and second try (no history)
            if call_count <= 2:
                raise Exception("Function call is missing a thought_signature in functionCall parts.")
            return f"fallback ok with {ag.model.model}"

        with (
            patch("backend.reasoning_agent._run_agent_for_text", side_effect=mock_run),
            patch("backend.reasoning_agent._make_litellm_model") as mock_factory,
        ):
            # Mock the factory to return a mock model with the skip parameter
            mock_skip = MagicMock()
            mock_skip.model = "openai/google/gemini-3-flash-preview"
            mock_factory.return_value = mock_skip

            result = await _run_adk_with_thought_signature_fallback(
                agent, "full with history", "just current turn", usage_stats=None, api_key="test-api-key"
            )

        assert "fallback ok" in result
        assert call_count == 3
        # Verify factory was called with the skip parameter AND the original api_key
        mock_factory.assert_called_once()
        assert mock_factory.call_args.kwargs["extra_body"]["thought_signature"] == "skip_thought_signature_validator"
        assert mock_factory.call_args.kwargs["api_key"] == "test-api-key"

    @pytest.mark.asyncio
    async def test_raises_non_thought_signature_errors(self):
        from backend.reasoning_agent import _run_adk_with_thought_signature_fallback

        agent = MagicMock()

        with (
            patch(
                "backend.reasoning_agent._run_agent_for_text",
                new=AsyncMock(side_effect=ValueError("unrelated error")),
            ),
            pytest.raises(ValueError, match="unrelated error"),
        ):
            await _run_adk_with_thought_signature_fallback(
                agent,
                "full prompt",
                "fallback prompt",
            )


class TestHistoryEnrichmentInReasoningAgent:
    """Test that run_reasoning_agent includes enrichment metadata separately."""

    @pytest.mark.asyncio
    async def test_includes_enrichment_metadata_separately(self):
        """Assistant turns should have pristine content with enrichment in a separate tag."""
        metadata = {"reasoning_summary": "test"}
        history = [
            {"role": "user", "content": "Create a project called X"},
            {"role": "assistant", "content": "Done!", "enrichment_metadata": "[Created: X (project)]"},
            {"role": "user", "content": "Now update it"},
        ]

        with (
            patch("backend.reasoning_agent._run_adk_with_thought_signature_fallback") as mock_run,
            patch("backend.reasoning_agent._make_reasoning_tools") as mock_make,
            patch("backend.reasoning_agent._make_litellm_model") as mock_factory,
            patch("backend.reasoning_agent.LlmAgent"),
        ):
            mock_run.return_value = json.dumps(metadata)
            mock_make.return_value = (
                [MagicMock() for _ in range(6)],
                {"created": [], "updated": [], "deleted": [], "merged": [], "relationships_created": []},
                {},
            )
            mock_factory.return_value = MagicMock()

            from backend.reasoning_agent import run_reasoning_agent

            await run_reasoning_agent(
                "Now update it",
                history,
                [],
                api_key="k",
                user_id="u",
            )

        # Check the full_prompt passed to the fallback function
        call_args = mock_run.call_args
        full_prompt = call_args.args[1]  # second positional arg
        # User turns should be included
        assert "<user>" in full_prompt
        # Assistant turn content should be pristine (no markers appended)
        assert "<assistant>Done!</assistant>" in full_prompt
        # Enrichment metadata should appear in a separate tag
        assert "<enrichment>[Created: X (project)]</enrichment>" in full_prompt

    @pytest.mark.asyncio
    async def test_keeps_assistant_turns_without_markers(self):
        """Assistant turns without tool call markers should be kept in history."""
        metadata = {"reasoning_summary": "test"}
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there, how can I help?"},
            {"role": "user", "content": "Tell me about my projects"},
        ]

        with (
            patch("backend.reasoning_agent._run_adk_with_thought_signature_fallback") as mock_run,
            patch("backend.reasoning_agent._make_reasoning_tools") as mock_make,
            patch("backend.reasoning_agent._make_litellm_model") as mock_factory,
            patch("backend.reasoning_agent.LlmAgent"),
        ):
            mock_run.return_value = json.dumps(metadata)
            mock_make.return_value = (
                [MagicMock() for _ in range(6)],
                {"created": [], "updated": [], "deleted": [], "merged": [], "relationships_created": []},
                {},
            )
            mock_factory.return_value = MagicMock()

            from backend.reasoning_agent import run_reasoning_agent

            await run_reasoning_agent(
                "Tell me about my projects",
                history,
                [],
                api_key="k",
                user_id="u",
            )

        call_args = mock_run.call_args
        full_prompt = call_args.args[1]
        # Both user and assistant turns should be present
        assert "Hi there, how can I help?" in full_prompt


# ---------------------------------------------------------------------------
# detect_personality_signal tool tests
# ---------------------------------------------------------------------------


class TestDetectPersonalitySignalTool:
    """Tests for the detect_personality_signal tool."""

    def _make_mock_db(self):
        mock_conn = MagicMock()
        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)
        return mock_conn, mock_db_ctx

    def test_invalid_signal_type_returns_error(self):
        from backend.reasoning_agent import _make_reasoning_tools

        tools, _, _fetched = _make_reasoning_tools("test-user")
        signal_fn = tools[7]  # detect_personality_signal
        result = signal_fn(signal_type="invalid", pattern="test")
        assert "error" in result

    def test_empty_pattern_returns_error(self):
        from backend.reasoning_agent import _make_reasoning_tools

        tools, _, _fetched = _make_reasoning_tools("test-user")
        signal_fn = tools[7]
        result = signal_fn(signal_type="positive", pattern="   ")
        assert "error" in result

    def test_creates_new_preference_thing(self):
        mock_conn, mock_db_ctx = self._make_mock_db()

        # No existing preference Thing
        mock_conn.execute.return_value.fetchone = MagicMock(side_effect=[None, None])

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, applied, _fetched = _make_reasoning_tools("test-user")
            signal_fn = tools[7]

            # First fetchone for existing pref Thing (None = not found)
            # Second fetchone for the newly inserted row
            new_row = {
                "id": "new-pref-uuid",
                "title": "Reli Communication Preferences",
                "type_hint": "preference",
                "data": '{"patterns": []}',
                "active": 1,
                "surface": 0,
            }
            mock_new = MagicMock()
            mock_new.__getitem__ = lambda self, key: new_row[key]
            mock_new.keys = lambda: new_row.keys()

            mock_conn.execute.return_value.fetchone = MagicMock(side_effect=[None, mock_new])

            result = signal_fn(
                signal_type="explicit_correction",
                pattern="No emoji",
                approach_used="Used emoji in task title",
            )

            assert result["action"] == "created"
            assert result["pattern"] == "No emoji"
            assert result["signal_type"] == "explicit_correction"
            assert result["total_patterns"] == 1

    def test_strengthens_existing_pattern(self):
        mock_conn, mock_db_ctx = self._make_mock_db()

        existing_data = {
            "patterns": [
                {
                    "pattern": "No emoji",
                    "signal_type": "explicit_correction",
                    "confidence": "strong",
                    "observations": 2,
                    "last_observed": "2026-03-20T00:00:00Z",
                    "last_approach": "Used emoji",
                }
            ]
        }
        existing_row = {
            "id": "pref-uuid",
            "title": "Reli Communication Preferences",
            "type_hint": "preference",
            "data": json.dumps(existing_data),
            "active": 1,
            "surface": 0,
        }
        mock_existing = MagicMock()
        mock_existing.__getitem__ = lambda self, key: existing_row[key]
        mock_existing.keys = lambda: existing_row.keys()

        updated_row = dict(existing_row)
        mock_updated = MagicMock()
        mock_updated.__getitem__ = lambda self, key: updated_row[key]
        mock_updated.keys = lambda: updated_row.keys()

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, applied, _fetched = _make_reasoning_tools("test-user")
            signal_fn = tools[7]

            mock_conn.execute.return_value.fetchone = MagicMock(side_effect=[mock_existing, mock_updated])

            result = signal_fn(
                signal_type="explicit_correction",
                pattern="No emoji",
                approach_used="Used emoji again",
            )

            assert result["action"] == "strengthened"
            assert result["id"] == "pref-uuid"

    def test_adds_new_pattern_to_existing_thing(self):
        mock_conn, mock_db_ctx = self._make_mock_db()

        existing_data = {
            "patterns": [
                {
                    "pattern": "No emoji",
                    "signal_type": "explicit_correction",
                    "confidence": "strong",
                    "observations": 3,
                    "last_observed": "2026-03-20T00:00:00Z",
                    "last_approach": "",
                }
            ]
        }
        existing_row = {
            "id": "pref-uuid",
            "title": "Reli Communication Preferences",
            "type_hint": "preference",
            "data": json.dumps(existing_data),
            "active": 1,
            "surface": 0,
        }
        mock_existing = MagicMock()
        mock_existing.__getitem__ = lambda self, key: existing_row[key]
        mock_existing.keys = lambda: existing_row.keys()

        updated_row = dict(existing_row)
        mock_updated = MagicMock()
        mock_updated.__getitem__ = lambda self, key: updated_row[key]
        mock_updated.keys = lambda: updated_row.keys()

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, applied, _fetched = _make_reasoning_tools("test-user")
            signal_fn = tools[7]

            mock_conn.execute.return_value.fetchone = MagicMock(side_effect=[mock_existing, mock_updated])

            result = signal_fn(
                signal_type="positive",
                pattern="Likes bullet points",
                approach_used="Used bullet point format",
            )

            assert result["action"] == "added"
            assert result["total_patterns"] == 2

    def test_explicit_correction_always_strong_confidence(self):
        mock_conn, mock_db_ctx = self._make_mock_db()

        # Existing pattern with moderate confidence and 1 observation
        existing_data = {
            "patterns": [
                {
                    "pattern": "Be concise",
                    "signal_type": "negative",
                    "confidence": "moderate",
                    "observations": 1,
                    "last_observed": "2026-03-20T00:00:00Z",
                    "last_approach": "",
                }
            ]
        }
        existing_row = {
            "id": "pref-uuid",
            "title": "Reli Communication Preferences",
            "type_hint": "preference",
            "data": json.dumps(existing_data),
            "active": 1,
            "surface": 0,
        }
        mock_existing = MagicMock()
        mock_existing.__getitem__ = lambda self, key: existing_row[key]
        mock_existing.keys = lambda: existing_row.keys()

        updated_row = dict(existing_row)
        mock_updated = MagicMock()
        mock_updated.__getitem__ = lambda self, key: updated_row[key]
        mock_updated.keys = lambda: updated_row.keys()

        with (
            patch("backend.reasoning_agent.db", return_value=mock_db_ctx),
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, applied, _fetched = _make_reasoning_tools("test-user")
            signal_fn = tools[7]

            mock_conn.execute.return_value.fetchone = MagicMock(side_effect=[mock_existing, mock_updated])

            # Same pattern but as explicit_correction should upgrade to strong
            result = signal_fn(
                signal_type="explicit_correction",
                pattern="Be concise",
            )

            assert result["action"] == "strengthened"
            # Verify the UPDATE call included strong confidence in the data
            update_call = mock_conn.execute.call_args_list[-2]  # UPDATE call
            if update_call and len(update_call[0]) > 1:
                args = update_call[0][1]
                # The first arg should be the JSON data string
                if isinstance(args[0], str):
                    updated_data = json.loads(args[0])
                    assert updated_data["patterns"][0]["confidence"] == "strong"
