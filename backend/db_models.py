"""SQLModel table models — typed DB layer for Phase 2+ query migration.

These models mirror the existing SQLite schema managed by ``database.py``.
Phase 1 introduces the models and the engine/session setup.
Existing ``sqlite3`` code in ``database.py`` is unchanged during this phase.
Phase 2 will migrate queries table by table to use ``Session`` + these models.

**Important:** ``SQLModel.metadata.create_all()`` is NOT called anywhere in
this module.  Table creation remains in ``database.init_db()`` for the full
duration of the transition.  Only call ``create_all()`` in tests against a
fresh in-memory/temp database.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column
from sqlalchemy import JSON as SA_JSON
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    """Maps to the ``users`` table."""

    __tablename__ = "users"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    email: str = Field(sa_column_kwargs={"unique": True})
    google_id: str = Field(sa_column_kwargs={"unique": True})
    name: str
    picture: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Thing(SQLModel, table=True):
    """Maps to the ``things`` table."""

    __tablename__ = "things"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    title: str
    type_hint: Optional[str] = Field(default=None)
    parent_id: Optional[str] = Field(default=None, foreign_key="things.id")
    checkin_date: Optional[datetime] = Field(default=None)
    priority: int = Field(default=3)
    active: bool = Field(default=True)
    surface: bool = Field(default=True)
    data: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column("data", SA_JSON, nullable=True)
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_referenced: Optional[datetime] = Field(default=None)
    open_questions: Optional[list[str]] = Field(
        default=None, sa_column=Column("open_questions", SA_JSON, nullable=True)
    )
    user_id: Optional[str] = Field(default=None, foreign_key="users.id")


class ThingRelationship(SQLModel, table=True):
    """Maps to the ``thing_relationships`` table."""

    __tablename__ = "thing_relationships"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    from_thing_id: str = Field(foreign_key="things.id")
    to_thing_id: str = Field(foreign_key="things.id")
    relationship_type: str
    # "metadata" is reserved by SQLAlchemy; map the DB column explicitly.
    rel_metadata: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column("metadata", SA_JSON, nullable=True)
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SweepFinding(SQLModel, table=True):
    """Maps to the ``sweep_findings`` table."""

    __tablename__ = "sweep_findings"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    thing_id: Optional[str] = Field(default=None, foreign_key="things.id")
    finding_type: str
    message: str
    priority: int = Field(default=2)
    dismissed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = Field(default=None)
    snoozed_until: Optional[datetime] = Field(default=None)
    user_id: Optional[str] = Field(default=None, foreign_key="users.id")


class ChatHistory(SQLModel, table=True):
    """Maps to the ``chat_history`` table."""

    __tablename__ = "chat_history"  # type: ignore[assignment]

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str
    role: str
    content: str
    applied_changes: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column("applied_changes", SA_JSON, nullable=True)
    )
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    cost_usd: float = Field(default=0.0)
    api_calls: int = Field(default=0)
    model: Optional[str] = Field(default=None)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    user_id: Optional[str] = Field(default=None, foreign_key="users.id")
