"""Refresh-token families: which sign-in a refresh token descends from, and when it was consumed.

Issue #1455, requirement 019. A rotated refresh token used to be deleted, so a replay of it was
indistinguishable from garbage. It is now kept, marked ``consumed_at``, until it expires, and every
token rotated from one authorization-code exchange shares a ``family_id`` — presenting a consumed
token revokes the family (OAuth 2.1 §4.3.1). Additive: two columns, and a live token already in the
table becomes its own one-member family.

Revision ID: v4_refresh_token_families
Revises: v4_web_oauth_state
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v4_refresh_token_families"
down_revision: str | None = "v4_web_oauth_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mcp_refresh_tokens", sa.Column("family_id", sa.Text(), nullable=True), if_not_exists=True)
    op.execute("UPDATE mcp_refresh_tokens SET family_id = refresh_token WHERE family_id IS NULL")
    op.alter_column("mcp_refresh_tokens", "family_id", existing_type=sa.Text(), nullable=False)
    op.add_column(
        "mcp_refresh_tokens",
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_column("mcp_refresh_tokens", "consumed_at")
    op.drop_column("mcp_refresh_tokens", "family_id")
