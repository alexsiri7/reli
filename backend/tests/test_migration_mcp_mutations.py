"""Tests for the idempotency guard in i3j4k5l6m7n8_add_mcp_mutations_table."""

from unittest.mock import MagicMock, patch


class TestMcpMutationsMigrationUpgrade:
    def _run_upgrade(self):
        from backend.alembic.versions.i3j4k5l6m7n8_add_mcp_mutations_table import upgrade

        upgrade()

    @patch("backend.alembic.versions.i3j4k5l6m7n8_add_mcp_mutations_table.op")
    @patch("backend.alembic.versions.i3j4k5l6m7n8_add_mcp_mutations_table.sa")
    def test_skips_create_when_table_exists(self, mock_sa, mock_op):
        """upgrade() must not call op.create_table when mcp_mutations already exists."""
        mock_inspector = MagicMock()
        mock_inspector.has_table.return_value = True
        mock_sa.inspect.return_value = mock_inspector
        mock_op.get_bind.return_value = MagicMock()

        self._run_upgrade()

        mock_op.create_table.assert_not_called()
        mock_op.create_index.assert_not_called()

    @patch("backend.alembic.versions.i3j4k5l6m7n8_add_mcp_mutations_table.op")
    @patch("backend.alembic.versions.i3j4k5l6m7n8_add_mcp_mutations_table.sa")
    def test_creates_table_when_absent(self, mock_sa, mock_op):
        """upgrade() must call op.create_table when mcp_mutations does not exist."""
        mock_inspector = MagicMock()
        mock_inspector.has_table.return_value = False
        mock_sa.inspect.return_value = mock_inspector
        mock_op.get_bind.return_value = MagicMock()

        self._run_upgrade()

        mock_op.create_table.assert_called_once()
        assert mock_op.create_index.call_count == 2
