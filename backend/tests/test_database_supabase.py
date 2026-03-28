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


class TestSummaryFunctions:
    """Tests for conversation summary helpers in database_supabase."""

    def test_get_latest_summary_returns_first_row(self, mock_supabase_client):
        client, _ = mock_supabase_client
        from backend.database_supabase import get_latest_summary_supabase

        q = MagicMock()
        client.table.return_value = q
        q.select.return_value = q
        q.eq.return_value = q
        q.order.return_value = q
        q.limit.return_value = q
        summary = {"id": 1, "user_id": "u1", "summary_text": "hi", "messages_summarized_up_to": 5}
        q.execute.return_value = MagicMock(data=[summary])

        result = get_latest_summary_supabase("u1")
        assert result == summary

    def test_get_latest_summary_returns_none_when_empty(self, mock_supabase_client):
        client, _ = mock_supabase_client
        from backend.database_supabase import get_latest_summary_supabase

        q = MagicMock()
        client.table.return_value = q
        q.select.return_value = q
        q.eq.return_value = q
        q.order.return_value = q
        q.limit.return_value = q
        q.execute.return_value = MagicMock(data=[])

        assert get_latest_summary_supabase("u1") is None

    def test_create_summary_returns_id(self, mock_supabase_client):
        client, _ = mock_supabase_client
        from backend.database_supabase import create_summary_supabase

        q = MagicMock()
        client.table.return_value = q
        q.insert.return_value = q
        q.execute.return_value = MagicMock(data=[{"id": 42}])

        result = create_summary_supabase("u1", "summary", 10, 100)
        assert result == 42

    def test_create_summary_raises_on_empty_response(self, mock_supabase_client):
        client, _ = mock_supabase_client
        from backend.database_supabase import create_summary_supabase

        q = MagicMock()
        client.table.return_value = q
        q.insert.return_value = q
        q.execute.return_value = MagicMock(data=[])

        with pytest.raises(RuntimeError):
            create_summary_supabase("u1", "summary", 10)

    def test_get_messages_since_summary_with_summary(self, mock_supabase_client):
        client, _ = mock_supabase_client
        from backend.database_supabase import get_messages_since_summary_supabase

        # Mock get_latest_summary_supabase via the table call
        summary_q = MagicMock()
        chat_q = MagicMock()

        call_count = [0]

        def table_router(name):
            call_count[0] += 1
            if name == "conversation_summaries":
                return summary_q
            return chat_q

        client.table.side_effect = table_router

        summary_q.select.return_value = summary_q
        summary_q.eq.return_value = summary_q
        summary_q.order.return_value = summary_q
        summary_q.limit.return_value = summary_q
        summary_q.execute.return_value = MagicMock(
            data=[{"id": 1, "messages_summarized_up_to": 5}]
        )

        chat_q.select.return_value = chat_q
        chat_q.eq.return_value = chat_q
        chat_q.order.return_value = chat_q
        chat_q.gt.return_value = chat_q
        messages = [{"id": 6, "role": "user", "content": "hi"}]
        chat_q.execute.return_value = MagicMock(data=messages)

        result = get_messages_since_summary_supabase("u1")
        assert result == messages

    def test_get_message_count_since_summary(self, mock_supabase_client):
        client, _ = mock_supabase_client
        from backend.database_supabase import get_message_count_since_summary_supabase

        summary_q = MagicMock()
        chat_q = MagicMock()

        def table_router(name):
            if name == "conversation_summaries":
                return summary_q
            return chat_q

        client.table.side_effect = table_router

        summary_q.select.return_value = summary_q
        summary_q.eq.return_value = summary_q
        summary_q.order.return_value = summary_q
        summary_q.limit.return_value = summary_q
        summary_q.execute.return_value = MagicMock(data=[])  # no summary

        chat_q.select.return_value = chat_q
        chat_q.eq.return_value = chat_q
        chat_q.limit.return_value = chat_q
        chat_q.execute.return_value = MagicMock(count=7)

        result = get_message_count_since_summary_supabase("u1")
        assert result == 7


class TestDatabaseGatingForSummaries:
    """Verify database.py dispatches summary functions to supabase backend."""

    def test_get_latest_summary_dispatches(self, mock_supabase_client, monkeypatch):
        monkeypatch.setattr("backend.database.settings.STORAGE_BACKEND", "supabase")
        from unittest.mock import patch as mp

        with mp("backend.database_supabase.get_latest_summary_supabase", return_value=None) as mock_fn:
            from backend.database import get_latest_summary

            result = get_latest_summary("u1")
            mock_fn.assert_called_once_with("u1")
            assert result is None

    def test_create_summary_dispatches(self, mock_supabase_client, monkeypatch):
        monkeypatch.setattr("backend.database.settings.STORAGE_BACKEND", "supabase")
        from unittest.mock import patch as mp

        with mp("backend.database_supabase.create_summary_supabase", return_value=99) as mock_fn:
            from backend.database import create_summary

            result = create_summary("u1", "text", 10, 200)
            mock_fn.assert_called_once_with("u1", "text", 10, 200)
            assert result == 99

    def test_get_message_count_dispatches(self, mock_supabase_client, monkeypatch):
        monkeypatch.setattr("backend.database.settings.STORAGE_BACKEND", "supabase")
        from unittest.mock import patch as mp

        with mp("backend.database_supabase.get_message_count_since_summary_supabase", return_value=3) as mock_fn:
            from backend.database import get_message_count_since_summary

            result = get_message_count_since_summary("u1")
            mock_fn.assert_called_once_with("u1")
            assert result == 3


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
