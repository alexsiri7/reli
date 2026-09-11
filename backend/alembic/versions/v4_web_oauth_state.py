"""The web view's sign-in flow state: one bounded table of PKCE verifiers keyed by state.

Issue #1449, requirement 019. The pre-v4 web sign-in kept this in an in-process dict; a table
survives a container restart mid-sign-in and follows the four MCP stores. Additive: nothing
existing is touched.

Revision ID: v4_web_oauth_state
Revises: v4_mcp_oauth_state
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v4_web_oauth_state"
down_revision: str | None = "v4_mcp_oauth_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "web_oauth_sessions",
        sa.Column("state", sa.Text(), primary_key=True),
        sa.Column("google_code_verifier", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("web_oauth_sessions")
