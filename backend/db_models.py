"""The Reli data layer: Things, the relationships between them, and the mutations journal.

Three tables and nothing else. A Thing is the universal unit — task, note, project, idea, goal —
with no type column and no ``parent_id``; hierarchy is a ``ChildOf`` relationship like any other
edge. Every mutation of the first two tables is recorded in the third, which is append-only.

All writes go through :mod:`backend.service`, which is the only module that may construct or mutate
``ThingRecord`` and ``RelationshipRecord``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, Dialect, Float, ForeignKey, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, SQLModel

RELATIONSHIP_TYPE_CHECK = "relationships_relationship_type_check"


def _enum_values(enum_class: type[Enum]) -> list[str]:
    """Persist an enum by its value, not by its Python member name."""
    return [member.value for member in enum_class]


def _now() -> datetime:
    return datetime.now(UTC)


class RelationshipType(str, Enum):
    """The kinds of edge a relationship may carry.

    Each type declares its own reading of source and target; there is no global convention:

    - ``ChildOf`` — the **source is the parent** and the target is the child, so ``children(x)``
      returns the targets of ``x``'s ``ChildOf`` edges (issue #1408: "targets of ``ChildOf``, for
      the tree view").
    - ``Blocks`` — the **source is the blocked** Thing and the target is what blocks it, so
      ``blocked()`` returns the sources of ``Blocks`` edges whose target is still active.
    - ``EvidenceFor`` — the source is the evidence, pointing at the Thing it supports.
    - ``RelatedTo`` — the type does not pin a direction, but a query may: ``user_model`` follows
      ``RelatedTo`` from the ``#User`` anchor to the preference, so that edge's direction is
      load-bearing wherever a preference is anchored.
    - ``References`` — direction is not pinned; no query depends on it yet.
    """

    CHILD_OF = "ChildOf"
    BLOCKS = "Blocks"
    RELATED_TO = "RelatedTo"
    EVIDENCE_FOR = "EvidenceFor"
    REFERENCES = "References"


class RelationshipTypeText(TypeDecorator[RelationshipType]):
    """Stores :class:`RelationshipType` in the text column #1408 specifies, and reads it back as the enum.

    The database ``CHECK`` is the last word on which values exist; this rejects the same set one
    layer earlier, so a bad type fails with the name of the offending value rather than a
    constraint violation.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: RelationshipType | str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return RelationshipType(value).value

    def process_result_value(self, value: str | None, dialect: Dialect) -> RelationshipType | None:
        if value is None:
            return None
        return RelationshipType(value)


# The user model's literals live here for the same reason ``RelationshipType`` does: one home, read
# by both the write path (``backend.service``) and the read path (``backend.queries``), so the two
# layers cannot drift and ``queries`` never has to import from ``service``.

#: The single ``#User`` anchor every preference hangs off. A fixed primary key is what makes it
#: single — there is no second anchor to create, only a row that is there or is not.
USER_ANCHOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

USER_TAG = "#User"
PREFERENCE_TAG = "#Preference"
REJECTED_TAG = "#Rejected"

#: A relationship can only point at a Thing, so a journal entry becomes evidence by being wrapped in
#: a Thing tagged ``#Observation`` carrying ``notes["journal_entry_id"]``. The learning pass (#1413)
#: is what writes them; the convention is fixed here so it cannot be re-decided there.
OBSERVATION_TAG = "#Observation"


class Actor(str, Enum):
    """Who performed a journalled mutation."""

    USER = "user"
    CLAUDE_INTERACTIVE = "claude_interactive"
    CLAUDE_SCHEDULED = "claude_scheduled"


class Operation(str, Enum):
    """What a journalled mutation did."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RELATE = "relate"
    UNRELATE = "unrelate"


class EntityType(str, Enum):
    """Which table a journal entry refers to."""

    THING = "thing"
    RELATIONSHIP = "relationship"


class ThingRecord(SQLModel, table=True):
    """A Thing — the universal unit of the graph.

    There is deliberately no ``parent_id`` and no type column: hierarchy is a ``ChildOf``
    relationship, and what a Thing *is* lives in its tags and its edges.
    """

    __tablename__ = "things"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True),
    )
    title: str = Field(sa_column=Column(Text, nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    notes: dict[str, str] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
        description="Slug to markdown string mapping.",
    )
    tags: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )
    urls: dict[str, str] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
        description="Name to URL mapping.",
    )
    checkin_date: date | None = Field(default=None, sa_column=Column(Date, nullable=True))
    priority: float = Field(default=0.0, sa_column=Column(Float, nullable=False, server_default="0"))
    active: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default="true"))
    created_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class RelationshipRecord(SQLModel, table=True):
    """A directed edge between two Things. See :class:`RelationshipType` for what each direction means."""

    __tablename__ = "relationships"
    __table_args__ = (
        CheckConstraint(
            "relationship_type IN ('ChildOf', 'Blocks', 'RelatedTo', 'EvidenceFor', 'References')",
            name=RELATIONSHIP_TYPE_CHECK,
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True),
    )
    source_thing_id: uuid.UUID = Field(
        sa_column=Column(PGUUID(as_uuid=True), ForeignKey("things.id", ondelete="RESTRICT"), nullable=False),
    )
    target_thing_id: uuid.UUID = Field(
        sa_column=Column(PGUUID(as_uuid=True), ForeignKey("things.id", ondelete="RESTRICT"), nullable=False),
    )
    relationship_type: RelationshipType = Field(sa_column=Column(RelationshipTypeText, nullable=False))
    context: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class JournalRecord(SQLModel, table=True):
    """One append-only entry per mutation of a Thing or a relationship.

    The journal is the only record of how the graph got to its current state, so a missing entry is
    unrecoverable. A database trigger rejects ``UPDATE``, ``DELETE`` and ``TRUNCATE`` on this table.
    """

    __tablename__ = "journal"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    occurred_at: datetime = Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    actor: Actor = Field(
        sa_column=Column(SAEnum(Actor, name="journal_actor", values_callable=_enum_values), nullable=False),
    )
    operation: Operation = Field(
        sa_column=Column(SAEnum(Operation, name="journal_operation", values_callable=_enum_values), nullable=False),
    )
    entity_type: EntityType = Field(
        sa_column=Column(SAEnum(EntityType, name="journal_entity_type", values_callable=_enum_values), nullable=False),
    )
    entity_id: uuid.UUID = Field(sa_column=Column(PGUUID(as_uuid=True), nullable=False))
    before: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    after: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
