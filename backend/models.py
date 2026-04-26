"""Pydantic models for request/response validation."""

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

# Maximum serialized size for arbitrary JSON dict fields (100 KB).
_MAX_DATA_JSON_BYTES = 100_000


def _validate_data_size(v: "dict[str, Any] | None") -> "dict[str, Any] | None":
    if v is not None and len(json.dumps(v)) > _MAX_DATA_JSON_BYTES:
        raise ValueError(f"data payload must be under {_MAX_DATA_JSON_BYTES} bytes when JSON-serialized")
    return v


def _validate_open_questions(v: "list[str] | None") -> "list[str] | None":
    if v is not None:
        if len(v) > 100:
            raise ValueError("open_questions may contain at most 100 items")
        for q in v:
            if len(q) > 2000:
                raise ValueError("each open_question must be at most 2000 characters")
    return v


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
    type_hint: str | None = Field(default=None, max_length=100, examples=["task"])
    checkin_date: datetime | None = Field(
        default=None, description="Date when this Thing should surface in the briefing"
    )
    importance: int = Field(default=2, ge=0, le=4, description="How bad if undone: 0 (critical) to 4 (backlog)")
    active: bool = Field(default=True, description="Inactive = completed/archived")
    surface: bool = Field(default=True, description="Whether to show in default views")
    data: dict[str, Any] | None = Field(default=None, description="Arbitrary JSON data (e.g. birthday, email, notes)")
    open_questions: list[str] | None = Field(default=None, description="Unresolved questions about this Thing")

    @field_validator("data")
    @classmethod
    def data_max_size(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return _validate_data_size(v)

    @field_validator("open_questions")
    @classmethod
    def open_questions_limits(cls, v: list[str] | None) -> list[str] | None:
        return _validate_open_questions(v)


class ThingUpdate(BaseModel):
    """Partial update for a Thing. Only provided fields are changed."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    type_hint: str | None = Field(default=None, max_length=100)
    checkin_date: datetime | None = Field(
        default=None, description="Date when this Thing should surface in the briefing"
    )
    importance: int | None = Field(default=None, ge=0, le=4, description="How bad if undone: 0 (critical) to 4 (backlog)")
    active: bool | None = Field(default=None, description="Inactive = completed/archived")
    surface: bool | None = Field(default=None, description="Whether to show in default views")
    data: dict[str, Any] | None = Field(default=None, description="Arbitrary JSON data")
    open_questions: list[str] | None = Field(default=None, description="Unresolved questions about this Thing")

    @field_validator("data")
    @classmethod
    def data_max_size(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return _validate_data_size(v)

    @field_validator("open_questions")
    @classmethod
    def open_questions_limits(cls, v: list[str] | None) -> list[str] | None:
        return _validate_open_questions(v)


class Thing(BaseModel):
    id: str
    title: str
    type_hint: str | None
    checkin_date: datetime | None
    importance: int
    active: bool
    surface: bool
    data: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    last_referenced: datetime | None = None
    open_questions: list[str] | None = None
    children_count: int | None = None
    completed_count: int | None = None
    parent_ids: list[str] | None = None

    model_config = {"from_attributes": True}


# ── Graph ────────────────────────────────────────────────────────────────────


class GraphNode(BaseModel):
    id: str
    title: str
    type_hint: str | None
    icon: str | None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relationship_type: str


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class OrphanCleanupResult(BaseModel):
    """Result of orphan relationship cleanup."""

    deleted_count: int
    deleted_ids: list[str]


# ── Relationships ────────────────────────────────────────────────────────────


class RelationshipCreate(BaseModel):
    """Create a typed relationship between two Things."""

    from_thing_id: str = Field(..., max_length=100, description="Source Thing ID")
    to_thing_id: str = Field(..., max_length=100, description="Target Thing ID")
    relationship_type: str = Field(
        ..., min_length=1, max_length=100, examples=["works_with"], description="Relationship label"
    )
    metadata: dict[str, Any] | None = Field(default=None, description="Optional metadata for this relationship")

    @field_validator("metadata")
    @classmethod
    def metadata_max_size(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and len(json.dumps(v)) > _MAX_DATA_JSON_BYTES:
            raise ValueError(f"metadata must be under {_MAX_DATA_JSON_BYTES} bytes when JSON-serialized")
        return v


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
    session_id: str = Field(..., min_length=1, max_length=200)
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str = Field(..., min_length=1, max_length=100_000)
    applied_changes: dict[str, Any] | None = None

    @field_validator("applied_changes")
    @classmethod
    def applied_changes_max_size(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and len(json.dumps(v)) > _MAX_DATA_JSON_BYTES:
            raise ValueError(f"applied_changes must be under {_MAX_DATA_JSON_BYTES} bytes when JSON-serialized")
        return v


class ChatSessionCreate(BaseModel):
    """Create a named chat session."""

    title: str = Field(default="New chat", min_length=1, max_length=500)
    origin: str | None = Field(default=None, max_length=100)


class ChatSessionListItem(BaseModel):
    """Summary of a chat session for listing."""

    id: str
    title: str
    origin: str | None = None
    created_at: datetime
    last_active_at: datetime

    model_config = {"from_attributes": True}


class CallUsage(BaseModel):
    """Usage for a single API call."""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


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
    per_call_usage: list[CallUsage] = []
    timestamp: datetime

    model_config = {"from_attributes": True}


# ── Chat Pipeline ─────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Send a message through the multi-agent chat pipeline."""

    session_id: str = Field(..., min_length=1, max_length=200, description="Chat session identifier", examples=["session-abc123"])
    message: str = Field(
        ...,
        min_length=1,
        max_length=10_000,
        description="User message text (max 10 000 chars)",
        examples=["What tasks are due this week?"],
    )
    mode: str = Field(
        default="normal",
        max_length=50,
        description="Chat mode ('normal' or 'planning') that changes reasoning behavior",
        examples=["normal", "planning"],
    )


class MigrateSessionRequest(BaseModel):
    """Migrate chat history from an old session ID to a new one."""

    old_session_id: str = Field(..., min_length=1, max_length=200, description="The old session ID to migrate from")
    new_session_id: str = Field(..., min_length=1, max_length=200, description="The new session ID to migrate to")


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    api_calls: int = 0
    model: str = ""
    per_call_usage: list[CallUsage] = []


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
    mode: str = "normal"
    usage: UsageInfo | None = None
    session_usage: SessionUsage | None = None


# ── Chat Sessions ────────────────────────────────────────────────────────────


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    origin: str | None = None
    created_at: datetime
    last_active_at: datetime
    message_count: int

    model_config = {"from_attributes": True}


class CreateSessionRequest(BaseModel):
    session_id: str
    title: str = "New chat"
    origin: str | None = None


class PatchSessionRequest(BaseModel):
    title: str


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

    thing_id: str | None = Field(default=None, max_length=100, description="Related Thing ID, if applicable")
    finding_type: str = Field(
        ..., min_length=1, max_length=100, examples=["stale_task"], description="Category of finding"
    )
    message: str = Field(..., min_length=1, max_length=5000, description="Human-readable finding message")
    priority: int = Field(default=2, ge=0, le=4, description="0 (critical) to 4 (backlog)")
    expires_at: datetime | None = Field(default=None, description="Auto-dismiss after this time")


class SweepFindingSnooze(BaseModel):
    """Snooze a finding until a given date."""

    until: datetime = Field(..., description="Hide the finding from the briefing until this time")


class BriefingItem(BaseModel):
    """A Thing scored by importance x urgency for the briefing."""

    thing: dict[str, Any]
    importance: int
    urgency: float
    score: float
    reasons: list[str]


class LearnedPreference(BaseModel):
    id: str
    title: str
    confidence_label: str  # "emerging", "moderate", or "strong"


class BriefingResponse(BaseModel):
    date: str
    the_one_thing: BriefingItem | None = None
    secondary: list[BriefingItem] = []
    parking_lot: list[dict[str, Any]] = []
    findings: list[SweepFinding] = []
    learned_preferences: list[LearnedPreference] = []
    total: int
    stats: dict[str, int] = {}


# ── Staleness & Neglect ─────────────────────────────────────────────────────


class StaleItem(BaseModel):
    """A Thing that hasn't been updated within the configured staleness window."""

    thing: Thing
    days_stale: int
    is_neglected: bool
    active_children: int = 0


class OverdueCheckin(BaseModel):
    """A Thing whose checkin_date is in the past."""

    thing: Thing
    days_overdue: int


class StalenessCategory(BaseModel):
    """Staleness counts grouped by category."""

    stale: int = 0
    neglected: int = 0
    overdue_checkins: int = 0


class StalenessReport(BaseModel):
    """Batch summary of stale and neglected items."""

    as_of: str
    stale_threshold_days: int
    stale_items: list[StaleItem]
    overdue_checkins: list[OverdueCheckin]
    counts: StalenessCategory
    total: int


# ── Morning Briefing ─────────────────────────────────────────────────────────


class MorningBriefingItem(BaseModel):
    """A single item in the morning briefing (importance, overdue, or blocker)."""

    thing_id: str
    title: str
    score: float | None = None
    reasons: list[str] = []
    days_overdue: int | None = None
    blocked_by: list[str] = []


class MorningBriefingFinding(BaseModel):
    """A sweep finding included in the morning briefing."""

    id: str
    message: str
    priority: int
    thing_id: str | None = None
    thing_title: str | None = None


class MorningBriefingContent(BaseModel):
    """Structured content of a pre-generated morning briefing."""

    summary: str
    priorities: list[MorningBriefingItem] = []
    overdue: list[MorningBriefingItem] = []
    blockers: list[MorningBriefingItem] = []
    findings: list[MorningBriefingFinding] = []
    stats: dict[str, int] = {}


class MorningBriefing(BaseModel):
    """A pre-generated morning briefing."""

    id: str
    briefing_date: str
    content: MorningBriefingContent
    generated_at: datetime

    model_config = {"from_attributes": True}


class BriefingPreferences(BaseModel):
    """User preferences for morning briefing content."""

    include_priorities: bool = True
    include_overdue: bool = True
    include_blockers: bool = True
    include_findings: bool = True
    max_priorities: int = Field(default=5, ge=1, le=20)
    max_findings: int = Field(default=10, ge=1, le=50)


# ── Nudges ────────────────────────────────────────────────────────────────────


class Nudge(BaseModel):
    """A proactive nudge surfaced to the user based on approaching dates."""

    id: str
    nudge_type: str
    message: str
    thing_id: str | None = None
    thing_title: str | None = None
    thing_type_hint: str | None = None
    days_away: int | None = None
    primary_action_label: str | None = None


# ── Weekly Digest ─────────────────────────────────────────────────────────────


class WeeklyBriefingItem(BaseModel):
    """A single item in a weekly digest section."""

    thing_id: str
    title: str
    type_hint: str | None = None
    detail: str | None = None


class WeeklyBriefingConnection(BaseModel):
    """A newly discovered connection between two things."""

    from_title: str
    to_title: str
    relationship_type: str


class WeeklyBriefingContent(BaseModel):
    """The structured content of a weekly digest."""

    summary: str
    week_start: str
    week_end: str
    completed: list[WeeklyBriefingItem] = Field(default_factory=list)
    upcoming: list[WeeklyBriefingItem] = Field(default_factory=list)
    new_connections: list[WeeklyBriefingConnection] = Field(default_factory=list)
    preferences_learned: list[str] = Field(default_factory=list)
    open_questions: list[WeeklyBriefingItem] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)


