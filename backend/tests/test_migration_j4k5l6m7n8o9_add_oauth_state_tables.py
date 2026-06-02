"""Tests for the idempotency guard in j4k5l6m7n8o9_add_oauth_state_tables."""

from unittest.mock import MagicMock, patch


class TestOAuthStateTablesMigrationUpgrade:
    def _run_upgrade(self):
        from backend.alembic.versions.j4k5l6m7n8o9_add_oauth_state_tables import upgrade

        upgrade()

    @patch("backend.alembic.versions.j4k5l6m7n8o9_add_oauth_state_tables.op")
    @patch("backend.alembic.versions.j4k5l6m7n8o9_add_oauth_state_tables.sa")
    def test_skips_create_when_tables_exist(self, mock_sa, mock_op):
        """upgrade() must not call op.create_table when mcp_oauth_sessions already exists."""
        mock_inspector = MagicMock()
        mock_inspector.has_table.return_value = True
        mock_sa.inspect.return_value = mock_inspector
        mock_op.get_bind.return_value = MagicMock()

        self._run_upgrade()

        mock_op.create_table.assert_not_called()
        mock_op.create_index.assert_not_called()

    @patch("backend.alembic.versions.j4k5l6m7n8o9_add_oauth_state_tables.op")
    @patch("backend.alembic.versions.j4k5l6m7n8o9_add_oauth_state_tables.sa")
    def test_creates_tables_when_absent(self, mock_sa, mock_op):
        """upgrade() must create all 5 tables when mcp_oauth_sessions does not exist."""
        mock_inspector = MagicMock()
        mock_inspector.has_table.return_value = False
        mock_sa.inspect.return_value = mock_inspector
        mock_op.get_bind.return_value = MagicMock()

        self._run_upgrade()

        assert mock_op.create_table.call_count == 5
        assert mock_op.create_index.call_count == 5
