"""Pydantic models for request/response validation."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ── Things ────────────────────────────────────────────────────────────────────


class ThingCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    type_hint: str | None = None
    parent_id: str | None = None
    checkin_date: datetime | None = None
    priority: int = Field(default=3, ge=1, le=5)
    active: bool = True
    surface: bool = True
    data: dict[str, Any] | None = None


class ThingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    type_hint: str | None = None
    parent_id: str | None = None
    checkin_date: datetime | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    active: bool | None = None
    surface: bool | None = None
    data: dict[str, Any] | None = None


class Thing(BaseModel):
    id: str
    title: str
    type_hint: str | None
    parent_id: str | None
    checkin_date: datetime | None
    priority: int
    active: bool
    surface: bool
    data: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    last_referenced: datetime | None = None
    children_count: int | None = None
    completed_count: int | None = None

    model_config = {"from_attributes": True}


# ── Relationships ────────────────────────────────────────────────────────────


class RelationshipCreate(BaseModel):
    from_thing_id: str
    to_thing_id: str
    relationship_type: str = Field(..., min_length=1, max_length=100)
    metadata: dict[str, Any] | None = None


class Relationship(BaseModel):
    id: str
    from_thing_id: str
    to_thing_id: str
    relationship_type: str
    metadata: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Chat ──────────────────────────────────────────────────────────────────────


class ChatMessageCreate(BaseModel):
    session_id: str = Field(..., min_length=1)
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)
    applied_changes: dict[str, Any] | None = None


class ChatMessage(BaseModel):
    id: int
    session_id: str
    role: str
    content: str
    applied_changes: dict[str, Any] | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    model: str | None = None
    timestamp: datetime

    model_config = {"from_attributes": True}


# ── Chat Pipeline ─────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    api_calls: int = 0
    model: str = ""


class ModelUsage(BaseModel):
    """Per-model usage breakdown."""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    api_calls: int = 0


class SessionUsage(BaseModel):
    """Cumulative usage stats for the current session."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    api_calls: int = 0
    per_model: list[ModelUsage] = []


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    applied_changes: dict[str, Any]
    questions_for_user: list[str]
    usage: UsageInfo | None = None
    session_usage: SessionUsage | None = None


# ── Briefing ──────────────────────────────────────────────────────────────────


class BriefingResponse(BaseModel):
    date: str
    things: list[Thing]
    total: int


# ── Proactive Surfaces ───────────────────────────────────────────────────────


class ProactiveSurface(BaseModel):
    thing: Thing
    reason: str
    date_key: str
    days_away: int
