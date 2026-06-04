"""add confidence to sweep_findings

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
Create Date: 2026-06-03 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m7n8o9p0q1r2"
down_revision: Union[str, Sequence[str], None] = "l6m7n8o9p0q1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("sweep_findings")]
    if "confidence" in columns:
        return  # idempotency guard
    with op.batch_alter_table("sweep_findings") as batch_op:
        batch_op.add_column(
            sa.Column("confidence", sa.Float(), nullable=True, server_default="0.5")
        )


def downgrade() -> None:
    with op.batch_alter_table("sweep_findings") as batch_op:
        batch_op.drop_column("confidence")
