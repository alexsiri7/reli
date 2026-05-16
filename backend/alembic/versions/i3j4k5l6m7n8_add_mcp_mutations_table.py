"""add mcp_mutations table

Revision ID: i3j4k5l6m7n8
Revises: a1b2c3d4e5f6
Create Date: 2026-05-16 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "i3j4k5l6m7n8"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create mcp_mutations table for audit logging."""
    op.create_table(
        "mcp_mutations",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("client_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("operation", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("thing_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("before_snapshot", sa.JSON(), nullable=True),
        sa.Column("after_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mcp_mutations_thing_id", "mcp_mutations", ["thing_id"])
    op.create_index("ix_mcp_mutations_occurred_at", "mcp_mutations", ["occurred_at"])


def downgrade() -> None:
    """Drop mcp_mutations table."""
    op.drop_index("ix_mcp_mutations_occurred_at", "mcp_mutations")
    op.drop_index("ix_mcp_mutations_thing_id", "mcp_mutations")
    op.drop_table("mcp_mutations")
