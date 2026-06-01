"""Scrub PII (email, google_id) from user anchor Thing.data (SEC-015)

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-05-31 00:00:00.000000
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k5l6m7n8o9p0"
down_revision: Union[str, Sequence[str], None] = "j4k5l6m7n8o9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PII_KEYS = {"email", "google_id"}


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, data FROM things WHERE type_hint = 'person' AND user_id IS NOT NULL AND data IS NOT NULL")
    ).fetchall()

    for row in rows:
        raw = row[1]
        if not raw:
            continue
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            print(f"[k5l6m7n8o9p0] WARNING: skipping row id={row[0]} — data is not valid JSON, PII not scrubbed")
            continue
        if not isinstance(data, dict):
            t = type(data).__name__
            print(f"[k5l6m7n8o9p0] WARNING: skipping row id={row[0]} — data is not a dict (type={t}), PII not scrubbed")
            continue
        if not any(k in data for k in _PII_KEYS):
            continue
        for k in _PII_KEYS:
            data.pop(k, None)
        # Empty dict after PII removal → NULL, consistent with new data=None default in auth.py
        new_val = json.dumps(data) if data else None
        conn.execute(
            sa.text("UPDATE things SET data = :data WHERE id = :id"),
            {"data": new_val, "id": row[0]},
        )


def downgrade() -> None:
    # PII scrubbing is intentionally not reversible
    pass
