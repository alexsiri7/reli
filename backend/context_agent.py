"""ADK LlmAgent-based context agent for the Reli chat pipeline.

Replaces the raw OpenAI/LiteLLM calls in agents.py with a Google ADK LlmAgent
backed by the LiteLlm connector routing through Requesty.  Preserves the same
public interface (``run_context_agent``, ``run_context_refinement``) so callers
in chat.py need only update their import path.
"""

import json
import logging
import re
import uuid
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from .agents import (
    CONTEXT_AGENT_SYSTEM,
    CONTEXT_REFINEMENT_SYSTEM,
    OLLAMA_MODEL,
    REQUESTY_API_KEY,
    _with_current_date,
    REQUESTY_BASE_URL,
    REQUESTY_MODEL,
    UsageStats,
    _chat_ollama,
    _with_current_date,
)

logger = logging.getLogger(__name__)

# Pattern to match markdown code fences wrapping JSON:  ```json\n...\n```
_MARKDOWN_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences if the model wrapped its JSON output in them."""
    m = _MARKDOWN_FENCE_RE.match(text.strip())
    return m.group(1) if m else text


# ---------------------------------------------------------------------------
# Model factory
# ---------------------------------------------------------------------------


# Gemini model names that are known "thinking" models requiring
# thought_signature handling.  The openai/ routing through Requesty
# does NOT preserve thought_signatures, so these models will fail
# on multi-step tool calls.  See GH #176.
_GEMINI_THINKING_MODELS = frozenset({
    "gemini-3-flash-preview",
    "gemini-3-flash",
    "gemini-2.5-pro-preview",
    "gemini-2.5-flash-thinking",
})


def _is_thinking_model(model_name: str) -> bool:
    """Return True if *model_name* is a Gemini thinking model."""
    # Strip provider prefixes like "google/" or "openai/google/"
    base = model_name.rsplit("/", 1)[-1]
    return base in _GEMINI_THINKING_MODELS


def _make_litellm_model(
    model: str | None = None,
    api_key: str | None = None,
    **kwargs: Any,
) -> LiteLlm:
    """Create a LiteLlm model instance configured for Requesty.

    Extra kwargs are forwarded to the LiteLlm constructor and ultimately to
    litellm's completion call (e.g. ``extra_body`` for provider-specific params).

    Warning: Gemini thinking models (e.g. gemini-3-flash-preview) require
    thought_signature preservation which is NOT supported when routing
    through the openai/ prefix to Requesty.  Multi-step tool calls will
    fail with 400 errors.  Use a non-thinking model for tool-calling agents.
    """
    effective_model = model or REQUESTY_MODEL
    if _is_thinking_model(effective_model):
        logger.warning(
            "Model %s is a Gemini thinking model — multi-step tool calls "
            "may fail with thought_signature errors when routed through "
            "the openai/ prefix. Consider using a non-thinking model "
            "like google/gemini-2.5-flash. See GH #176.",
            effective_model,
        )
    # LiteLlm expects the openai/ prefix for OpenAI-compatible providers
    if not effective_model.startswith("openai/"):
        effective_model = f"openai/{effective_model}"
    return LiteLlm(
        model=effective_model,
        api_key=api_key or REQUESTY_API_KEY,
        api_base=REQUESTY_BASE_URL,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Helpers — run an LlmAgent and extract text + usage
# ---------------------------------------------------------------------------

# Module-level session service shared across calls (stateless — sessions are
# created per invocation and never reused).
_session_service = InMemorySessionService()


async def _run_agent_for_text(
    agent: LlmAgent,
    user_message: str,
    usage_stats: UsageStats | None = None,
) -> str:
    """Run an LlmAgent and return the concatenated text response.

    Creates a throwaway Runner / session for each call so there is no shared
    mutable state between pipeline invocations.
    """
    runner = Runner(
        agent=agent,
        app_name="reli_context",
        session_service=_session_service,
    )

    user_id = "context_pipeline"
    session_id = str(uuid.uuid4())

    session = await _session_service.create_session(
        app_name="reli_context",
        user_id=user_id,
        session_id=session_id,
    )

    user_content = genai_types.Content(
        role="user",
        parts=[genai_types.Part.from_text(text=user_message)],
    )

    text_parts: list[str] = []
    total_prompt = 0
    total_completion = 0
    total_tokens = 0
    model_name = ""

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=user_content,
    ):
        # Collect text from non-partial model events
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text and not event.partial:
                    text_parts.append(part.text)

        # Accumulate usage metadata
        if event.usage_metadata:
            um = event.usage_metadata
            total_prompt += um.prompt_token_count or 0
            total_completion += um.candidates_token_count or 0
            total_tokens += um.total_token_count or 0

        if event.model_version:
            model_name = event.model_version

    response_text = "".join(text_parts)

    if usage_stats is not None and total_tokens > 0:
        usage_stats.accumulate(
            prompt=total_prompt,
            completion=total_completion,
            total=total_tokens,
            cost=0.0,  # LiteLlm/ADK doesn't provide cost directly
            model=model_name or "unknown",
        )

    return response_text


# ---------------------------------------------------------------------------
# Public API — drop-in replacements for agents.run_context_agent/refinement
# ---------------------------------------------------------------------------


async def run_context_agent(
    message: str,
    history: list[dict[str, Any]],
    usage_stats: UsageStats | None = None,
    context_window: int = 10,
    api_key: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Stage 1: decide what to search for.

    Uses local Ollama when OLLAMA_MODEL is configured, with graceful fallback
    to Requesty via ADK LlmAgent.
    """
    # Build the user message that includes conversation history context
    history_block = ""
    for h in history[-context_window:]:
        history_block += f"<{h['role']}>{h['content']}</{h['role']}>\n"

    user_prompt = (
        (f"Conversation history:\n{history_block}\nCurrent user message: {message}") if history_block else message
    )

    raw = None

    # Try Ollama first if configured (unchanged — Ollama doesn't use ADK)
    if OLLAMA_MODEL:
        try:
            messages = [{"role": "system", "content": _with_current_date(CONTEXT_AGENT_SYSTEM)}]
            for h in history[-context_window:]:
                messages.append({"role": h["role"], "content": h["content"]})
            messages.append({"role": "user", "content": message})
            raw = await _chat_ollama(
                messages,
                response_format={"type": "json_object"},
                usage_stats=usage_stats,
            )
            logger.info(
                "Context agent (Ollama/%s) raw response: %s",
                OLLAMA_MODEL,
                raw[:500] if raw else raw,
            )
        except Exception as exc:
            logger.warning(
                "Ollama context agent failed, falling back to ADK/Requesty: %s",
                exc,
            )

    # Fall back to ADK LlmAgent via Requesty
    if raw is None:
        litellm_model = _make_litellm_model(model=model, api_key=api_key)

        context_agent = LlmAgent(
            name="context_agent",
            description="Generates search parameters to find relevant Things in the database.",
            model=litellm_model,
            instruction=_with_current_date(CONTEXT_AGENT_SYSTEM),
            generate_content_config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )

        raw = await _run_agent_for_text(context_agent, user_prompt, usage_stats)
        logger.info(
            "Context agent (ADK/Requesty/%s) raw response: %s",
            model or REQUESTY_MODEL,
            raw[:500] if raw else raw,
        )

    try:
        result: dict[str, Any] = json.loads(_strip_markdown_fences(raw))
        logger.info(
            "Context agent parsed — search_queries=%r, filter_params=%r",
            result.get("search_queries"),
            result.get("filter_params"),
        )
        return result
    except json.JSONDecodeError:
        logger.warning(
            "Context agent returned invalid JSON, falling back to message as query: %s",
            raw[:200] if raw else raw,
        )
        return {
            "search_queries": [message],
            "filter_params": {"active_only": True, "type_hint": None},
        }


