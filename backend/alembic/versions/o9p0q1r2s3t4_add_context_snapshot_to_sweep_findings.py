"""add context_snapshot and dismissed_reason to sweep_findings

Revision ID: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
Create Date: 2026-06-04 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o9p0q1r2s3t4"
down_revision: Union[str, Sequence[str], None] = "n8o9p0q1r2s3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("sweep_findings")]
    with op.batch_alter_table("sweep_findings") as batch_op:
        if "context_snapshot" not in columns:
            batch_op.add_column(sa.Column("context_snapshot", sa.JSON(), nullable=True))
        if "dismissed_reason" not in columns:
            batch_op.add_column(sa.Column("dismissed_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sweep_findings") as batch_op:
        batch_op.drop_column("dismissed_reason")
        batch_op.drop_column("context_snapshot")
