"""Tests for the LiteLLM connector routing through Requesty."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.llm import REQUESTY_BASE_URL, acomplete, acomplete_stream


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_response(content: str = "hello", model: str = "google/gemini-2.5-flash-lite"):
    """Build a minimal mock response matching LiteLLM's ModelResponse shape."""
    choice = MagicMock()
    choice.message.content = content
    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5
    usage.total_tokens = 15
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    resp.model = model
    return resp


def _fake_chunk(content: str | None = None, *, usage: bool = False):
    """Build a minimal streaming chunk."""
    chunk = MagicMock()
    if content is not None:
        delta = MagicMock()
        delta.content = content
        choice = MagicMock()
        choice.delta = delta
        chunk.choices = [choice]
    else:
        chunk.choices = []
    if usage:
        u = MagicMock()
        u.prompt_tokens = 10
        u.completion_tokens = 5
        u.total_tokens = 15
        chunk.usage = u
    else:
        chunk.usage = None
    return chunk


# ---------------------------------------------------------------------------
# acomplete — non-streaming round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acomplete_routes_through_requesty():
    """acomplete passes the model with openai/ prefix and Requesty base_url."""
    mock_resp = _fake_response("test reply")

    with patch("backend.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp) as mock_call:
        result = await acomplete(
            [{"role": "user", "content": "hi"}],
            "google/gemini-2.5-flash-lite",
            api_key="test-key",
        )

    mock_call.assert_called_once()
    call_kwargs = mock_call.call_args
    assert call_kwargs.kwargs["model"] == "openai/google/gemini-2.5-flash-lite"
    assert call_kwargs.kwargs["api_base"] == REQUESTY_BASE_URL
    assert call_kwargs.kwargs["api_key"] == "test-key"
    assert result.choices[0].message.content == "test reply"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    [
        "google/gemini-2.5-flash-lite",
        "google/gemini-3-flash-preview",
    ],
)
async def test_acomplete_all_model_configs(model: str):
    """All three configured models (context, reasoning, response) route correctly."""
    mock_resp = _fake_response("ok", model=model)

    with patch("backend.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp) as mock_call:
        result = await acomplete(
            [{"role": "user", "content": "test"}],
            model,
        )

    assert mock_call.call_args.kwargs["model"] == f"openai/{model}"
    assert result.choices[0].message.content == "ok"


# ---------------------------------------------------------------------------
# acomplete_stream — streaming round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acomplete_stream_yields_chunks():
    """acomplete_stream yields chunks from the LiteLLM streaming response."""
    chunks = [
        _fake_chunk("Hello"),
        _fake_chunk(" world"),
        _fake_chunk(None, usage=True),
    ]

    async def _fake_stream(*args, **kwargs):
        for c in chunks:
            yield c

    with patch("backend.llm.litellm.acompletion", new_callable=AsyncMock, return_value=_fake_stream()):
        collected = []
        async for chunk in acomplete_stream(
            [{"role": "user", "content": "hi"}],
            "google/gemini-2.5-flash-lite",
        ):
            collected.append(chunk)

    assert len(collected) == 3


# ---------------------------------------------------------------------------
# Integration with agents._chat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agents_chat_uses_litellm():
    """agents._chat delegates to the LiteLLM acomplete function."""
    mock_resp = _fake_response("agent reply")

    with patch("backend.agents.acomplete", new_callable=AsyncMock, return_value=mock_resp):
        from backend.agents import _chat

        result = await _chat(
            [{"role": "user", "content": "hello"}],
            model="google/gemini-2.5-flash-lite",
        )

    assert result == "agent reply"


# ---------------------------------------------------------------------------
# Per-user model override preserved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_user_model_override():
    """Per-user model and API key overrides reach the LiteLLM layer."""
    mock_resp = _fake_response("custom model reply")

    with patch("backend.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp) as mock_call:
        result = await acomplete(
            [{"role": "user", "content": "test"}],
            "custom/user-model",
            api_key="user-personal-key",
        )

    call_kwargs = mock_call.call_args.kwargs
    assert call_kwargs["model"] == "openai/custom/user-model"
    assert call_kwargs["api_key"] == "user-personal-key"
    assert result.choices[0].message.content == "custom model reply"
