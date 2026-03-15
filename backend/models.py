"""Pydantic models for request/response validation."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ── Thing Types ───────────────────────────────────────────────────────────────


class ThingTypeCreate(BaseModel):
    """Create a new Thing Type with a name, icon, and optional color."""

    name: str = Field(..., min_length=1, max_length=100, examples=["person"])
    icon: str = Field(default="📌", max_length=10, examples=["👤"])
    color: str | None = Field(default=None, max_length=50, examples=["blue"])


class ThingTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=10)
    color: str | None = Field(default=None, max_length=50)


class ThingType(BaseModel):
    id: str
    name: str
    icon: str
    color: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Things ────────────────────────────────────────────────────────────────────


class ThingCreate(BaseModel):
    """Create a new Thing (task, note, project, idea, goal, person, etc.)."""

    title: str = Field(..., min_length=1, max_length=500, examples=["Buy groceries"])
    type_hint: str | None = Field(default=None, examples=["task"])
    parent_id: str | None = Field(default=None, description="Parent Thing ID for hierarchical nesting")
    checkin_date: datetime | None = Field(
        default=None, description="Date when this Thing should surface in the briefing"
    )
    priority: int = Field(default=3, ge=1, le=5, description="1 (highest) to 5 (lowest)")
    active: bool = Field(default=True, description="Inactive = completed/archived")
    surface: bool = Field(default=True, description="Whether to show in default views")
    data: dict[str, Any] | None = Field(default=None, description="Arbitrary JSON data (e.g. birthday, email, notes)")
    open_questions: list[str] | None = Field(default=None, description="Unresolved questions about this Thing")


class ThingUpdate(BaseModel):
    """Partial update for a Thing. Only provided fields are changed."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    type_hint: str | None = None
    parent_id: str | None = Field(default=None, description="Parent Thing ID for hierarchical nesting")
    checkin_date: datetime | None = Field(
        default=None, description="Date when this Thing should surface in the briefing"
    )
    priority: int | None = Field(default=None, ge=1, le=5, description="1 (highest) to 5 (lowest)")
    active: bool | None = Field(default=None, description="Inactive = completed/archived")
    surface: bool | None = Field(default=None, description="Whether to show in default views")
    data: dict[str, Any] | None = Field(default=None, description="Arbitrary JSON data")
    open_questions: list[str] | None = Field(default=None, description="Unresolved questions about this Thing")


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
    open_questions: list[str] | None = None
    children_count: int | None = None
    completed_count: int | None = None

    model_config = {"from_attributes": True}


# ── Relationships ────────────────────────────────────────────────────────────


class RelationshipCreate(BaseModel):
    """Create a typed relationship between two Things."""

    from_thing_id: str = Field(..., description="Source Thing ID")
    to_thing_id: str = Field(..., description="Target Thing ID")
    relationship_type: str = Field(
        ..., min_length=1, max_length=100, examples=["works_with"], description="Relationship label"
    )
    metadata: dict[str, Any] | None = Field(default=None, description="Optional metadata for this relationship")


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
    """Send a message through the multi-agent chat pipeline."""

    session_id: str = Field(..., min_length=1, description="Chat session identifier", examples=["session-abc123"])
    message: str = Field(..., min_length=1, description="User message text", examples=["What tasks are due this week?"])


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
    cost_usd: float = 0.0


class SessionUsage(BaseModel):
    """Cumulative usage stats for the current session."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    api_calls: int = 0
    cost_usd: float = 0.0
    per_model: list[ModelUsage] = []


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    applied_changes: dict[str, Any]
    questions_for_user: list[str]
    usage: UsageInfo | None = None
    session_usage: SessionUsage | None = None


# ── Briefing ──────────────────────────────────────────────────────────────────


class SweepFinding(BaseModel):
    id: str
    thing_id: str | None
    finding_type: str
    message: str
    priority: int
    dismissed: bool
    created_at: datetime
    expires_at: datetime | None
    snoozed_until: datetime | None = None
    thing: Thing | None = None

    model_config = {"from_attributes": True}


class SweepFindingCreate(BaseModel):
    """Create a sweep finding (insight from the nightly sweep)."""

    thing_id: str | None = Field(default=None, description="Related Thing ID, if applicable")
    finding_type: str = Field(
        ..., min_length=1, max_length=100, examples=["stale_task"], description="Category of finding"
    )
    message: str = Field(..., min_length=1, description="Human-readable finding message")
    priority: int = Field(default=2, ge=0, le=4, description="0 (critical) to 4 (backlog)")
    expires_at: datetime | None = Field(default=None, description="Auto-dismiss after this time")


class SweepFindingSnooze(BaseModel):
    """Snooze a finding until a given date."""

    until: datetime = Field(..., description="Hide the finding from the briefing until this time")


class BriefingResponse(BaseModel):
    date: str
    things: list[Thing]
    findings: list[SweepFinding]
    total: int


# ── Proactive Surfaces ───────────────────────────────────────────────────────


class ProactiveSurface(BaseModel):
    thing: Thing
    reason: str
    date_key: str
    days_away: int
