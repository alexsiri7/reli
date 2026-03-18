"""Tests for the ADK LlmAgent-based context agent."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

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
    event.model_version = "google/gemini-2.5-flash-lite"

    if usage:
        um = MagicMock()
        um.prompt_token_count = 10
        um.candidates_token_count = 5
        um.total_token_count = 15
        event.usage_metadata = um
    else:
        event.usage_metadata = None

    return event


async def _mock_run_async_factory(events):
    """Create an async generator that yields mock events."""
    for e in events:
        yield e


# ---------------------------------------------------------------------------
# run_context_agent — ADK path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_agent_returns_parsed_json():
    """run_context_agent parses JSON from ADK LlmAgent response."""
    expected = {
        "search_queries": ["project alpha"],
        "fetch_ids": [],
        "filter_params": {"active_only": True, "type_hint": None},
        "needs_web_search": False,
        "web_search_query": None,
        "gmail_query": None,
        "include_calendar": False,
    }
    response_text = json.dumps(expected)

    events = [
        _make_mock_event(response_text, usage=True),
    ]

    with patch("backend.context_agent.Runner") as MockRunner:
        mock_runner = MagicMock()
        mock_runner.run_async = MagicMock(
            return_value=_mock_run_async_factory(events)
        )
        MockRunner.return_value = mock_runner

        with patch("backend.context_agent._session_service") as mock_svc:
            mock_session = MagicMock()
            mock_session.id = "test-session"
            mock_svc.create_session = AsyncMock(return_value=mock_session)

            from backend.context_agent import run_context_agent

            result = await run_context_agent(
                "Tell me about project alpha",
                [],
                api_key="test-key",
                model="google/gemini-2.5-flash-lite",
            )

    assert result["search_queries"] == ["project alpha"]
    assert result["needs_web_search"] is False


@pytest.mark.asyncio
async def test_context_agent_invalid_json_fallback():
    """run_context_agent falls back to message-as-query on invalid JSON."""
    events = [
        _make_mock_event("not valid json {{{", usage=True),
    ]

    with patch("backend.context_agent.Runner") as MockRunner:
        mock_runner = MagicMock()
        mock_runner.run_async = MagicMock(
            return_value=_mock_run_async_factory(events)
        )
        MockRunner.return_value = mock_runner

        with patch("backend.context_agent._session_service") as mock_svc:
            mock_session = MagicMock()
            mock_session.id = "test-session"
            mock_svc.create_session = AsyncMock(return_value=mock_session)

            from backend.context_agent import run_context_agent

            result = await run_context_agent(
                "hello world",
                [],
                api_key="test-key",
            )

    assert result["search_queries"] == ["hello world"]
    assert result["filter_params"]["active_only"] is True


@pytest.mark.asyncio
async def test_context_agent_tracks_usage():
    """run_context_agent accumulates usage stats from ADK events."""
    from backend.agents import UsageStats

    events = [
        _make_mock_event('{"search_queries": ["test"], "filter_params": {}}', usage=True),
    ]

    with patch("backend.context_agent.Runner") as MockRunner:
        mock_runner = MagicMock()
        mock_runner.run_async = MagicMock(
            return_value=_mock_run_async_factory(events)
        )
        MockRunner.return_value = mock_runner

        with patch("backend.context_agent._session_service") as mock_svc:
            mock_session = MagicMock()
            mock_session.id = "test-session"
            mock_svc.create_session = AsyncMock(return_value=mock_session)

            from backend.context_agent import run_context_agent

            usage = UsageStats()
            await run_context_agent("test", [], usage_stats=usage, api_key="k")

    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 5
    assert usage.api_calls == 1


@pytest.mark.asyncio
async def test_context_agent_ollama_fallback():
    """run_context_agent tries Ollama first, falls back to ADK on failure."""
    expected = {
        "search_queries": ["adk result"],
        "filter_params": {"active_only": True},
    }
    events = [
        _make_mock_event(json.dumps(expected), usage=True),
    ]

    with (
        patch("backend.context_agent.OLLAMA_MODEL", "test-ollama-model"),
        patch(
            "backend.context_agent._chat_ollama",
            new_callable=AsyncMock,
            side_effect=Exception("Ollama down"),
        ),
        patch("backend.context_agent.Runner") as MockRunner,
        patch("backend.context_agent._session_service") as mock_svc,
    ):
        mock_runner = MagicMock()
        mock_runner.run_async = MagicMock(
            return_value=_mock_run_async_factory(events)
        )
        MockRunner.return_value = mock_runner

        mock_session = MagicMock()
        mock_session.id = "test-session"
        mock_svc.create_session = AsyncMock(return_value=mock_session)

        from backend.context_agent import run_context_agent

        result = await run_context_agent("test", [], api_key="k")

    assert result["search_queries"] == ["adk result"]


# ---------------------------------------------------------------------------
# run_context_refinement — ADK path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_refinement_done():
    """run_context_refinement returns done=True when agent says so."""
    events = [
        _make_mock_event('{"done": true}', usage=True),
    ]

    with patch("backend.context_agent.Runner") as MockRunner:
        mock_runner = MagicMock()
        mock_runner.run_async = MagicMock(
            return_value=_mock_run_async_factory(events)
        )
        MockRunner.return_value = mock_runner

        with patch("backend.context_agent._session_service") as mock_svc:
            mock_session = MagicMock()
            mock_session.id = "test-session"
            mock_svc.create_session = AsyncMock(return_value=mock_session)

            from backend.context_agent import run_context_refinement

            result = await run_context_refinement(
                "test message",
                [],
                [{"id": "1", "title": "Test Thing"}],
                ["previous query"],
                api_key="test-key",
            )

    assert result["done"] is True


@pytest.mark.asyncio
async def test_context_refinement_needs_more():
    """run_context_refinement returns additional queries when not done."""
    refinement_result = {
        "done": False,
        "search_queries": ["more stuff"],
        "thing_ids": ["uuid-123"],
        "filter_params": {"active_only": True},
    }
    events = [
        _make_mock_event(json.dumps(refinement_result), usage=True),
    ]

    with patch("backend.context_agent.Runner") as MockRunner:
        mock_runner = MagicMock()
        mock_runner.run_async = MagicMock(
            return_value=_mock_run_async_factory(events)
        )
        MockRunner.return_value = mock_runner

        with patch("backend.context_agent._session_service") as mock_svc:
            mock_session = MagicMock()
            mock_session.id = "test-session"
            mock_svc.create_session = AsyncMock(return_value=mock_session)

            from backend.context_agent import run_context_refinement

            result = await run_context_refinement(
                "test",
                [],
                [{"id": "1", "title": "Existing"}],
                ["old query"],
                api_key="k",
            )

    assert result["done"] is False
    assert result["search_queries"] == ["more stuff"]
    assert result["thing_ids"] == ["uuid-123"]


@pytest.mark.asyncio
async def test_context_refinement_invalid_json_returns_done():
    """run_context_refinement returns done=True on invalid JSON."""
    events = [
        _make_mock_event("invalid json!!!", usage=True),
    ]

    with patch("backend.context_agent.Runner") as MockRunner:
        mock_runner = MagicMock()
        mock_runner.run_async = MagicMock(
            return_value=_mock_run_async_factory(events)
        )
        MockRunner.return_value = mock_runner

        with patch("backend.context_agent._session_service") as mock_svc:
            mock_session = MagicMock()
            mock_session.id = "test-session"
            mock_svc.create_session = AsyncMock(return_value=mock_session)

            from backend.context_agent import run_context_refinement

            result = await run_context_refinement(
                "test", [], [{"id": "1"}], ["q"], api_key="k",
            )

    assert result == {"done": True}


# ---------------------------------------------------------------------------
# Model factory
# ---------------------------------------------------------------------------


def test_make_litellm_model_adds_prefix():
    """_make_litellm_model adds openai/ prefix to model names."""
    from backend.context_agent import _make_litellm_model

    m = _make_litellm_model(model="google/gemini-2.5-flash-lite", api_key="k")
    assert m.model == "openai/google/gemini-2.5-flash-lite"


def test_make_litellm_model_no_double_prefix():
    """_make_litellm_model does not double-prefix openai/ models."""
    from backend.context_agent import _make_litellm_model

    m = _make_litellm_model(model="openai/gpt-4o", api_key="k")
    assert m.model == "openai/gpt-4o"


def test_make_litellm_model_disable_thinking():
    """_make_litellm_model with disable_thinking passes extra kwargs to disable Gemini thinking.

    Regression test for: Gemini 2.5 Flash thought_signature error breaking chat
    when tools are used through OpenAI-compatible gateways.
    """
    from backend.context_agent import _make_litellm_model

    m = _make_litellm_model(
        model="google/gemini-2.5-flash", api_key="k", disable_thinking=True,
    )
    assert m.model == "openai/google/gemini-2.5-flash"
    # reasoning_effort and extra_body should be in _additional_args
    assert m._additional_args.get("reasoning_effort") == "none"
    extra_body = m._additional_args.get("extra_body", {})
    assert extra_body.get("generationConfig", {}).get("thinkingConfig", {}).get("thinkingBudget") == 0


def test_make_litellm_model_default_no_thinking_args():
    """_make_litellm_model without disable_thinking does not add thinking params."""
    from backend.context_agent import _make_litellm_model

    m = _make_litellm_model(model="google/gemini-2.5-flash-lite", api_key="k")
    assert "reasoning_effort" not in m._additional_args
    assert "extra_body" not in m._additional_args
