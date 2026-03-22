"""ADK agent module for preference detection eval — exports ``root_agent``.

Preference detection evals test the reasoning agent's ability to identify
and store user preferences (both explicit statements and inferred behavioral
patterns).  The agent is identical to the reasoning agent eval — same stub
tools, same system prompt — because preference detection is a reasoning-agent
capability, not a separate agent.
"""

from eval.reasoning_agent.agent import root_agent  # noqa: F401

__all__ = ["root_agent"]
