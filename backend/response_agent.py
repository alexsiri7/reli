"""ADK LlmAgent-based response agent for the Reli chat pipeline.

Replaces the raw LiteLLM calls in agents.py with a Google ADK LlmAgent
backed by the LiteLlm connector routing through Requesty.  Preserves the same
public interface (``run_response_agent``, ``run_response_agent_stream``) so
callers in chat.py need only update their import path.

Streaming is implemented by iterating over partial ADK events and yielding
text chunks as they arrive.
"""

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from .agents import (
    REQUESTY_RESPONSE_MODEL,
    UsageStats,
    _build_response_messages,
    get_response_system_prompt,
)
from .context_agent import _make_litellm_model

logger = logging.getLogger(__name__)

# Module-level session service shared across calls (stateless — sessions are
# created per invocation and never reused).
_session_service = InMemorySessionService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_user_prompt(
    message: str,
    reasoning_summary: str,
    questions_for_user: list[str],
    applied_changes: dict[str, Any],
    web_results: list[dict[str, Any]] | None = None,
    open_questions_by_thing: dict[str, list[str]] | None = None,
    priority_question: str = "",
    briefing_mode: bool = False,
    interaction_style: str = "auto",
) -> str:
    """Build the user prompt content for the ADK agent.

    Reuses ``_build_response_messages`` from agents.py and extracts the user
    message content so the ADK LlmAgent receives it as its input.
    """
    messages = _build_response_messages(
        message,
        reasoning_summary,
        questions_for_user,
        applied_changes,
        web_results,
        open_questions_by_thing,
        priority_question=priority_question,
        briefing_mode=briefing_mode,
        interaction_style=interaction_style,
    )
    # The second message (index 1) is the user message with all context
    content: str = messages[1]["content"]
    return content


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
        app_name="reli_response",
        session_service=_session_service,
    )

    user_id = "response_pipeline"
    session_id = str(uuid.uuid4())

    session = await _session_service.create_session(
        app_name="reli_response",
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
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text and not event.partial:
                    text_parts.append(part.text)

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
            cost=0.0,
            model=model_name or "unknown",
        )

    return response_text


async def _run_agent_for_stream(
    agent: LlmAgent,
    user_message: str,
    usage_stats: UsageStats | None = None,
) -> AsyncIterator[str]:
    """Run an LlmAgent and yield text chunks as they stream in.

    Yields partial text events for real-time delivery, then accumulates
    usage from the final non-partial events.
    """
    runner = Runner(
        agent=agent,
        app_name="reli_response",
        session_service=_session_service,
    )

    user_id = "response_pipeline"
    session_id = str(uuid.uuid4())

    session = await _session_service.create_session(
        app_name="reli_response",
        user_id=user_id,
        session_id=session_id,
    )

    user_content = genai_types.Content(
        role="user",
        parts=[genai_types.Part.from_text(text=user_message)],
    )

    total_prompt = 0
    total_completion = 0
    total_tokens = 0
    model_name = ""

    # Track previously yielded text length to emit only new characters
    yielded_length = 0

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=user_content,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text and event.partial:
                    # Partial events contain the full accumulated text so far.
                    # Yield only the new portion since the last yield.
                    new_text = part.text[yielded_length:]
                    if new_text:
                        yield new_text
                        yielded_length = len(part.text)
                elif part.text and not event.partial:
                    # Final (non-partial) event — yield any remaining text
                    new_text = part.text[yielded_length:]
                    if new_text:
                        yield new_text
                    yielded_length = 0  # Reset for potential multi-turn

        if event.usage_metadata:
            um = event.usage_metadata
            total_prompt += um.prompt_token_count or 0
            total_completion += um.candidates_token_count or 0
            total_tokens += um.total_token_count or 0

        if event.model_version:
            model_name = event.model_version

    if usage_stats is not None and total_tokens > 0:
        usage_stats.accumulate(
            prompt=total_prompt,
            completion=total_completion,
            total=total_tokens,
            cost=0.0,
            model=model_name or "unknown",
        )


# ---------------------------------------------------------------------------
# Public API — drop-in replacements for agents.run_response_agent*
# ---------------------------------------------------------------------------


async def run_response_agent(
    message: str,
    reasoning_summary: str,
    questions_for_user: list[str],
    applied_changes: dict[str, Any],
    web_results: list[dict[str, Any]] | None = None,
    usage_stats: UsageStats | None = None,
    open_questions_by_thing: dict[str, list[str]] | None = None,
    api_key: str | None = None,
    model: str | None = None,
    priority_question: str = "",
    briefing_mode: bool = False,
    interaction_style: str = "auto",
) -> str:
    """Stage 4: generate friendly user-facing response via ADK LlmAgent."""
    user_prompt = _build_user_prompt(
        message,
        reasoning_summary,
        questions_for_user,
        applied_changes,
        web_results,
        open_questions_by_thing,
        priority_question=priority_question,
        briefing_mode=briefing_mode,
        interaction_style=interaction_style,
    )

    litellm_model = _make_litellm_model(
        model=model or REQUESTY_RESPONSE_MODEL,
        api_key=api_key,
    )

    response_agent = LlmAgent(
        name="response_agent",
        description="Generates friendly, conversational responses to the user.",
        model=litellm_model,
        instruction=get_response_system_prompt(interaction_style),
    )

    return await _run_agent_for_text(response_agent, user_prompt, usage_stats)


async def run_response_agent_stream(
    message: str,
    reasoning_summary: str,
    questions_for_user: list[str],
    applied_changes: dict[str, Any],
    web_results: list[dict[str, Any]] | None = None,
    usage_stats: UsageStats | None = None,
    open_questions_by_thing: dict[str, list[str]] | None = None,
    api_key: str | None = None,
    model: str | None = None,
    priority_question: str = "",
    briefing_mode: bool = False,
    interaction_style: str = "auto",
) -> AsyncIterator[str]:
    """Stage 4 (streaming): yield response tokens as they arrive via ADK LlmAgent."""
    user_prompt = _build_user_prompt(
        message,
        reasoning_summary,
        questions_for_user,
        applied_changes,
        web_results,
        open_questions_by_thing,
        priority_question=priority_question,
        briefing_mode=briefing_mode,
        interaction_style=interaction_style,
    )

    litellm_model = _make_litellm_model(
        model=model or REQUESTY_RESPONSE_MODEL,
        api_key=api_key,
    )

    response_agent = LlmAgent(
        name="response_agent",
        description="Generates friendly, conversational responses to the user.",
        model=litellm_model,
        instruction=get_response_system_prompt(interaction_style),
    )

    async for token in _run_agent_for_stream(response_agent, user_prompt, usage_stats):
        yield token
