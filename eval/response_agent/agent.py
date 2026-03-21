"""ADK agent module for response agent eval — exports ``root_agent``.

The response agent is a pure text agent (no tool calling) that generates
friendly, conversational responses given a reasoning summary and applied
changes.  For eval, we construct a standalone LlmAgent with the same system
prompt used in production.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from backend.agents import get_response_system_prompt
from backend.context_agent import _make_litellm_model

model = _make_litellm_model()

root_agent = LlmAgent(
    name="response_agent",
    description="Generates friendly, conversational responses to the user.",
    model=model,
    instruction=get_response_system_prompt("auto"),
)
