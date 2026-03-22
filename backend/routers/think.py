"""Think endpoint — reasoning-as-a-service for MCP clients.

Accepts natural language, runs the reasoning agent in instruction-only mode,
and returns structured instructions (create/update/delete/link) without
executing them. The calling agent executes the instructions via CRUD tools.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import require_user
from ..reasoning_agent import run_think_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/think", tags=["think"])


class ThinkRequest(BaseModel):
    """Request body for the /think endpoint."""

    message: str = Field(..., min_length=1, description="Natural language message to reason about.")
    context: str = Field(default="", description="Optional additional context from the calling agent.")


class ThinkResponse(BaseModel):
    """Structured instructions returned by the think agent."""

    instructions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of action dicts: {action, params, ref?}",
    )
    questions_for_user: list[str] = Field(
        default_factory=list,
        description="Clarifying questions if intent is ambiguous.",
    )
    reasoning_summary: str = Field(
        default="",
        description="Brief explanation of the reasoning and plan.",
    )
    context: dict[str, Any] | None = Field(
        default=None,
        description="Things found during analysis (for reference).",
    )


@router.post("", response_model=ThinkResponse)
async def think(
    body: ThinkRequest,
    user_id: str = Depends(require_user),
) -> dict[str, Any]:
    """Analyze a natural language message and return structured instructions.

    This is the reasoning-as-a-service endpoint. It runs the reasoning agent
    in read-only mode: it searches the knowledge graph for context, then
    returns a plan of what should be created, updated, deleted, or linked.
    The calling agent executes the plan via CRUD endpoints.
    """
    result = await run_think_agent(
        message=body.message,
        context=body.context,
        user_id=user_id,
    )
    return result
