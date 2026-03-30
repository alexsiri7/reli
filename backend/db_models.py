"""SQLModel table models -- the single source of truth for the database schema.

These models serve as both the database schema (table=True) and API response
types. During the migration from raw sqlite3, they coexist with the legacy
Pydantic models in ``models.py``. Once migration is complete, the legacy
models will be removed.

Naming: ``XxxRecord`` suffix during transition to avoid conflicts with
existing Pydantic models. After full migration, the suffix is dropped.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Things
# ---------------------------------------------------------------------------


class ThingRecord(SQLModel, table=True):
    """A Thing in the knowledge graph -- task, project, person, event, etc."""

    __tablename__ = "things"

    id: str = Field(default_factory=_new_id, primary_key=True)
    title: str
    type_hint: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    parent_id: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    checkin_date: datetime | None = None

    # Legacy column -- kept for backward compat, use ``importance`` instead.
    priority: int | None = Field(default=3, exclude=True)

    importance: int = Field(default=2, ge=0, le=4)
    active: bool = True
    surface: bool = True

    data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    open_questions: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    last_referenced: datetime | None = None

    user_id: str | None = None


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------


class ThingRelationshipRecord(SQLModel, table=True):
    """A typed relationship between two Things."""

    __tablename__ = "thing_relationships"

    id: str = Field(default_factory=_new_id, primary_key=True)
    from_thing_id: str = Field(foreign_key="things.id")
    to_thing_id: str = Field(foreign_key="things.id")
    relationship_type: str
    metadata_: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column("metadata", JSON, nullable=True),
    )
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatHistoryRecord(SQLModel, table=True):
    """A single chat message in a session."""

    __tablename__ = "chat_history"

    id: int | None = Field(default=None, primary_key=True)
    session_id: str
    role: str
    content: str
    applied_changes: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    api_calls: int = 0
    model: str | None = None
    timestamp: datetime = Field(default_factory=_utcnow)
    user_id: str | None = None


class ChatMessageUsageRecord(SQLModel, table=True):
    """Per-call usage breakdown for a chat message."""

    __tablename__ = "chat_message_usage"

    id: int | None = Field(default=None, primary_key=True)
    chat_message_id: int = Field(foreign_key="chat_history.id")
    stage: str | None = None
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# Users & Auth
# ---------------------------------------------------------------------------


class UserRecord(SQLModel, table=True):
    """A registered user."""

    __tablename__ = "users"

    id: str = Field(primary_key=True)
    email: str = Field(unique=True)
    google_id: str = Field(unique=True)
    name: str
    picture: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class UserSettingRecord(SQLModel, table=True):
    """Per-user key/value setting."""

    __tablename__ = "user_settings"

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(foreign_key="users.id")
    key: str
    value: str | None = None
    updated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Sweep & Findings
# ---------------------------------------------------------------------------


class SweepFindingRecord(SQLModel, table=True):
    """A sweep finding (insight from the nightly sweep)."""

    __tablename__ = "sweep_findings"

    id: str = Field(primary_key=True)
    thing_id: str | None = Field(default=None, foreign_key="things.id")
    finding_type: str
    message: str
    priority: int = 2
    dismissed: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime | None = None
    snoozed_until: datetime | None = None
    user_id: str | None = None


class SweepRunRecord(SQLModel, table=True):
    """Record of a sweep execution."""

    __tablename__ = "sweep_runs"

    id: str = Field(primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="users.id")
    status: str = "running"
    candidates_found: int = 0
    findings_created: int = 0
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


class UsageLogRecord(SQLModel, table=True):
    """Per-call usage log entry for daily aggregation."""

    __tablename__ = "usage_log"

    id: int | None = Field(default=None, primary_key=True)
    session_id: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    timestamp: datetime = Field(default_factory=_utcnow)
    user_id: str | None = None


# ---------------------------------------------------------------------------
# Thing Types
# ---------------------------------------------------------------------------


class ThingTypeRecord(SQLModel, table=True):
    """A named thing type with icon and color."""

    __tablename__ = "thing_types"

    id: str = Field(primary_key=True)
    name: str = Field(unique=True)
    icon: str = Field(default="\U0001f4cc")
    color: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Google Tokens
# ---------------------------------------------------------------------------


class GoogleTokenRecord(SQLModel, table=True):
    """Google OAuth tokens for calendar/gmail integration."""

    __tablename__ = "google_tokens"

    id: int | None = Field(default=None, primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="users.id")
    service: str = "calendar"
    access_token: str
    refresh_token: str | None = None
    token_uri: str
    client_id: str
    client_secret: str
    expiry: str | None = None
    scopes: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Merge History
# ---------------------------------------------------------------------------


class MergeHistoryRecord(SQLModel, table=True):
    """Audit trail for Thing merges."""

    __tablename__ = "merge_history"

    id: str = Field(primary_key=True)
    keep_id: str
    remove_id: str
    keep_title: str
    remove_title: str
    merged_data: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    triggered_by: str = "api"
    user_id: str | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Morning Briefings
# ---------------------------------------------------------------------------


class MorningBriefingRecord(SQLModel, table=True):
    """Pre-generated morning briefing."""

    __tablename__ = "morning_briefings"

    id: str = Field(primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="users.id")
    briefing_date: str
    content: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    generated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Connection Suggestions
# ---------------------------------------------------------------------------


class ConnectionSuggestionRecord(SQLModel, table=True):
    """Auto-connect suggestion between two Things."""

    __tablename__ = "connection_suggestions"

    id: str = Field(primary_key=True)
    from_thing_id: str = Field(foreign_key="things.id")
    to_thing_id: str = Field(foreign_key="things.id")
    suggested_relationship_type: str
    reason: str
    confidence: float = 0.5
    status: str = "pending"
    created_at: datetime = Field(default_factory=_utcnow)
    resolved_at: datetime | None = None
    user_id: str | None = Field(default=None, foreign_key="users.id")


# ---------------------------------------------------------------------------
# Conversation Summaries
# ---------------------------------------------------------------------------


class ConversationSummaryRecord(SQLModel, table=True):
    """Compressed conversation history summary."""

    __tablename__ = "conversation_summaries"

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(foreign_key="users.id")
    summary_text: str
    messages_summarized_up_to: int
    token_count: int = 0
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Weekly Briefings
# ---------------------------------------------------------------------------


class WeeklyBriefingRecord(SQLModel, table=True):
    """Pre-generated weekly digest briefing."""

    __tablename__ = "weekly_briefings"

    id: str = Field(primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="users.id")
    week_start: str
    content: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    generated_at: datetime = Field(default_factory=_utcnow)
