"""v4 baseline: things, relationships and the mutations journal.

Issue #1408, requirement 018. This is the clean baseline of the vision-v4 rebuild: it replaces the
whole pre-v4 schema rather than migrating it, so it has no ``down_revision``.

Revision ID: v4_baseline
Revises:
Create Date: 2026-09-10
"""

# reli:allow-destructive-ddl
#
# The 29 pre-v4 tables are dropped outright. Sanctioned by CLAUDE.md's Database Safety Policy:
# the baseline "is allowed to define the schema outright... it does not need to preserve or migrate
# the legacy tables", and the owner holds an offline export of the legacy graph (#1406) outside this
# public repository. The additive-only rule applies from this revision forward.
#
# Operational note: a database that still carries a pre-v4 ``alembic_version`` row cannot reach this
# revision, because Alembic cannot resolve the recorded revision against a ``down_revision = None``
# baseline. Drop that table once before the first deploy — see CLAUDE.md's Deployment section.

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v4_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LEGACY_TABLES = (
    "things",
    "thing_relationships",
    "chat_sessions",
    "chat_history",
    "chat_message_usage",
    "users",
    "user_settings",
    "sweep_findings",
    "sweep_runs",
    "sweep_actions",
    "usage_log",
    "thing_types",
    "google_tokens",
    "merge_history",
    "mcp_mutations",
    "morning_briefings",
    "connection_suggestions",
    "conversation_summaries",
    "weekly_briefings",
    "nudge_dismissals",
    "nudge_suppressions",
    "thing_embeddings",
    "scheduled_tasks",
    "mcp_oauth_sessions",
    "mcp_auth_codes",
    "mcp_registered_clients",
    "mcp_refresh_tokens",
    "gmail_oauth_states",
    "revoked_tokens",
)

RELATIONSHIP_TYPES = ("ChildOf", "Blocks", "RelatedTo", "EvidenceFor", "References")

journal_actor = postgresql.ENUM(
    "user", "claude_interactive", "claude_scheduled", name="journal_actor", create_type=False
)
journal_operation = postgresql.ENUM(
    "create", "update", "delete", "relate", "unrelate", name="journal_operation", create_type=False
)
journal_entity_type = postgresql.ENUM("thing", "relationship", name="journal_entity_type", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    for table in LEGACY_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    journal_actor.create(bind, checkfirst=True)
    journal_operation.create(bind, checkfirst=True)
    journal_entity_type.create(bind, checkfirst=True)

    op.create_table(
        "things",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("notes", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("urls", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("checkin_date", sa.Date(), nullable=True),
        sa.Column("priority", sa.Float(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_things_title", "things", ["title"])
    op.create_index("ix_things_checkin_date", "things", ["checkin_date"])
    op.create_index("ix_things_active", "things", ["active"])
    op.create_index("ix_things_updated_at", "things", ["updated_at"])
    # Default jsonb_ops rather than jsonb_path_ops: by_tag(match="any") uses ?|, which
    # jsonb_path_ops does not index.
    op.create_index("ix_things_tags", "things", ["tags"], postgresql_using="gin")

    types_sql = ", ".join(f"'{name}'" for name in RELATIONSHIP_TYPES)
    op.create_table(
        "relationships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_thing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_thing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relationship_type", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # RESTRICT, not CASCADE: deleting a Thing with edges must fail rather than silently remove
        # relationships without journal entries. backend.service unrelates first.
        sa.ForeignKeyConstraint(["source_thing_id"], ["things.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_thing_id"], ["things.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            f"relationship_type IN ({types_sql})",
            name="relationships_relationship_type_check",
        ),
    )
    op.create_index("ix_relationships_source_thing_id", "relationships", ["source_thing_id"])
    op.create_index("ix_relationships_target_thing_id", "relationships", ["target_thing_id"])
    op.create_index("ix_relationships_relationship_type", "relationships", ["relationship_type"])

    op.create_table(
        "journal",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", journal_actor, nullable=False),
        sa.Column("operation", journal_operation, nullable=False),
        sa.Column("entity_type", journal_entity_type, nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_journal_occurred_at", "journal", ["occurred_at"])
    op.create_index("ix_journal_entity_id", "journal", ["entity_id"])

    # A trigger rather than a rewrite rule: a rule that does nothing swallows the write silently,
    # where the journal must refuse it loudly.
    op.execute(
        """
        CREATE FUNCTION journal_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'journal is append-only: % is not permitted', TG_OP;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER journal_no_mutate BEFORE UPDATE OR DELETE ON journal
            FOR EACH ROW EXECUTE FUNCTION journal_append_only()
        """
    )
    op.execute(
        """
        CREATE TRIGGER journal_no_truncate BEFORE TRUNCATE ON journal
            FOR EACH STATEMENT EXECUTE FUNCTION journal_append_only()
        """
    )


def downgrade() -> None:
    """Drop the v4 schema. The pre-v4 tables are not restored — see the note at the top of this file."""
    op.execute("DROP TRIGGER IF EXISTS journal_no_truncate ON journal")
    op.execute("DROP TRIGGER IF EXISTS journal_no_mutate ON journal")
    op.execute("DROP FUNCTION IF EXISTS journal_append_only()")
    op.drop_table("journal")
    op.drop_table("relationships")
    op.drop_table("things")

    bind = op.get_bind()
    journal_entity_type.drop(bind, checkfirst=True)
    journal_operation.drop(bind, checkfirst=True)
    journal_actor.drop(bind, checkfirst=True)