async def run_context_refinement(
    message: str,
    history: list[dict[str, Any]],
    found_things: list[dict[str, Any]],
    previous_queries: list[str],
    relationships: list[dict[str, Any]] | None = None,
    usage_stats: UsageStats | None = None,
    context_window: int = 10,
    api_key: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Ask the context agent if it needs more searches given what was found."""
    things_summary = json.dumps(
        [
            {
                "id": t.get("id"),
                "title": t.get("title"),
                "type_hint": t.get("type_hint"),
                "data": t.get("data"),
                "parent_id": t.get("parent_id"),
                "active": t.get("active"),
                "open_questions": t.get("open_questions"),
            }
            for t in found_things
        ],
        default=str,
    )

    rels_section = ""
    if relationships:
        rels_section = f"\n\nRelationships between Things:\n{json.dumps(relationships, default=str)}\n"

    refinement_prompt = (
        f"User's message: {message}\n\n"
        f"Previous search queries: {json.dumps(previous_queries)}\n\n"
        f"Things found so far ({len(found_things)} results):\n{things_summary}"
        f"{rels_section}\n\n"
        f"Do you have enough context to understand the user's request, "
        f"or do you need to search for more?"
    )

    # Include conversation history context
    history_block = ""
    for h in history[-context_window:]:
        history_block += f"<{h['role']}>{h['content']}</{h['role']}>\n"

    if history_block:
        full_prompt = f"Conversation history:\n{history_block}\n{refinement_prompt}"
    else:
        full_prompt = refinement_prompt

    raw = None

    # Try Ollama first if configured
    if OLLAMA_MODEL:
        try:
            messages = [{"role": "system", "content": _with_current_date(CONTEXT_REFINEMENT_SYSTEM)}]
            for h in history[-context_window:]:
                messages.append({"role": h["role"], "content": h["content"]})
            messages.append({"role": "user", "content": refinement_prompt})
            raw = await _chat_ollama(
                messages,
                response_format={"type": "json_object"},
                usage_stats=usage_stats,
            )
        except Exception:
            pass

    # Fall back to ADK LlmAgent
    if raw is None:
        litellm_model = _make_litellm_model(model=model, api_key=api_key)

        refinement_agent = LlmAgent(
            name="context_refinement_agent",
            description="Decides if more context searches are needed.",
            model=litellm_model,
            instruction=_with_current_date(CONTEXT_REFINEMENT_SYSTEM),
            generate_content_config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )

        raw = await _run_agent_for_text(refinement_agent, full_prompt, usage_stats)

    logger.info(
        "Context refinement raw response: %s",
        raw[:500] if raw else raw,
    )

    try:
        result: dict[str, Any] = json.loads(_strip_markdown_fences(raw))
        return result
    except json.JSONDecodeError:
        return {"done": True}