class WeeklyBriefing(BaseModel):
    """A pre-generated weekly digest."""

    id: str
    week_start: str
    content: WeeklyBriefingContent
    generated_at: datetime

    model_config = {"from_attributes": True}


# ── Personality Preferences ───────────────────────────────────────────────────


class PersonalityPattern(BaseModel):
    """A single learned personality/behavior pattern."""

    pattern: str = Field(..., min_length=1, max_length=2000, description="The learned preference pattern text")
    confidence: str = Field(default="emerging", max_length=50, description="Confidence level: emerging, established, or strong")
    observations: int = Field(default=1, ge=1, description="Number of times this pattern has been observed")


class PersonalityPreferenceData(BaseModel):
    """Collection of personality patterns loaded from preference Things."""

    patterns: list[PersonalityPattern] = Field(default_factory=list)


# ── Proactive Surfaces ───────────────────────────────────────────────────────


class ProactiveSurface(BaseModel):
    thing: Thing
    reason: str
    date_key: str
    days_away: int


# ── Focus Recommendations ──────────────────────────────────────────────────


class FocusRecommendation(BaseModel):
    thing: Thing
    score: float
    reasons: list[str]
    is_blocked: bool = False


class FocusResponse(BaseModel):
    recommendations: list[FocusRecommendation]
    total: int
    calendar_active: bool = False


