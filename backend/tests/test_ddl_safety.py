"""Tests for the destructive DDL safety guard in Alembic migrations."""

import os
import textwrap

import pytest

from backend.alembic.safety import (
    DestructiveDDLFound,
    _find_destructive_ops_in_source,
)


class TestFindDestructiveOps:
    """Test AST-based detection of destructive operations."""

    def test_detects_drop_table(self):
        source = textwrap.dedent("""\
            from alembic import op

            def upgrade():
                op.drop_table('users')
        """)
        findings = _find_destructive_ops_in_source(source)
        assert len(findings) == 1
        assert "drop_table" in findings[0]
        assert "users" in findings[0]

    def test_detects_drop_column(self):
        source = textwrap.dedent("""\
            from alembic import op

            def upgrade():
                op.drop_column('users', 'email')
        """)
        findings = _find_destructive_ops_in_source(source)
        assert len(findings) == 1
        assert "drop_column" in findings[0]

    def test_detects_drop_index(self):
        source = textwrap.dedent("""\
            from alembic import op

            def upgrade():
                op.drop_index('ix_users_email', table_name='users')
        """)
        findings = _find_destructive_ops_in_source(source)
        assert len(findings) == 1
        assert "drop_index" in findings[0]

    def test_detects_drop_constraint(self):
        source = textwrap.dedent("""\
            from alembic import op

            def upgrade():
                op.drop_constraint('uq_users_email', 'users')
        """)
        findings = _find_destructive_ops_in_source(source)
        assert len(findings) == 1
        assert "drop_constraint" in findings[0]

    def test_detects_execute_drop_table_sql(self):
        source = textwrap.dedent("""\
            from alembic import op

            def upgrade():
                op.execute("DROP TABLE users")
        """)
        findings = _find_destructive_ops_in_source(source)
        assert len(findings) == 1
        assert "DROP TABLE" in findings[0]

    def test_detects_execute_truncate_sql(self):
        source = textwrap.dedent("""\
            from alembic import op

            def upgrade():
                op.execute("TRUNCATE TABLE users")
        """)
        findings = _find_destructive_ops_in_source(source)
        assert len(findings) == 1
        assert "TRUNCATE" in findings[0]

    def test_detects_execute_delete_from_sql(self):
        source = textwrap.dedent("""\
            from alembic import op

            def upgrade():
                op.execute("DELETE FROM users WHERE active = false")
        """)
        findings = _find_destructive_ops_in_source(source)
        assert len(findings) == 1
        assert "DELETE FROM" in findings[0]

    def test_detects_multiple_destructive_ops(self):
        source = textwrap.dedent("""\
            from alembic import op

            def upgrade():
                op.drop_column('users', 'old_field')
                op.drop_table('deprecated_table')
        """)
        findings = _find_destructive_ops_in_source(source)
        assert len(findings) == 2

    def test_ignores_safe_operations(self):
        source = textwrap.dedent("""\
            from alembic import op
            import sqlalchemy as sa

            def upgrade():
                op.create_table('new_table',
                    sa.Column('id', sa.Integer(), primary_key=True),
                )
                op.add_column('users', sa.Column('bio', sa.Text()))
                op.create_index('ix_users_bio', 'users', ['bio'])
        """)
        findings = _find_destructive_ops_in_source(source)
        assert findings == []

    def test_ignores_downgrade_function(self):
        source = textwrap.dedent("""\
            from alembic import op

            def upgrade():
                op.create_table('new_table')

            def downgrade():
                op.drop_table('new_table')
        """)
        findings = _find_destructive_ops_in_source(source)
        assert findings == []

    def test_handles_syntax_error(self):
        source = "this is not valid python {{{"
        findings = _find_destructive_ops_in_source(source)
        assert findings == []

    def test_handles_empty_source(self):
        findings = _find_destructive_ops_in_source("")
        assert findings == []


