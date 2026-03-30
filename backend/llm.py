"""LiteLLM-based model wrapper routing through Requesty.

Provides ``acomplete`` and ``acomplete_stream`` as drop-in replacements for
the raw AsyncOpenAI calls previously used in agents.py.  All requests go through
Requesty (``https://router.requesty.ai/v1``) via LiteLLM's ``openai/`` provider
prefix, which gives us unified error handling, retry logic, and provider routing.
"""

import asyncio
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

# ---------------------------------------------------------------------------
# Retry config for transient errors (404, 429, 503)
# ---------------------------------------------------------------------------

_RETRY_MAX_ATTEMPTS: int = 4
_RETRY_BASE_DELAY: float = 0.5  # seconds
_RETRY_MAX_DELAY: float = 8.0  # seconds

# Errors worth retrying: transient 404s (Gemini/Vertex AI), 429 rate limits,
# and 503 service unavailable.
_RETRYABLE_ERRORS = (litellm.NotFoundError, litellm.RateLimitError, litellm.ServiceUnavailableError)


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

    Retries with exponential backoff on transient errors: 404 (Gemini/Vertex AI),
    429 (rate limit), and 503 (service unavailable).
    """
    last_exc: Exception | None = None
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            return await litellm.acompletion(
                model=_litellm_model(model),
                messages=messages,
                api_key=api_key or REQUESTY_API_KEY,
                api_base=REQUESTY_BASE_URL,
                **kwargs,
            )
        except _RETRYABLE_ERRORS as exc:
            last_exc = exc
            if attempt < _RETRY_MAX_ATTEMPTS - 1:
                delay = min(_RETRY_BASE_DELAY * (2**attempt), _RETRY_MAX_DELAY)
                logger.warning(
                    "LiteLLM %s on attempt %d/%d for model %s, retrying in %.1fs",
                    type(exc).__name__,
                    attempt + 1,
                    _RETRY_MAX_ATTEMPTS,
                    model,
                    delay,
                )
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


async def acomplete_stream(
    messages: list[dict[str, Any]],
    model: str,
    *,
    api_key: str | None = None,
    **kwargs: Any,
) -> AsyncIterator[Any]:
    """Streaming LLM completion via Requesty.

    Yields ``litellm`` chunk objects (same shape as OpenAI streaming chunks).

    Retries with exponential backoff on transient errors: 404 (Gemini/Vertex AI),
    429 (rate limit), and 503 (service unavailable).
    """
    last_exc: Exception | None = None
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
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
            return
        except _RETRYABLE_ERRORS as exc:
            last_exc = exc
            if attempt < _RETRY_MAX_ATTEMPTS - 1:
                delay = min(_RETRY_BASE_DELAY * (2**attempt), _RETRY_MAX_DELAY)
                logger.warning(
                    "LiteLLM %s on attempt %d/%d for model %s (stream), retrying in %.1fs",
                    type(exc).__name__,
                    attempt + 1,
                    _RETRY_MAX_ATTEMPTS,
                    model,
                    delay,
                )
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]
