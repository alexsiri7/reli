"""Conflict detection API — surface blockers, deadline conflicts, and schedule overlaps."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..auth import require_user
from ..conflict_detection import detect_conflicts
from .settings import get_user_setting

router = APIRouter(prefix="/conflicts", tags=["conflicts"])


class ConflictResponse(BaseModel):
    conflict_type: str
    message: str
    priority: int
    thing_id: str | None = None
    thing_title: str | None = None
    blocker_id: str | None = None
    blocker_title: str | None = None
    details: dict = {}


@router.get("", response_model=list[ConflictResponse], summary="Detected conflicts")
def get_conflicts(
    proactivity: str | None = Query(
        None,
        description="Override proactivity level (low/medium/high)",
        pattern="^(low|medium|high)$",
    ),
    user_id: str = Depends(require_user),
) -> list[ConflictResponse]:
    """Return detected blockers and conflicts for the current user."""
    level = proactivity
    if not level:
        level = get_user_setting(user_id, "proactivity_level") or "medium"

    conflicts = detect_conflicts(user_id=user_id, proactivity=level)
    return [
        ConflictResponse(**c.to_dict())
        for c in conflicts
    ]
