"""ADK agent module for context agent eval — exports ``root_agent``.

The context agent is a pure text agent (no tool calling) that generates
JSON with search_queries and filter_params. For eval, we construct a
standalone LlmAgent with the same system prompt.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types as genai_types

from backend.agents import CONTEXT_AGENT_SYSTEM
from eval._eval_model import make_eval_model, make_eval_model_by_name

model = make_eval_model("context")

root_agent = LlmAgent(
    name="context_agent",
    description="Generates search parameters to find relevant Things in the database.",
    model=model,
    instruction=CONTEXT_AGENT_SYSTEM,
    generate_content_config=genai_types.GenerateContentConfig(
        response_mime_type="application/json",
    ),
)


def build_agent(model_name: str) -> LlmAgent:
    """Build the context agent with a specific model name (for model comparison)."""
    return LlmAgent(
        name="context_agent",
        description="Generates search parameters to find relevant Things in the database.",
        model=make_eval_model_by_name(model_name),
        instruction=CONTEXT_AGENT_SYSTEM,
        generate_content_config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
