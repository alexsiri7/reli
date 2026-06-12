# reli:allow-destructive-ddl — drops the content column from thing_embeddings.
# The column stores a plaintext copy of _thing_to_text() output; it is never
# read by any query (all vector searches return only thing_id/embedding).
# Removing it reduces PII exposure surface. Data is fully derivable from the
# canonical things table — no data migration needed.
"""drop content column from thing_embeddings (SEC-11)

Revision ID: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
Create Date: 2026-06-12 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r2s3t4u5v6w7"
down_revision: Union[str, None] = "q1r2s3t4u5v6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("thing_embeddings", "content")


def downgrade() -> None:
    op.add_column(
        "thing_embeddings",
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
    )
