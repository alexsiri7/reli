"""add weekly_briefings table

Revision ID: e5348d5dff40
Revises: 450defba86b7
Create Date: 2026-03-30 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5348d5dff40"
down_revision: Union[str, Sequence[str], None] = "450defba86b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create weekly_briefings table."""
    op.create_table(
        "weekly_briefings",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("week_start", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Drop weekly_briefings table."""
    op.drop_table("weekly_briefings")
