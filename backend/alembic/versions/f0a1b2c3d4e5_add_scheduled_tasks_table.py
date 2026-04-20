"""add scheduled_tasks table

Revision ID: f0a1b2c3d4e5
Revises: d4e5f6a7b8c9
Create Date: 2026-04-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision: str = 'f0a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create scheduled_tasks table."""
    op.create_table('scheduled_tasks',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('thing_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('task_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="'remind'"),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('scheduled_at', sa.DateTime(), nullable=False),
        sa.Column('executed_at', sa.DateTime(), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['thing_id'], ['things.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_scheduled_tasks_scheduled_at', 'scheduled_tasks', ['scheduled_at'])
    op.create_index('ix_scheduled_tasks_thing_id', 'scheduled_tasks', ['thing_id'])


def downgrade() -> None:
    """Drop scheduled_tasks table."""
    op.drop_index('ix_scheduled_tasks_thing_id', 'scheduled_tasks')
    op.drop_index('ix_scheduled_tasks_scheduled_at', 'scheduled_tasks')
    op.drop_table('scheduled_tasks')
