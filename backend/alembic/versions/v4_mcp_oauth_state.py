"""The OAuth 2.1 authorization server's flow state: four bounded tables of short-lived rows.

Issue #1450, requirement 019. Restores the state the pre-v4 MCP authorization server kept —
registered clients, sign-ins in flight, authorization codes and refresh tokens — Postgres-native
this time: JSONB for the list fields and timestamptz for expiry. Additive: nothing existing is
touched. The baseline dropped the pre-v4 tables of the same names before this revision runs.

Revision ID: v4_mcp_oauth_state
Revises: v4_baseline
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v4_mcp_oauth_state"
down_revision: str | None = "v4_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _expires_at() -> sa.Column:
    return sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False)


def upgrade() -> None:
    op.create_table(
        "mcp_registered_clients",
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("client_secret", sa.Text(), nullable=False),
        sa.Column("redirect_uris", postgresql.JSONB(), nullable=False),
        sa.Column("client_name", sa.Text(), nullable=False),
        sa.Column("grant_types", postgresql.JSONB(), nullable=False),
        sa.Column("response_types", postgresql.JSONB(), nullable=False),
        sa.Column("token_endpoint_auth_method", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        _expires_at(),
        if_not_exists=True,
    )
    op.create_table(
        "mcp_oauth_sessions",
        sa.Column("server_state", sa.Text(), primary_key=True),
        sa.Column("client_state", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("code_challenge_method", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("google_code_verifier", sa.Text(), nullable=False),
        _expires_at(),
        if_not_exists=True,
    )
    op.create_table(
        "mcp_auth_codes",
        sa.Column("auth_code", sa.Text(), primary_key=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("code_challenge_method", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        _expires_at(),
        if_not_exists=True,
    )
    op.create_table(
        "mcp_refresh_tokens",
        sa.Column("refresh_token", sa.Text(), primary_key=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        _expires_at(),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("mcp_refresh_tokens")
    op.drop_table("mcp_auth_codes")
    op.drop_table("mcp_oauth_sessions")
    op.drop_table("mcp_registered_clients")
