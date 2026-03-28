"""ADK agent module for eval — exports ``root_agent`` (or ``get_agent_async``).

The ADK ``AgentEvaluator`` loads the agent from this module by looking for
either ``root_agent`` (a module-level LlmAgent) or ``get_agent_async``
(an async factory).

For evals we construct a *mock-tool* variant of the reasoning agent: the
tools have the same names and signatures as production, but they don't
touch the database — they return canned responses.  This lets us evaluate
the LLM's *tool selection and argument quality* without side effects.
"""

from __future__ import annotations

from typing import Any

from google.adk.agents import LlmAgent

from backend.context_agent import _make_litellm_model
from backend.reasoning_agent import REASONING_AGENT_TOOL_SYSTEM
from eval._eval_model import make_eval_model, make_eval_model_by_name

# ---------------------------------------------------------------------------
# Stub tools — same signatures as production, but no DB
# ---------------------------------------------------------------------------

_NEXT_ID = 0


def _fresh_id() -> str:
    global _NEXT_ID
    _NEXT_ID += 1
    return f"eval-thing-{_NEXT_ID:04d}"


def fetch_context(
    search_queries_json: str = "[]",
    fetch_ids_json: str = "[]",
    active_only: bool = True,
    type_hint: str = "",
) -> dict[str, Any]:
    """Search the Things database for relevant context (eval stub)."""
    return {"things": [], "relationships": [], "count": 0}


def create_thing(
    title: str,
    type_hint: str = "",
    priority: int = 3,
    checkin_date: str = "",
    surface: bool = True,
    data_json: str = "{}",
    open_questions_json: str = "[]",
) -> dict[str, Any]:
    """Create a new Thing in the database (eval stub)."""
    return {"id": _fresh_id(), "title": title, "type_hint": type_hint}


def update_thing(
    thing_id: str,
    title: str = "",
    active: bool | None = None,
    checkin_date: str = "",
    priority: int | None = None,
    type_hint: str = "",
    surface: bool | None = None,
    data_json: str = "",
    open_questions_json: str = "",
) -> dict[str, Any]:
    """Update an existing Thing's fields (eval stub)."""
    return {"id": thing_id, "title": title or "updated"}


def delete_thing(thing_id: str) -> dict[str, Any]:
    """Delete a Thing by ID (eval stub)."""
    return {"deleted": thing_id}


def merge_things(
    keep_id: str,
    remove_id: str,
    merged_data_json: str = "{}",
) -> dict[str, Any]:
    """Merge a duplicate Thing into a primary Thing (eval stub)."""
    return {"keep_id": keep_id, "remove_id": remove_id}


def create_relationship(
    from_thing_id: str,
    to_thing_id: str,
    relationship_type: str,
) -> dict[str, Any]:
    """Create a typed relationship link between two Things (eval stub)."""
    return {
        "from_thing_id": from_thing_id,
        "to_thing_id": to_thing_id,
        "relationship_type": relationship_type,
    }


def chat_history(
    n: int = 10,
    search_query: str = "",
) -> dict[str, Any]:
    """Retrieve older messages from the current conversation (eval stub)."""
    return {"messages": [], "count": 0}


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------


_STUB_TOOLS = [
    fetch_context,
    create_thing,
    update_thing,
    delete_thing,
    merge_things,
    create_relationship,
    chat_history,
]


def _build_agent() -> LlmAgent:
    """Build the reasoning agent wired with stub tools."""
    model = make_eval_model("reasoning")
    return LlmAgent(
        name="reasoning_agent",
        description="Reasoning agent for Reli — decides storage changes via tool calls.",
        model=model,
        instruction=REASONING_AGENT_TOOL_SYSTEM,
        tools=_STUB_TOOLS,
    )


def build_agent(model_name: str) -> LlmAgent:
    """Build the reasoning agent with a specific model name (for model comparison)."""
    model = make_eval_model_by_name(model_name)
    return LlmAgent(
        name="reasoning_agent",
        description="Reasoning agent for Reli — decides storage changes via tool calls.",
        model=model,
        instruction=REASONING_AGENT_TOOL_SYSTEM,
        tools=_STUB_TOOLS,
    )


root_agent = _build_agent()
