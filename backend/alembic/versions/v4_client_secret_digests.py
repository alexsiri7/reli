"""Client secrets stored as digests, and consumed refresh tokens kept without their identity.

Issue #1715 (SEC-24). ``mcp_registered_clients.client_secret`` held the secret itself, and a
consumed refresh token kept the owner's ``subject`` and ``email`` for as long as thirty days,
though recognising a replay needs neither. ``backend.mcp_oauth`` now stores the SHA-256 hex digest
of the secret it hands out and compares the digest of the one presented, and
``backend.oauth_state.consume_refresh_token`` nulls the two identity columns in the statement that
consumes. This revision relaxes ``NOT NULL`` on those two columns, scrubs the rows consumed before
it, and rewrites each stored secret from its own value, so a connector holding the secret keeps
authenticating and nobody re-registers. Additive: no DDL that removes anything, and no row is
removed.

Revision ID: v4_client_secret_digests
Revises: v4_unique_evidence_for
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "v4_client_secret_digests"
down_revision: str | None = "v4_unique_evidence_for"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The digest expression is the one v4_hashed_credential_keys uses, which equals credential_digest.
# The SQL is spelled out in each statement so the destructive-DDL scan in backend/alembic/safety.py
# reads it as written.
def upgrade() -> None:
    op.alter_column("mcp_refresh_tokens", "subject", nullable=True)
    op.alter_column("mcp_refresh_tokens", "email", nullable=True)
    op.execute("UPDATE mcp_refresh_tokens SET subject = NULL, email = NULL WHERE consumed_at IS NOT NULL")
    op.execute(
        "UPDATE mcp_registered_clients SET client_secret = encode(sha256(convert_to(client_secret, 'UTF8')), 'hex')"
    )


def downgrade() -> None:
    # A digest cannot be turned back into the secret, nor a scrubbed identity restored. Older code
    # compares a presented secret against the digest and answers invalid_client; re-registering the
    # connector is the remedy. The columns stay nullable: older code only writes values into them.
    pass
