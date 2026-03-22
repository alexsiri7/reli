"""Tests for the think agent (run_think_agent) in reasoning_agent.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend.reasoning_agent import _THINK_SYSTEM, _make_think_tools, run_think_agent


class TestThinkSystemPrompt:
    """Verify the think system prompt has the right structure."""

    def test_contains_instruction_schema(self) -> None:
        assert '"instructions"' in _THINK_SYSTEM
        assert '"action"' in _THINK_SYSTEM
        assert "create_thing" in _THINK_SYSTEM
        assert "update_thing" in _THINK_SYSTEM
        assert "delete_thing" in _THINK_SYSTEM
        assert "create_relationship" in _THINK_SYSTEM

    def test_contains_ref_explanation(self) -> None:
        assert "ref" in _THINK_SYSTEM
        assert "ref_0" in _THINK_SYSTEM

    def test_no_mutation_instructions(self) -> None:
        """The think prompt should not instruct the agent to execute changes."""
        assert "You do NOT execute changes yourself" in _THINK_SYSTEM

    def test_has_fetch_context_tool(self) -> None:
        assert "fetch_context" in _THINK_SYSTEM


class TestMakeThinkTools:
    """Test the _make_think_tools factory."""

    def test_returns_one_tool(self, patched_db: Any) -> None:
        tools, context = _make_think_tools(user_id="test-user")
        assert len(tools) == 1
        assert tools[0].__name__ == "fetch_context"

    def test_context_dict_initialized(self, patched_db: Any) -> None:
        _, context = _make_think_tools(user_id="test-user")
        assert context == {"things": [], "relationships": []}

    def test_fetch_context_empty_queries(self, patched_db: Any) -> None:
        tools, _ = _make_think_tools(user_id="test-user")
        fetch_context = tools[0]
        result = fetch_context()
        assert result["count"] == 0
        assert result["things"] == []


class TestRunThinkAgent:
    """Test the run_think_agent function."""

    @pytest.mark.asyncio
    @patch("backend.reasoning_agent._run_adk_with_thought_signature_fallback", new_callable=AsyncMock)
    async def test_returns_parsed_instructions(self, mock_run: AsyncMock, patched_db: Any) -> None:
        mock_run.return_value = (
            '{"instructions": [{"action": "create_thing", "params": {"title": "Test"}}],'
            '"questions_for_user": [], "reasoning_summary": "Created test."}'
        )
        result = await run_think_agent(
            message="Create a test thing",
            user_id="test-user",
        )
        assert len(result["instructions"]) == 1
        assert result["instructions"][0]["action"] == "create_thing"
        assert result["reasoning_summary"] == "Created test."

    @pytest.mark.asyncio
    @patch("backend.reasoning_agent._run_adk_with_thought_signature_fallback", new_callable=AsyncMock)
    async def test_returns_questions_when_ambiguous(self, mock_run: AsyncMock, patched_db: Any) -> None:
        mock_run.return_value = (
            '{"instructions": [], "questions_for_user": ["What do you mean?"],'
            '"reasoning_summary": "Ambiguous request."}'
        )
        result = await run_think_agent(message="Do the thing", user_id="test-user")
        assert result["instructions"] == []
        assert result["questions_for_user"] == ["What do you mean?"]

    @pytest.mark.asyncio
    @patch("backend.reasoning_agent._run_adk_with_thought_signature_fallback", new_callable=AsyncMock)
    async def test_handles_non_json_response(self, mock_run: AsyncMock, patched_db: Any) -> None:
        mock_run.return_value = "I couldn't understand the request."
        result = await run_think_agent(message="gibberish", user_id="test-user")
        assert result["instructions"] == []
        assert "I couldn't understand" in result["reasoning_summary"]

    @pytest.mark.asyncio
    @patch("backend.reasoning_agent._run_adk_with_thought_signature_fallback", new_callable=AsyncMock)
    async def test_handles_empty_response(self, mock_run: AsyncMock, patched_db: Any) -> None:
        mock_run.return_value = ""
        result = await run_think_agent(message="hello", user_id="test-user")
        assert result["instructions"] == []
        assert result["questions_for_user"] == []

    @pytest.mark.asyncio
    @patch("backend.reasoning_agent._run_adk_with_thought_signature_fallback", new_callable=AsyncMock)
    async def test_passes_context_to_prompt(self, mock_run: AsyncMock, patched_db: Any) -> None:
        mock_run.return_value = '{"instructions": [], "questions_for_user": [], "reasoning_summary": ""}'
        await run_think_agent(
            message="Test message",
            context="Extra context here",
            user_id="test-user",
        )
        # Check the prompt passed to the agent includes the context
        call_args = mock_run.call_args
        prompt = call_args[0][1]  # full_prompt is second positional arg
        assert "Extra context here" in prompt
        assert "Test message" in prompt

    @pytest.mark.asyncio
    @patch("backend.reasoning_agent._run_adk_with_thought_signature_fallback", new_callable=AsyncMock)
    async def test_markdown_fences_stripped(self, mock_run: AsyncMock, patched_db: Any) -> None:
        mock_run.return_value = (
            '```json\n{"instructions": [], "questions_for_user": [], "reasoning_summary": "clean"}\n```'
        )
        result = await run_think_agent(message="test", user_id="test-user")
        assert result["reasoning_summary"] == "clean"

    @pytest.mark.asyncio
    @patch("backend.reasoning_agent._run_adk_with_thought_signature_fallback", new_callable=AsyncMock)
    async def test_ref_instructions_preserved(self, mock_run: AsyncMock, patched_db: Any) -> None:
        mock_run.return_value = (
            '{"instructions": ['
            '{"action": "create_thing",'
            ' "params": {"title": "Alice", "type_hint": "person"},'
            ' "ref": "ref_0"},'
            '{"action": "create_relationship",'
            ' "params": {"from_thing_id": "ref_0",'
            ' "to_thing_id": "existing-id",'
            ' "relationship_type": "sister"}}'
            '], "questions_for_user": [],'
            ' "reasoning_summary": "Linked Alice."}'
        )
        result = await run_think_agent(message="My sister Alice", user_id="test-user")
        assert result["instructions"][0]["ref"] == "ref_0"
        assert result["instructions"][1]["params"]["from_thing_id"] == "ref_0"
