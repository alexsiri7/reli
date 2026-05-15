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
    op.add_column("merge_history", sa.Column("expires_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Remove expires_at column from merge_history."""
    op.drop_column("merge_history", "expires_at")
