"""Interaction style preference endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import require_user
from ..interaction_style import (
    DIMENSIONS,
    analyze_chat_history,
    get_style_preferences,
    set_manual_override,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interaction-style", tags=["interaction-style"])


class StyleDimension(BaseModel):
    value: float
    learned_value: float
    manual_override: float | None
    sample_count: int


class StylePreferences(BaseModel):
    coaching_vs_consulting: StyleDimension
    verbosity: StyleDimension
    formality: StyleDimension


class StyleOverrideRequest(BaseModel):
    dimension: str
    value: float | None = Field(None, ge=0.0, le=1.0)


@router.get("", response_model=StylePreferences, summary="Get interaction style preferences")
def get_preferences(user_id: str = Depends(require_user)) -> StylePreferences:
    """Return current interaction style preferences (learned + overrides)."""
    prefs = get_style_preferences(user_id)
    return StylePreferences(**{dim: StyleDimension(**prefs[dim]) for dim in DIMENSIONS})


@router.put("", response_model=StylePreferences, summary="Set manual style override")
def update_preference(
    body: StyleOverrideRequest,
    user_id: str = Depends(require_user),
) -> StylePreferences:
    """Set or clear a manual override for a style dimension."""
    try:
        set_manual_override(user_id, body.dimension, body.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    prefs = get_style_preferences(user_id)
    return StylePreferences(**{dim: StyleDimension(**prefs[dim]) for dim in DIMENSIONS})


@router.post("/analyze", response_model=StylePreferences, summary="Analyze chat history for style")
def analyze_style(user_id: str = Depends(require_user)) -> StylePreferences:
    """Analyze recent chat history to update learned style preferences."""
    prefs = analyze_chat_history(user_id)
    return StylePreferences(**{dim: StyleDimension(**prefs[dim]) for dim in DIMENSIONS})
