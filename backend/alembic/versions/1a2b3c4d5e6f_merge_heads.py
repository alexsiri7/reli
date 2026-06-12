"""merge heads h2i3j4k5l6m7 and p0q1r2s3t4u5

Revision ID: 1a2b3c4d5e6f
Revises: h2i3j4k5l6m7, p0q1r2s3t4u5
Create Date: 2026-06-01 00:00:00.000000

"""

from typing import Sequence, Union

revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = ("h2i3j4k5l6m7", "p0q1r2s3t4u5")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
