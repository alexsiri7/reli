"""add indexes on thing_relationships foreign keys

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-02 01:00:00.000000

The search_things Phase 2 query uses EXISTS sub-selects that join
thing_relationships on from_thing_id / to_thing_id.  Without indexes
on these columns, SQLite and PostgreSQL both resort to full table scans
on thing_relationships, causing timeouts on larger datasets (#319).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add indexes on thing_relationships.from_thing_id and .to_thing_id."""
    op.create_index('ix_thing_relationships_from_thing_id', 'thing_relationships', ['from_thing_id'])
    op.create_index('ix_thing_relationships_to_thing_id', 'thing_relationships', ['to_thing_id'])


def downgrade() -> None:
    """Remove relationship FK indexes."""
    op.drop_index('ix_thing_relationships_to_thing_id', 'thing_relationships')
    op.drop_index('ix_thing_relationships_from_thing_id', 'thing_relationships')
