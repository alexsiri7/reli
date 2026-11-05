"""The revocation list logout writes: one bounded table of ``jti`` values, each kept until its JWT expires.

Issue #1699 (SEC-08). Logout deleted the cookie and nothing else, so a copy of the token kept
elsewhere stayed good for the rest of its seven days. ``backend.auth`` now records the ``jti`` of
the session it ends and refuses a token whose ``jti`` is here, on ``/api`` and ``/mcp`` alike —
the approach #1221 took before the v4 baseline dropped the table of the same name. Additive:
nothing existing is touched.

Revision ID: v4_revoked_tokens
Revises: v4_client_secret_digests
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v4_revoked_tokens"
down_revision: str | None = "v4_client_secret_digests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.Text(), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("revoked_tokens")
