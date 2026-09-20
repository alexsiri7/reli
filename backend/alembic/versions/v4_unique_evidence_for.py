"""One ``EvidenceFor`` edge per (source, target), enforced by a partial unique index.

Issue #1536 (REL-014). Preference strength is the count of ``EvidenceFor`` edges pointing at the
preference, and nothing in the schema kept a pair from carrying two: ``add_preference_evidence``
checked before inserting, which two concurrent calls both pass, and ``relate`` never checked. A
duplicate overstates a preference by one — the confidence float the design forbids, by another
name. This revision adds ``EVIDENCE_FOR_UNIQUE_INDEX`` over ``(source_thing_id, target_thing_id)``
where ``relationship_type = 'EvidenceFor'``; the other four types are not constrained, since
nothing counts them and a second ``References`` edge with a different ``context`` is a legitimate
edge.

A unique index cannot be built over rows that already violate it, and a migration failure fails
the boot, so the revision first collapses any duplicate pair through
``backend.service.collapse_duplicate_evidence``: the earliest edge of each pair stays and every
later one is journalled as an ``unrelate`` by ``claude_scheduled`` with its snapshot in ``before``.
Additive: one index, no DDL that removes anything; the rows it removes are on the journal.

Revision ID: v4_unique_evidence_for
Revises: v4_hashed_credential_keys
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlmodel import Session

from backend.db_models import EVIDENCE_FOR_UNIQUE_INDEX
from backend.service import collapse_duplicate_evidence

revision: str = "v4_unique_evidence_for"
down_revision: str | None = "v4_hashed_credential_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The session joins the transaction Alembic already opened on this connection, so the collapse
    # and the index commit together and nothing here commits on its own.
    with Session(op.get_bind()) as session:
        collapse_duplicate_evidence(session)
    op.create_index(
        EVIDENCE_FOR_UNIQUE_INDEX,
        "relationships",
        ["source_thing_id", "target_thing_id"],
        unique=True,
        postgresql_where=sa.text("relationship_type = 'EvidenceFor'"),
    )


def downgrade() -> None:
    # The collapsed edges stay collapsed: the journal is append-only, so the record of removing
    # them cannot be taken back, and the count they left is the honest one.
    op.drop_index(EVIDENCE_FOR_UNIQUE_INDEX, table_name="relationships")
