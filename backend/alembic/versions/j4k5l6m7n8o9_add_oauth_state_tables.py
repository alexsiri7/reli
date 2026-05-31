"""add oauth state tables (SEC-016)

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-05-31 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "j4k5l6m7n8o9"
down_revision: Union[str, Sequence[str], None] = "i3j4k5l6m7n8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_oauth_sessions",
        sa.Column("server_state", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("client_state", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("redirect_uri", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("code_challenge", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("code_challenge_method", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("client_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scope", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("google_code_verifier", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("server_state"),
    )
    op.create_index("ix_mcp_oauth_sessions_expires_at", "mcp_oauth_sessions", ["expires_at"])

    op.create_table(
        "mcp_auth_codes",
        sa.Column("auth_code", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("code_challenge", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("code_challenge_method", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("redirect_uri", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("client_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("auth_code"),
    )
    op.create_index("ix_mcp_auth_codes_expires_at", "mcp_auth_codes", ["expires_at"])

    op.create_table(
        "mcp_registered_clients",
        sa.Column("client_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("client_secret", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("redirect_uris", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("client_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("grant_types", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("response_types", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("token_endpoint_auth_method", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scope", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("client_id"),
    )
    op.create_index("ix_mcp_registered_clients_expires_at", "mcp_registered_clients", ["expires_at"])

    op.create_table(
        "mcp_refresh_tokens",
        sa.Column("refresh_token", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("client_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scope", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("refresh_token"),
    )
    op.create_index("ix_mcp_refresh_tokens_expires_at", "mcp_refresh_tokens", ["expires_at"])

    op.create_table(
        "gmail_oauth_states",
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("state", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index("ix_gmail_oauth_states_expires_at", "gmail_oauth_states", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_mcp_oauth_sessions_expires_at", "mcp_oauth_sessions")
    op.drop_table("mcp_oauth_sessions")
    op.drop_index("ix_mcp_auth_codes_expires_at", "mcp_auth_codes")
    op.drop_table("mcp_auth_codes")
    op.drop_index("ix_mcp_registered_clients_expires_at", "mcp_registered_clients")
    op.drop_table("mcp_registered_clients")
    op.drop_index("ix_mcp_refresh_tokens_expires_at", "mcp_refresh_tokens")
    op.drop_table("mcp_refresh_tokens")
    op.drop_index("ix_gmail_oauth_states_expires_at", "gmail_oauth_states")
    op.drop_table("gmail_oauth_states")
