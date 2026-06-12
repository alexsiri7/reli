# reli:allow-destructive-ddl
"""add user_id to thing_types for per-user scoping (SEC-008)

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-06-01 00:00:00.000000

Data is fully preserved: table is recreated with the same rows; only the
schema changes (new user_id column, new unique constraint).
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "l6m7n8o9p0q1"
down_revision: Union[str, Sequence[str], None] = "k5l6m7n8o9p0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add user_id column; replace UNIQUE(name) with UNIQUE(user_id, name).

    SQLite does not support dropping constraints without recreating the table,
    so we use batch_alter_table with recreate='always' for compatibility.
    All existing rows receive user_id=NULL (visible to all users via user_filter_clause).
    """
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Idempotency guard: if user_id already exists, this migration has already run.
    columns = [c["name"] for c in inspector.get_columns("thing_types")]
    if "user_id" in columns:
        return

    # The initial migration created UNIQUE(name) without an explicit name, so
    # SQLite auto-generated an internal name that varies by installation.
    # Use a naming_convention so Alembic assigns a predictable name to the
    # reflected unnamed constraint during reflection — the template expands to
    # "uq_thing_types_name", which is what drop_constraint targets below.
    naming_convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
    print(
        "[l6m7n8o9p0q1] Applying naming_convention to reflect unnamed UNIQUE(name) constraint "
        "as 'uq_thing_types_name' before dropping it."
    )

    with op.batch_alter_table("thing_types", recreate="always", naming_convention=naming_convention) as batch_op:
        batch_op.add_column(sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.drop_constraint("uq_thing_types_name", type_="unique")
        batch_op.create_unique_constraint("uq_thing_types_user_id_name", ["user_id", "name"])


def downgrade() -> None:
    # WARNING: If users have created thing types with names that duplicate
    # another user's types (allowed by the per-user unique constraint), this
    # downgrade will fail when restoring UNIQUE(name) due to duplicate name values.
    # Manual dedup required before running downgrade:
    #   DELETE FROM thing_types
    #   WHERE user_id IS NOT NULL
    #   AND name IN (SELECT name FROM thing_types GROUP BY name HAVING COUNT(*) > 1);
    with op.batch_alter_table("thing_types", recreate="always") as batch_op:
        batch_op.drop_column("user_id")
        batch_op.drop_constraint("uq_thing_types_user_id_name", type_="unique")
        batch_op.create_unique_constraint("uq_thing_types_name", ["name"])
