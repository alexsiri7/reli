"""Tests for the idempotency guard in m7n8o9p0q1r2_add_confidence_to_sweep_findings."""

from unittest.mock import MagicMock, patch


class TestConfidenceMigrationUpgrade:
    def _run_upgrade(self):
        from backend.alembic.versions.m7n8o9p0q1r2_add_confidence_to_sweep_findings import upgrade

        upgrade()

    @patch("backend.alembic.versions.m7n8o9p0q1r2_add_confidence_to_sweep_findings.op")
    @patch("backend.alembic.versions.m7n8o9p0q1r2_add_confidence_to_sweep_findings.sa")
    def test_skips_when_confidence_already_exists(self, mock_sa, mock_op):
        """upgrade() must return early if confidence column is already present."""
        mock_inspector = MagicMock()
        mock_inspector.get_columns.return_value = [
            {"name": "id"}, {"name": "message"}, {"name": "confidence"}
        ]
        mock_sa.inspect.return_value = mock_inspector
        mock_op.get_bind.return_value = MagicMock()

        self._run_upgrade()

        mock_op.batch_alter_table.assert_not_called()

    @patch("backend.alembic.versions.m7n8o9p0q1r2_add_confidence_to_sweep_findings.op")
    @patch("backend.alembic.versions.m7n8o9p0q1r2_add_confidence_to_sweep_findings.sa")
    def test_runs_migration_when_confidence_absent(self, mock_sa, mock_op):
        """upgrade() must add confidence column when it is not present."""
        mock_inspector = MagicMock()
        mock_inspector.get_columns.return_value = [
            {"name": "id"}, {"name": "message"}, {"name": "priority"}
        ]
        mock_sa.inspect.return_value = mock_inspector
        mock_op.get_bind.return_value = MagicMock()
        mock_batch_op = MagicMock()
        mock_op.batch_alter_table.return_value.__enter__ = MagicMock(return_value=mock_batch_op)
        mock_op.batch_alter_table.return_value.__exit__ = MagicMock(return_value=False)

        self._run_upgrade()

        mock_op.batch_alter_table.assert_called_once_with("sweep_findings")
        mock_batch_op.add_column.assert_called_once()
