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

from sqlalchemy import JSON, Column, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector
from sqlmodel import Field, SQLModel

# SQL-level server defaults so raw INSERT statements (used in tests and
# legacy code) get sensible values without specifying every column.
_TS_DEFAULT = text("CURRENT_TIMESTAMP")

# Use JSONB on PostgreSQL (supports comparison operators, indexing, etc.)
# and plain JSON on SQLite (which stores JSON as text anyway).
_JSON = JSON().with_variant(JSONB(), "postgresql")


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
    priority: int | None = Field(default=3, exclude=True, sa_column_kwargs={"server_default": "3"})

    importance: int = Field(default=2, ge=0, le=4, sa_column_kwargs={"server_default": "2"})
    active: bool = Field(default=True, sa_column_kwargs={"server_default": "1"})
    surface: bool = Field(default=True, sa_column_kwargs={"server_default": "1"})

    data: dict[str, Any] | None = Field(default=None, sa_column=Column(_JSON, nullable=True))
    open_questions: list[str] | None = Field(default=None, sa_column=Column(_JSON, nullable=True))

    created_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})
    updated_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})
    last_referenced: datetime | None = None

    user_id: str | None = None


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------


class ThingRelationshipRecord(SQLModel, table=True):
    """A typed relationship between two Things."""

    __tablename__ = "thing_relationships"

    id: str = Field(default_factory=_new_id, primary_key=True)
    from_thing_id: str = Field(foreign_key="things.id", index=True)
    to_thing_id: str = Field(foreign_key="things.id", index=True)
    relationship_type: str
    metadata_: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column("metadata", _JSON, nullable=True),
    )
    created_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})


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
        default=None, sa_column=Column(_JSON, nullable=True)
    )
    prompt_tokens: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    completion_tokens: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    cost_usd: float = Field(default=0.0, sa_column_kwargs={"server_default": "0.0"})
    api_calls: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    model: str | None = None
    timestamp: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})
    user_id: str | None = None


class ChatMessageUsageRecord(SQLModel, table=True):
    """Per-call usage breakdown for a chat message."""

    __tablename__ = "chat_message_usage"

    id: int | None = Field(default=None, primary_key=True)
    chat_message_id: int = Field(foreign_key="chat_history.id")
    stage: str | None = None
    model: str
    prompt_tokens: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    completion_tokens: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    cost_usd: float = Field(default=0.0, sa_column_kwargs={"server_default": "0.0"})


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
    created_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})
    updated_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})


class UserSettingRecord(SQLModel, table=True):
    """Per-user key/value setting."""

    __tablename__ = "user_settings"

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(foreign_key="users.id")
    key: str
    value: str | None = None
    updated_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})


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
    priority: int = Field(default=2, sa_column_kwargs={"server_default": "2"})
    dismissed: bool = Field(default=False, sa_column_kwargs={"server_default": "0"})
    created_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})
    expires_at: datetime | None = None
    snoozed_until: datetime | None = None
    user_id: str | None = None


class SweepRunRecord(SQLModel, table=True):
    """Record of a sweep execution."""

    __tablename__ = "sweep_runs"

    id: str = Field(primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="users.id")
    status: str = Field(default="running", sa_column_kwargs={"server_default": "'running'"})
    candidates_found: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    findings_created: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    model: str | None = None
    prompt_tokens: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    completion_tokens: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    cost_usd: float = Field(default=0.0, sa_column_kwargs={"server_default": "0.0"})
    error: str | None = None
    started_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})
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
    prompt_tokens: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    completion_tokens: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    cost_usd: float = Field(default=0.0, sa_column_kwargs={"server_default": "0.0"})
    timestamp: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})
    user_id: str | None = None


# ---------------------------------------------------------------------------
# Thing Types
# ---------------------------------------------------------------------------


class ThingTypeRecord(SQLModel, table=True):
    """A named thing type with icon and color."""

    __tablename__ = "thing_types"

    id: str = Field(primary_key=True)
    name: str = Field(unique=True)
    icon: str = Field(default="\U0001f4cc", sa_column_kwargs={"server_default": "'\U0001f4cc'"})
    color: str | None = None
    created_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})


# ---------------------------------------------------------------------------
# Google Tokens
# ---------------------------------------------------------------------------


class GoogleTokenRecord(SQLModel, table=True):
    """Google OAuth tokens for calendar/gmail integration."""

    __tablename__ = "google_tokens"

    id: int | None = Field(default=None, primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="users.id")
    service: str = Field(default="calendar", sa_column_kwargs={"server_default": "'calendar'"})
    access_token: str
    refresh_token: str | None = None
    token_uri: str
    client_id: str
    client_secret: str
    expiry: str | None = None
    scopes: str | None = None
    created_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})
    updated_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})


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
        default=None, sa_column=Column(_JSON, nullable=True)
    )
    triggered_by: str = Field(default="api", sa_column_kwargs={"server_default": "'api'"})
    user_id: str | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})


# ---------------------------------------------------------------------------
# Morning Briefings
# ---------------------------------------------------------------------------


class MorningBriefingRecord(SQLModel, table=True):
    """Pre-generated morning briefing."""

    __tablename__ = "morning_briefings"

    id: str = Field(primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="users.id")
    briefing_date: str
    content: dict[str, Any] = Field(sa_column=Column(_JSON, nullable=False))
    generated_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})


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
    confidence: float = Field(default=0.5, sa_column_kwargs={"server_default": "0.5"})
    status: str = Field(default="pending", sa_column_kwargs={"server_default": "'pending'"})
    created_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})
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
    token_count: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    created_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})


# ---------------------------------------------------------------------------
# Weekly Briefings
# ---------------------------------------------------------------------------


class WeeklyBriefingRecord(SQLModel, table=True):
    """Pre-generated weekly digest briefing."""

    __tablename__ = "weekly_briefings"

    id: str = Field(primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="users.id")
    week_start: str
    content: dict[str, Any] = Field(sa_column=Column(_JSON, nullable=False))
    generated_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})


# Nudge Dismissals & Suppressions
# ---------------------------------------------------------------------------


class NudgeDismissalRecord(SQLModel, table=True):
    """A nudge dismissed by a user for a specific date."""

    __tablename__ = "nudge_dismissals"

    id: int | None = Field(default=None, primary_key=True)
    user_id: str
    nudge_id: str
    dismissed_date: str


class NudgeSuppressionRecord(SQLModel, table=True):
    """A permanently suppressed nudge type for a user."""

    __tablename__ = "nudge_suppressions"

    id: int | None = Field(default=None, primary_key=True)
    user_id: str
    nudge_type: str


# ---------------------------------------------------------------------------
# Thing Embeddings (pgvector)
# ---------------------------------------------------------------------------


class ThingEmbeddingRecord(SQLModel, table=True):
    """Vector embedding for a Thing, stored via pgvector."""

    __tablename__ = "thing_embeddings"

    thing_id: str = Field(primary_key=True, foreign_key="things.id")
    embedding: Any = Field(sa_column=Column(Vector(1536), nullable=False))
    content: str = Field(default="", sa_column_kwargs={"server_default": "''"})
    updated_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _TS_DEFAULT})
