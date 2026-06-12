"""Tests for p0q1r2s3t4u5: backfill expires_at for sweep_findings."""

import sqlite3
from unittest.mock import MagicMock, patch


class TestBackfillDefaultTTLUpgrade:
    def _make_conn(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """CREATE TABLE sweep_findings (
                id TEXT PRIMARY KEY,
                created_at TEXT,
                expires_at TEXT,
                dismissed INTEGER DEFAULT 0
            )"""
        )
        return conn

    def _run_upgrade_on(self, sqlite_conn):
        from backend.alembic.versions.p0q1r2s3t4u5_backfill_default_ttl_for_sweep_findings import upgrade

        mock_conn = MagicMock()
        mock_conn.dialect.name = "sqlite"

        def real_execute(stmt, *args, **kwargs):
            sqlite_conn.execute(str(stmt), *args, **kwargs)

        mock_conn.execute.side_effect = real_execute

        with patch("backend.alembic.versions.p0q1r2s3t4u5_backfill_default_ttl_for_sweep_findings.op") as mock_op:
            mock_op.get_bind.return_value = mock_conn
            upgrade()

        sqlite_conn.commit()

    def test_null_expires_at_non_dismissed_rows_are_backfilled(self):
        """Rows with expires_at IS NULL and dismissed=0 get expires_at set."""
        conn = self._make_conn()
        conn.execute("INSERT INTO sweep_findings VALUES (?, ?, NULL, 0)", ("row1", "2026-04-01T12:00:00"))
        conn.commit()

        self._run_upgrade_on(conn)

        row = conn.execute("SELECT expires_at FROM sweep_findings WHERE id='row1'").fetchone()
        assert row[0] is not None

    def test_dismissed_rows_are_not_backfilled(self):
        """Rows with dismissed=1 must not have expires_at set by the migration."""
        conn = self._make_conn()
        conn.execute("INSERT INTO sweep_findings VALUES (?, ?, NULL, 1)", ("dismissed1", "2026-04-01T12:00:00"))
        conn.commit()

        self._run_upgrade_on(conn)

        row = conn.execute("SELECT expires_at FROM sweep_findings WHERE id='dismissed1'").fetchone()
        assert row[0] is None

    def test_rows_with_existing_expires_at_are_not_overwritten(self):
        """Rows that already have expires_at set must not be touched."""
        conn = self._make_conn()
        original_expiry = "2025-12-31T00:00:00"
        conn.execute("INSERT INTO sweep_findings VALUES (?, ?, ?, 0)", ("row2", "2026-04-01T12:00:00", original_expiry))
        conn.commit()

        self._run_upgrade_on(conn)

        row = conn.execute("SELECT expires_at FROM sweep_findings WHERE id='row2'").fetchone()
        assert row[0] == original_expiry

    def test_idempotent_running_twice_does_not_change_data(self):
        """Running upgrade() twice must not alter expires_at set by first run."""
        conn = self._make_conn()
        conn.execute("INSERT INTO sweep_findings VALUES (?, ?, NULL, 0)", ("row3", "2026-04-01T12:00:00"))
        conn.commit()

        self._run_upgrade_on(conn)
        first_expiry = conn.execute("SELECT expires_at FROM sweep_findings WHERE id='row3'").fetchone()[0]

        self._run_upgrade_on(conn)
        second_expiry = conn.execute("SELECT expires_at FROM sweep_findings WHERE id='row3'").fetchone()[0]

        assert first_expiry == second_expiry

    @patch("backend.alembic.versions.p0q1r2s3t4u5_backfill_default_ttl_for_sweep_findings.op")
    def test_postgresql_dialect_uses_interval_syntax(self, mock_op):
        """PostgreSQL dialect must use INTERVAL syntax, not datetime()."""
        from backend.alembic.versions.p0q1r2s3t4u5_backfill_default_ttl_for_sweep_findings import upgrade

        mock_conn = MagicMock()
        mock_conn.dialect.name = "postgresql"
        mock_op.get_bind.return_value = mock_conn

        upgrade()

        executed_sql = str(mock_conn.execute.call_args[0][0])
        assert "INTERVAL" in executed_sql
        assert "datetime(" not in executed_sql
        assert "dismissed = false" in executed_sql
