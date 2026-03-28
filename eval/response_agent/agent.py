"""ADK LlmAgent wrapper for response agent eval.

The response agent is a text-only agent (no tool calls) that generates a
friendly conversational response given user message, reasoning summary, and
applied changes.

For evals we bypass ``load_personality_preferences`` (which reads from DB) and
instead accept personality_patterns directly.  ``root_agent`` uses the default
auto interaction style with no personality overrides.
"""

from __future__ import annotations

from typing import Any

from google.adk.agents import LlmAgent

from backend.agents import get_response_system_prompt
from eval._eval_model import make_eval_model


def build_agent(
    interaction_style: str = "auto",
    personality_patterns: list[dict[str, Any]] | None = None,
) -> LlmAgent:
    """Build the response agent for eval with optional personality patterns."""
    return LlmAgent(
        name="response_agent",
        description="Generates friendly, conversational responses to the user.",
        model=make_eval_model("response"),
        instruction=get_response_system_prompt(interaction_style, personality_patterns or []),
    )


root_agent = build_agent()
