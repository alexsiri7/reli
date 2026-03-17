"""LiteLLM-based model wrapper routing through Requesty.

Provides ``acomplete`` and ``acomplete_stream`` as drop-in replacements for
the raw AsyncOpenAI calls previously used in agents.py.  All requests go through
Requesty (``https://router.requesty.ai/v1``) via LiteLLM's ``openai/`` provider
prefix, which gives us unified error handling, retry logic, and provider routing.
"""

import logging
from collections.abc import AsyncIterator
from typing import Any

import litellm

from .config import settings

logger = logging.getLogger(__name__)

# Silence LiteLLM's noisy default logging
litellm.suppress_debug_info = True

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REQUESTY_BASE_URL: str = settings.REQUESTY_BASE_URL or "https://router.requesty.ai/v1"
REQUESTY_API_KEY: str = settings.REQUESTY_API_KEY


def _litellm_model(model: str) -> str:
    """Prefix model name for LiteLLM's OpenAI-compatible provider.

    Requesty exposes an OpenAI-compatible API, so we tell LiteLLM to use the
    ``openai/`` provider.  If the model already has an ``openai/`` prefix we
    leave it alone.
    """
    if model.startswith("openai/"):
        return model
    return f"openai/{model}"


# ---------------------------------------------------------------------------
# Core completion helpers
# ---------------------------------------------------------------------------


async def acomplete(
    messages: list[dict[str, Any]],
    model: str,
    *,
    api_key: str | None = None,
    **kwargs: Any,
) -> Any:
    """Non-streaming LLM completion via Requesty.

    Returns a ``litellm.ModelResponse`` (typed as Any to avoid mypy issues with
    LiteLLM's dynamic return types).  Callers can access ``.choices``, ``.usage``,
    and ``.model`` as usual.
    """
    return await litellm.acompletion(
        model=_litellm_model(model),
        messages=messages,
        api_key=api_key or REQUESTY_API_KEY,
        api_base=REQUESTY_BASE_URL,
        **kwargs,
    )


async def acomplete_stream(
    messages: list[dict[str, Any]],
    model: str,
    *,
    api_key: str | None = None,
    **kwargs: Any,
) -> AsyncIterator[Any]:
    """Streaming LLM completion via Requesty.

    Yields ``litellm`` chunk objects (same shape as OpenAI streaming chunks).
    """
    response = await litellm.acompletion(
        model=_litellm_model(model),
        messages=messages,
        api_key=api_key or REQUESTY_API_KEY,
        api_base=REQUESTY_BASE_URL,
        stream=True,
        stream_options={"include_usage": True},
        **kwargs,
    )
    async for chunk in response:
        yield chunk
