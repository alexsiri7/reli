"""add chat_sessions table

Revision ID: g1h2i3j4k5l6
Revises: f0a1b2c3d4e5
Create Date: 2026-04-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision: str = 'g1h2i3j4k5l6'
down_revision: Union[str, Sequence[str], None] = 'f0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create chat_sessions table."""
    op.create_table('chat_sessions',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="'New chat'"),
        sa.Column('origin', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_active_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_chat_sessions_user_id', 'chat_sessions', ['user_id'])
    op.create_index('ix_chat_sessions_last_active_at', 'chat_sessions', ['last_active_at'])


def downgrade() -> None:
    """Drop chat_sessions table."""
    op.drop_index('ix_chat_sessions_last_active_at', table_name='chat_sessions')
    op.drop_index('ix_chat_sessions_user_id', table_name='chat_sessions')
    op.drop_table('chat_sessions')
