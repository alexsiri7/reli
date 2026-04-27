"""fix embedding vector dimensions 3072 -> 1536

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-30 23:30:00.000000

The thing_embeddings table was created with Vector(3072) but the
production EMBEDDING_MODEL is text-embedding-3-small which produces
1536-dimensional vectors.  Since the table is empty (reindex hasn't
run yet), we can safely drop and recreate the column.
"""

from typing import Sequence, Union

from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change embedding column from Vector(3072) to Vector(1536)."""
    op.alter_column(
        "thing_embeddings",
        "embedding",
        type_=Vector(1536),
        existing_type=Vector(3072),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Revert embedding column to Vector(3072)."""
    op.alter_column(
        "thing_embeddings",
        "embedding",
        type_=Vector(3072),
        existing_type=Vector(1536),
        existing_nullable=False,
    )