class TestCheckPendingMigrations:
    """Integration-style tests using a mock ScriptDirectory."""

    def test_allows_when_env_var_set(self, tmp_path, monkeypatch):
        """ALLOW_DESTRUCTIVE_DDL=true bypasses the check entirely."""
        from unittest.mock import MagicMock

        from backend.alembic.safety import check_pending_migrations

        monkeypatch.setenv("ALLOW_DESTRUCTIVE_DDL", "true")
        mock_script_dir = MagicMock()
        # Should not raise even with a mocked script dir
        check_pending_migrations(mock_script_dir, current_heads=set())

    def test_env_var_case_insensitive(self, monkeypatch):
        from unittest.mock import MagicMock

        from backend.alembic.safety import check_pending_migrations

        for value in ("TRUE", "True", "1", "yes", "YES"):
            monkeypatch.setenv("ALLOW_DESTRUCTIVE_DDL", value)
            mock_script_dir = MagicMock()
            check_pending_migrations(mock_script_dir, current_heads=set())

    def test_blocks_destructive_migration(self, tmp_path, monkeypatch):
        """A pending migration with drop_table should raise."""
        monkeypatch.delenv("ALLOW_DESTRUCTIVE_DDL", raising=False)

        # Create a fake migration file
        versions_dir = tmp_path / "versions"
        versions_dir.mkdir()
        migration_file = versions_dir / "abc123_drop_users.py"
        migration_file.write_text(textwrap.dedent("""\
            revision = 'abc123'
            down_revision = None

            from alembic import op

            def upgrade():
                op.drop_table('users')

            def downgrade():
                op.create_table('users')
        """))

        from unittest.mock import MagicMock

        from backend.alembic.safety import check_pending_migrations

        # Mock script directory
        mock_rev = MagicMock()
        mock_rev.revision = "abc123"
        mock_rev.doc = "drop users"
        mock_rev.path = str(migration_file)

        mock_script_dir = MagicMock()
        mock_script_dir.walk_revisions.return_value = [mock_rev]
        mock_script_dir.get_heads.return_value = ("abc123",)

        with pytest.raises(DestructiveDDLFound) as exc_info:
            check_pending_migrations(mock_script_dir, current_heads=set())

        error_msg = str(exc_info.value)
        assert "drop_table" in error_msg
        assert "ALLOW_DESTRUCTIVE_DDL" in error_msg

    def test_passes_safe_migration(self, tmp_path, monkeypatch):
        """A pending migration with only safe ops should pass."""
        monkeypatch.delenv("ALLOW_DESTRUCTIVE_DDL", raising=False)

        versions_dir = tmp_path / "versions"
        versions_dir.mkdir()
        migration_file = versions_dir / "def456_add_column.py"
        migration_file.write_text(textwrap.dedent("""\
            revision = 'def456'
            down_revision = None

            from alembic import op
            import sqlalchemy as sa

            def upgrade():
                op.add_column('users', sa.Column('bio', sa.Text()))

            def downgrade():
                op.drop_column('users', 'bio')
        """))

        from unittest.mock import MagicMock

        from backend.alembic.safety import check_pending_migrations

        mock_rev = MagicMock()
        mock_rev.revision = "def456"
        mock_rev.doc = "add column"
        mock_rev.path = str(migration_file)

        mock_script_dir = MagicMock()
        mock_script_dir.walk_revisions.return_value = [mock_rev]
        mock_script_dir.get_heads.return_value = ("def456",)

        # Should not raise
        check_pending_migrations(mock_script_dir, current_heads=set())

    def test_skips_already_applied(self, tmp_path, monkeypatch):
        """Already-applied revisions should be skipped."""
        monkeypatch.delenv("ALLOW_DESTRUCTIVE_DDL", raising=False)

        versions_dir = tmp_path / "versions"
        versions_dir.mkdir()
        migration_file = versions_dir / "abc123_drop_users.py"
        migration_file.write_text(textwrap.dedent("""\
            revision = 'abc123'
            down_revision = None

            from alembic import op

            def upgrade():
                op.drop_table('users')

            def downgrade():
                pass
        """))

        from unittest.mock import MagicMock

        from backend.alembic.safety import check_pending_migrations

        mock_rev = MagicMock()
        mock_rev.revision = "abc123"
        mock_rev.doc = "drop users"
        mock_rev.path = str(migration_file)

        mock_script_dir = MagicMock()
        mock_script_dir.walk_revisions.return_value = [mock_rev]

        # abc123 is already applied — should not raise
        check_pending_migrations(
            mock_script_dir, current_heads={"abc123"}
        )
