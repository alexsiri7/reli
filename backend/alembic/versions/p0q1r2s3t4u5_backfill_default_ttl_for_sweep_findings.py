"""backfill default TTL (expires_at) for sweep_findings

Revision ID: p0q1r2s3t4u5
Revises: o9p0q1r2s3t4
Create Date: 2026-06-04 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p0q1r2s3t4u5"
down_revision: Union[str, Sequence[str], None] = "o9p0q1r2s3t4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == "postgresql":
        conn.execute(
            sa.text(
                "UPDATE sweep_findings "
                "SET expires_at = created_at + INTERVAL '30 days' "
                "WHERE expires_at IS NULL AND dismissed = false"
            )
        )
    else:
        # SQLite: datetime stored as ISO-8601 text
        conn.execute(
            sa.text(
                "UPDATE sweep_findings "
                "SET expires_at = datetime(created_at, '+30 days') "
                "WHERE expires_at IS NULL AND dismissed = 0"
            )
        )


def downgrade() -> None:
    # Cannot distinguish backfilled rows from rows set by the LLM/user,
    # so downgrade is a no-op.
    pass
