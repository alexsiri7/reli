"""SQLModel table models — the single source of truth for the database schema.

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
from typing import Any

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class ThingRecord(SQLModel, table=True):
    """A Thing in the knowledge graph — task, project, person, event, etc."""

    __tablename__ = "things"

    id: str = Field(default_factory=_new_id, primary_key=True)
    title: str
    type_hint: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    parent_id: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    checkin_date: datetime | None = None

    # Legacy column — kept for backward compat, use `importance` instead.
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
