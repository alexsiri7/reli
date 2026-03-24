"""Tests for the LiteLLM connector routing through Requesty."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import litellm
import pytest

from backend.llm import (
    _RETRY_MAX_ATTEMPTS,
    REQUESTY_BASE_URL,
    acomplete,
    acomplete_stream,
)

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
        "google/gemini-2.5-flash",
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


# ---------------------------------------------------------------------------
# Retry on 404 (transient Gemini/Vertex AI errors)
# ---------------------------------------------------------------------------


def _make_not_found_error() -> litellm.NotFoundError:
    """Create a litellm.NotFoundError for testing."""
    return litellm.NotFoundError(
        message="Model not found",
        model="google/gemini-2.5-flash-lite",
        llm_provider="openai",
    )


@pytest.mark.asyncio
async def test_acomplete_retries_on_404_then_succeeds():
    """acomplete retries transient 404s and returns on success."""
    mock_resp = _fake_response("recovered")
    mock_call = AsyncMock(side_effect=[_make_not_found_error(), _make_not_found_error(), mock_resp])

    with (
        patch("backend.llm.litellm.acompletion", mock_call),
        patch("backend.llm.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await acomplete(
            [{"role": "user", "content": "hi"}],
            "google/gemini-2.5-flash-lite",
        )

    assert result.choices[0].message.content == "recovered"
    assert mock_call.call_count == 3


@pytest.mark.asyncio
async def test_acomplete_raises_after_max_retries():
    """acomplete raises NotFoundError after exhausting all retries."""
    mock_call = AsyncMock(side_effect=[_make_not_found_error()] * _RETRY_MAX_ATTEMPTS)

    with (
        patch("backend.llm.litellm.acompletion", mock_call),
        patch("backend.llm.asyncio.sleep", new_callable=AsyncMock),
    ):
        with pytest.raises(litellm.NotFoundError):
            await acomplete(
                [{"role": "user", "content": "hi"}],
                "google/gemini-2.5-flash-lite",
            )

    assert mock_call.call_count == _RETRY_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_acomplete_does_not_retry_other_errors():
    """acomplete does not retry non-404 errors."""
    mock_call = AsyncMock(
        side_effect=litellm.BadRequestError(
            message="Bad request",
            model="google/gemini-2.5-flash-lite",
            llm_provider="openai",
        )
    )

    with (
        patch("backend.llm.litellm.acompletion", mock_call),
        patch("backend.llm.asyncio.sleep", new_callable=AsyncMock),
    ):
        with pytest.raises(litellm.BadRequestError):
            await acomplete(
                [{"role": "user", "content": "hi"}],
                "google/gemini-2.5-flash-lite",
            )

    assert mock_call.call_count == 1


@pytest.mark.asyncio
async def test_acomplete_stream_retries_on_404_then_succeeds():
    """acomplete_stream retries transient 404s and yields chunks on success."""
    chunks = [_fake_chunk("Hello"), _fake_chunk(" world")]

    async def _fake_stream(*args, **kwargs):
        for c in chunks:
            yield c

    call_count = 0

    async def _mock_acompletion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise _make_not_found_error()
        return _fake_stream()

    with (
        patch("backend.llm.litellm.acompletion", side_effect=_mock_acompletion),
        patch("backend.llm.asyncio.sleep", new_callable=AsyncMock),
    ):
        collected = []
        async for chunk in acomplete_stream(
            [{"role": "user", "content": "hi"}],
            "google/gemini-2.5-flash-lite",
        ):
            collected.append(chunk)

    assert len(collected) == 2
    assert call_count == 3


@pytest.mark.asyncio
async def test_acomplete_retry_uses_exponential_backoff():
    """acomplete uses exponential backoff delays between retries."""
    mock_resp = _fake_response("ok")
    mock_call = AsyncMock(side_effect=[_make_not_found_error(), _make_not_found_error(), mock_resp])
    mock_sleep = AsyncMock()

    with patch("backend.llm.litellm.acompletion", mock_call), patch("backend.llm.asyncio.sleep", mock_sleep):
        await acomplete(
            [{"role": "user", "content": "hi"}],
            "google/gemini-2.5-flash-lite",
        )

    assert mock_sleep.call_count == 2
    # First retry: 0.5s, second retry: 1.0s
    assert mock_sleep.call_args_list[0].args[0] == pytest.approx(0.5)
    assert mock_sleep.call_args_list[1].args[0] == pytest.approx(1.0)
