"""add expires_at to merge_history

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-05-15 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h2i3j4k5l6m7"
down_revision: Union[str, Sequence[str], None] = "g1h2i3j4k5l6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add expires_at column to merge_history."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("merge_history")]
    if "expires_at" in columns:
        print("[h2i3j4k5l6m7] expires_at already present — skipping add_column (idempotency guard)")
        return  # column already exists (schema drift); skip to avoid duplicate column error
    with op.batch_alter_table("merge_history") as batch_op:
        batch_op.add_column(sa.Column("expires_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Remove expires_at column from merge_history."""
    with op.batch_alter_table("merge_history") as batch_op:
        batch_op.drop_column("expires_at")
