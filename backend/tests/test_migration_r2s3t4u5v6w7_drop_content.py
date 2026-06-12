"""Unit tests for migration r2s3t4u5v6w7 — drop content from thing_embeddings.

Tests column name correctness in upgrade/downgrade without running Alembic,
mirroring the pattern used in test_migration_scrub_pii.py.
"""

from unittest.mock import patch

import sqlalchemy as sa


def test_upgrade_drops_correct_column():
    """upgrade() drops the 'content' column from 'thing_embeddings'."""
    with patch("alembic.op.drop_column") as mock_drop:
        from backend.alembic.versions.r2s3t4u5v6w7_drop_content_from_thing_embeddings import upgrade

        upgrade()

    mock_drop.assert_called_once_with("thing_embeddings", "content")


def test_downgrade_adds_correct_column():
    """downgrade() re-adds 'content' column to 'thing_embeddings' with nullable=False, server_default=''."""
    with patch("alembic.op.add_column") as mock_add:
        from backend.alembic.versions.r2s3t4u5v6w7_drop_content_from_thing_embeddings import downgrade

        downgrade()

    assert mock_add.call_count == 1
    args = mock_add.call_args
    table_name = args[0][0]
    column = args[0][1]

    assert table_name == "thing_embeddings"
    assert column.name == "content"
    assert isinstance(column.type, sa.Text)
    assert column.nullable is False
    assert column.server_default.arg == ""


def test_revision_chain():
    """Revision metadata is correct and points to the right predecessor."""
    from backend.alembic.versions.r2s3t4u5v6w7_drop_content_from_thing_embeddings import (
        down_revision,
        revision,
    )

    assert revision == "r2s3t4u5v6w7"
    assert down_revision == "q1r2s3t4u5v6"
