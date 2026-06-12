"""Tests for the idempotency guard in l6m7n8o9p0q1_add_user_id_to_thing_types."""

from unittest.mock import MagicMock, patch


class TestThingTypesMigrationUpgrade:
    def _run_upgrade(self):
        from backend.alembic.versions.l6m7n8o9p0q1_add_user_id_to_thing_types import upgrade

        upgrade()

    @patch("backend.alembic.versions.l6m7n8o9p0q1_add_user_id_to_thing_types.op")
    @patch("backend.alembic.versions.l6m7n8o9p0q1_add_user_id_to_thing_types.sa")
    def test_skips_when_user_id_already_exists(self, mock_sa, mock_op):
        """upgrade() must return early if user_id column already present."""
        mock_inspector = MagicMock()
        mock_inspector.get_columns.return_value = [{"name": "id"}, {"name": "name"}, {"name": "user_id"}]
        mock_sa.inspect.return_value = mock_inspector
        mock_op.get_bind.return_value = MagicMock()

        self._run_upgrade()

        mock_op.batch_alter_table.assert_not_called()

    @patch("backend.alembic.versions.l6m7n8o9p0q1_add_user_id_to_thing_types.op")
    @patch("backend.alembic.versions.l6m7n8o9p0q1_add_user_id_to_thing_types.sa")
    def test_runs_migration_when_user_id_absent(self, mock_sa, mock_op):
        """upgrade() must call batch_alter_table when user_id is not present."""
        mock_inspector = MagicMock()
        mock_inspector.get_columns.return_value = [{"name": "id"}, {"name": "name"}]
        mock_sa.inspect.return_value = mock_inspector
        mock_op.get_bind.return_value = MagicMock()
        mock_batch_op = MagicMock()
        mock_op.batch_alter_table.return_value.__enter__ = MagicMock(return_value=mock_batch_op)
        mock_op.batch_alter_table.return_value.__exit__ = MagicMock(return_value=False)

        self._run_upgrade()

        mock_op.batch_alter_table.assert_called_once()
        call_kwargs = mock_op.batch_alter_table.call_args
        assert call_kwargs.kwargs.get("naming_convention") == {"uq": "uq_%(table_name)s_%(column_0_name)s"}
        assert call_kwargs.kwargs.get("recreate") == "always"
        mock_batch_op.add_column.assert_called_once()
        mock_batch_op.drop_constraint.assert_called_once_with("uq_thing_types_name", type_="unique")
        mock_batch_op.create_unique_constraint.assert_called_once_with(
            "uq_thing_types_user_id_name", ["user_id", "name"]
        )
