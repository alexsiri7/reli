"""Tests for the idempotency guard in h2i3j4k5l6m7_add_merge_history_expires_at."""

from unittest.mock import MagicMock, patch


class TestMergeHistoryExpiresAtMigrationUpgrade:
    def _run_upgrade(self):
        from backend.alembic.versions.h2i3j4k5l6m7_add_merge_history_expires_at import upgrade

        upgrade()

    @patch("backend.alembic.versions.h2i3j4k5l6m7_add_merge_history_expires_at.op")
    @patch("backend.alembic.versions.h2i3j4k5l6m7_add_merge_history_expires_at.sa")
    def test_skips_when_expires_at_already_exists(self, mock_sa, mock_op):
        """upgrade() must return early if expires_at column is already present."""
        mock_inspector = MagicMock()
        mock_inspector.get_columns.return_value = [
            {"name": "id"}, {"name": "created_at"}, {"name": "expires_at"}
        ]
        mock_sa.inspect.return_value = mock_inspector
        mock_op.get_bind.return_value = MagicMock()

        self._run_upgrade()

        mock_op.batch_alter_table.assert_not_called()

    @patch("backend.alembic.versions.h2i3j4k5l6m7_add_merge_history_expires_at.op")
    @patch("backend.alembic.versions.h2i3j4k5l6m7_add_merge_history_expires_at.sa")
    def test_runs_migration_when_expires_at_absent(self, mock_sa, mock_op):
        """upgrade() must add expires_at column when it is not present."""
        mock_inspector = MagicMock()
        mock_inspector.get_columns.return_value = [
            {"name": "id"}, {"name": "keep_id"}, {"name": "created_at"}
        ]
        mock_sa.inspect.return_value = mock_inspector
        mock_op.get_bind.return_value = MagicMock()
        mock_batch_op = MagicMock()
        mock_op.batch_alter_table.return_value.__enter__ = MagicMock(return_value=mock_batch_op)
        mock_op.batch_alter_table.return_value.__exit__ = MagicMock(return_value=False)

        self._run_upgrade()

        mock_op.batch_alter_table.assert_called_once_with("merge_history")
        mock_batch_op.add_column.assert_called_once()
