"""Tests for the Supabase database backend gating and module."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def _use_supabase(monkeypatch):
    """Patch settings so STORAGE_BACKEND=supabase with dummy credentials."""
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "test-key")


@pytest.fixture()
def mock_supabase_client():
    """Return a mock Supabase client and patch create_client to return it."""
    client = MagicMock()
    with patch("backend.database_supabase.create_client", return_value=client) as mock_create:
        # Reset the module-level singleton so create_client is called again.
        with patch("backend.database_supabase._client", None):
            yield client, mock_create


class TestGetClient:
    def test_creates_client_with_settings(self, mock_supabase_client):
        client, mock_create = mock_supabase_client
        from backend.database_supabase import get_client

        result = get_client()
        assert result is client
        mock_create.assert_called_once()

    def test_singleton_returns_same_client(self, mock_supabase_client):
        client, mock_create = mock_supabase_client
        from backend.database_supabase import get_client

        c1 = get_client()
        c2 = get_client()
        assert c1 is c2
        assert mock_create.call_count == 1


class TestSupabaseDb:
    def test_context_manager_yields_client(self, mock_supabase_client):
        client, _ = mock_supabase_client
        from backend.database_supabase import supabase_db

        with supabase_db() as c:
            assert c is client


class TestInitDbSupabase:
    def test_probes_all_expected_tables(self, mock_supabase_client):
        client, _ = mock_supabase_client
        from backend.database_supabase import _EXPECTED_TABLES, init_db_supabase

        # Set up the chain: client.table(...).select(...).limit(...).execute()
        mock_query = MagicMock()
        client.table.return_value = mock_query
        mock_query.select.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[], count=0)

        init_db_supabase()

        # Every expected table should have been probed
        probed_tables = [call.args[0] for call in client.table.call_args_list]
        assert probed_tables == _EXPECTED_TABLES


class TestCleanOrphanRelationships:
    def test_deletes_orphans(self, mock_supabase_client):
        client, _ = mock_supabase_client
        from backend.database_supabase import clean_orphan_relationships_supabase

        # Set up things table response
        things_query = MagicMock()
        rels_query = MagicMock()
        delete_query = MagicMock()

        def table_router(name):
            if name == "things":
                return things_query
            return rels_query

        client.table.side_effect = table_router

        # things: only "t1" exists
        things_query.select.return_value = things_query
        things_query.execute.return_value = MagicMock(data=[{"id": "t1"}])

        # relationships: one valid, one orphan
        rels_query.select.return_value = rels_query
        rels_query.execute.return_value = MagicMock(
            data=[
                {"id": "r1", "from_thing_id": "t1", "to_thing_id": "t1"},
                {"id": "r2", "from_thing_id": "t1", "to_thing_id": "t_gone"},
            ]
        )
        rels_query.delete.return_value = delete_query
        delete_query.eq.return_value = delete_query
        delete_query.execute.return_value = MagicMock()

        count, ids = clean_orphan_relationships_supabase()
        assert count == 1
        assert ids == ["r2"]

    def test_no_orphans(self, mock_supabase_client):
        client, _ = mock_supabase_client
        from backend.database_supabase import clean_orphan_relationships_supabase

        things_query = MagicMock()
        rels_query = MagicMock()

        def table_router(name):
            if name == "things":
                return things_query
            return rels_query

        client.table.side_effect = table_router

        things_query.select.return_value = things_query
        things_query.execute.return_value = MagicMock(data=[{"id": "t1"}])

        rels_query.select.return_value = rels_query
        rels_query.execute.return_value = MagicMock(data=[{"id": "r1", "from_thing_id": "t1", "to_thing_id": "t1"}])

        count, ids = clean_orphan_relationships_supabase()
        assert count == 0
        assert ids == []


class TestDatabaseGating:
    """Verify that database.py dispatches to supabase when flag is set."""

    def test_db_yields_sqlite_by_default(self, tmp_path, monkeypatch):
        """Default STORAGE_BACKEND=sqlite yields sqlite3.Connection."""
        import sqlite3

        monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
        monkeypatch.setattr("backend.database.DB_PATH", tmp_path / "test.db")
        # Re-import to pick up patched settings
        from backend.database import db

        with db() as conn:
            assert isinstance(conn, sqlite3.Connection)

    def test_init_db_supabase_dispatches(self, mock_supabase_client, monkeypatch):
        """init_db() dispatches to init_db_supabase when flag is set."""
        monkeypatch.setattr("backend.database.settings.STORAGE_BACKEND", "supabase")
        client, _ = mock_supabase_client

        mock_query = MagicMock()
        client.table.return_value = mock_query
        mock_query.select.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[], count=0)

        from backend.database import init_db

        init_db()

        # Verify it probed tables (i.e., used supabase path)
        assert client.table.call_count > 0

    def test_clean_orphans_supabase_dispatches(self, mock_supabase_client, monkeypatch):
        """clean_orphan_relationships() dispatches to supabase when flag is set."""
        monkeypatch.setattr("backend.database.settings.STORAGE_BACKEND", "supabase")
        client, _ = mock_supabase_client

        things_query = MagicMock()
        rels_query = MagicMock()

        def table_router(name):
            if name == "things":
                return things_query
            return rels_query

        client.table.side_effect = table_router
        things_query.select.return_value = things_query
        things_query.execute.return_value = MagicMock(data=[])
        rels_query.select.return_value = rels_query
        rels_query.execute.return_value = MagicMock(data=[])

        from backend.database import clean_orphan_relationships

        count, ids = clean_orphan_relationships()
        assert count == 0
        assert ids == []
