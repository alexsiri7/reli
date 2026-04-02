"""remove parent_id column — use typed relationships for hierarchy

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-02 09:00:00.000000

Migrates existing parent_id data into thing_relationships as parent-of
relationships, then drops the parent_id column and its index from the
things table.  See GitHub issue #338.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Migrate parent_id to parent-of relationships, then drop the column."""
    conn = op.get_bind()

    # Step 1: Convert existing parent_id values into parent-of relationships.
    # Only create a relationship if one doesn't already exist.
    conn.execute(sa.text("""
        INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type, created_at)
        SELECT
            gen_random_uuid()::text,
            t.parent_id,
            t.id,
            'parent-of',
            NOW()
        FROM things t
        WHERE t.parent_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM thing_relationships r
            WHERE r.from_thing_id = t.parent_id
              AND r.to_thing_id = t.id
              AND r.relationship_type = 'parent-of'
          )
    """))

    # Step 2: Drop the index and column.
    op.drop_index('idx_things_parent', 'things')
    op.drop_column('things', 'parent_id')


def downgrade() -> None:
    """Re-add parent_id column and backfill from parent-of relationships."""
    op.add_column('things', sa.Column('parent_id', sa.Text(), nullable=True))
    op.create_index('idx_things_parent', 'things', ['parent_id'])

    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE things t
        SET parent_id = r.from_thing_id
        FROM thing_relationships r
        WHERE r.to_thing_id = t.id
          AND r.relationship_type = 'parent-of'
    """))