# ── Conflict Alerts ─────────────────────────────────────────────────────────


class ConflictAlertResponse(BaseModel):
    alert_type: str
    severity: str
    message: str
    thing_ids: list[str]
    thing_titles: list[str]


# ── Merge Suggestions ────────────────────────────────────────────────────────


class MergeSuggestionThing(BaseModel):
    """Minimal Thing representation for merge suggestions."""

    id: str
    title: str
    type_hint: str | None


class MergeSuggestion(BaseModel):
    """A pair of Things that may be duplicates."""

    thing_a: MergeSuggestionThing
    thing_b: MergeSuggestionThing
    reason: str


class MergeRequest(BaseModel):
    """Request to merge two Things."""

    keep_id: str = Field(..., max_length=100, description="ID of the Thing to keep")
    remove_id: str = Field(..., max_length=100, description="ID of the Thing to merge into keep_id and delete")


class MergeResult(BaseModel):
    """Result of a merge operation."""

    keep_id: str
    remove_id: str
    keep_title: str
    remove_title: str


class MergeHistoryRecord(BaseModel):
    """A recorded merge event for audit trail."""

    id: str
    keep_id: str
    remove_id: str
    keep_title: str
    remove_title: str
    merged_data: dict[str, Any] | None
    triggered_by: str
    user_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Connection Suggestions ──────────────────────────────────────────────────


class ConnectionSuggestionThing(BaseModel):
    """Minimal Thing representation for connection suggestions."""

    id: str
    title: str
    type_hint: str | None


class ConnectionSuggestion(BaseModel):
    """A suggested connection between two Things."""

    id: str
    from_thing: ConnectionSuggestionThing
    to_thing: ConnectionSuggestionThing
    suggested_relationship_type: str
    reason: str
    confidence: float
    status: str
    created_at: datetime


class ConnectionSuggestionAccept(BaseModel):
    """Accept a connection suggestion, optionally overriding the relationship type."""

    relationship_type: str | None = Field(default=None, max_length=100, description="Override the suggested relationship type")
