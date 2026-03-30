"""add thing_embeddings table with pgvector

Revision ID: a1b2c3d4e5f6
Revises: e5348d5dff40
Create Date: 2026-03-30 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from pgvector.sqlalchemy import Vector
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'e5348d5dff40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable pgvector extension and create thing_embeddings table."""
    op.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.create_table('thing_embeddings',
        sa.Column('thing_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('embedding', Vector(3072), nullable=False),
        sa.Column('content', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['thing_id'], ['things.id'], ),
        sa.PrimaryKeyConstraint('thing_id')
    )


def downgrade() -> None:
    """Drop thing_embeddings table."""
    op.drop_table('thing_embeddings')
