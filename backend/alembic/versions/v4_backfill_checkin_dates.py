"""Backfill: a check-in date for every active capture that has none, and ``#New`` where it is bare.

Issue #1517, requirement 024. #1516 made ``create_thing`` date a capture tomorrow and mark it
``#New``; this is the one-off pass that brings the Things captured before then under the same rule,
so no active Thing of the owner's is left without a check-in date. The rule itself lives in
``backend.service.backfill_checkin_dates``: dates are spread a few to a day from tomorrow, oldest
capture first, a Thing with no description is marked ``#New`` as well, and archived Things, Reli's
own records (``INTERNAL_TAGS``) and anything already dated are not touched — which is also why
running it again changes nothing. Additive: no DDL, and no row is removed.

Every row this migration writes is journalled with actor ``claude_scheduled``. The learning pass
filters the journal by actor, and a bulk backfill attributed to ``user`` would read as the owner
having touched every Thing in the graph in one second.

Revision ID: v4_backfill_checkin_dates
Revises: v4_refresh_token_families
Create Date: 2026-09-20
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from alembic import op
from sqlmodel import Session

from backend.service import backfill_checkin_dates

revision: str = "v4_backfill_checkin_dates"
down_revision: str | None = "v4_refresh_token_families"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The session joins the transaction Alembic already opened on this connection, so the flushed
    # rows commit with the revision and nothing here commits on its own.
    with Session(op.get_bind()) as session:
        backfill_checkin_dates(session, now=datetime.now(UTC))


def downgrade() -> None:
    # The dates and marks stay: the journal is append-only, so the record of assigning them cannot
    # be taken back, and a date is what keeps a capture from disappearing.
    pass
