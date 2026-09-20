"""Refresh tokens and authorization codes stored as digests: nothing in the two tables redeems.

Issue #1530 (REL-008). ``mcp_refresh_tokens`` and ``mcp_auth_codes`` were keyed by the credential
itself, so a reader of the database or a backup held thirty days of renewable access to ``/mcp``.
``backend.oauth_state`` now stores the SHA-256 hex digest of the value handed to the client and
looks a row up by the digest of the value presented; this revision brings the live rows under the
same rule by rewriting each key from its own value, so the connector holding the raw token keeps
matching and nobody re-authorises. ``v4_refresh_token_families`` named a family after its first
token, so a family older than that revision carries a raw token in ``family_id`` on every row; those
are rewritten to the same digest first, while the token they copy can still be recognised.
Additive: no DDL, and no row is removed.

Revision ID: v4_hashed_credential_keys
Revises: v4_backfill_checkin_dates
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "v4_hashed_credential_keys"
down_revision: str | None = "v4_backfill_checkin_dates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# convert_to, not a bytea cast: the cast reads backslash escapes, convert_to encodes every
# character, which is what ``str.encode()`` does on the Python side. The SQL is spelled out in each
# statement so the destructive-DDL scan in backend/alembic/safety.py reads it as written.
def upgrade() -> None:
    op.execute(
        "UPDATE mcp_refresh_tokens SET family_id = encode(sha256(convert_to(family_id, 'UTF8')), 'hex')"
        " WHERE family_id IN (SELECT refresh_token FROM mcp_refresh_tokens)"
    )
    op.execute("UPDATE mcp_refresh_tokens SET refresh_token = encode(sha256(convert_to(refresh_token, 'UTF8')), 'hex')")
    op.execute("UPDATE mcp_auth_codes SET auth_code = encode(sha256(convert_to(auth_code, 'UTF8')), 'hex')")


def downgrade() -> None:
    # A digest cannot be turned back into the credential. Older code compares a presented token
    # against the digest, finds nothing and answers invalid_grant; re-authorising is the remedy,
    # and the rows expire on their own.
    pass
