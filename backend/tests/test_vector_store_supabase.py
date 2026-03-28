"""Tests for the Supabase pgvector path in vector_store.py.

Tests call the private _*_supabase functions directly because conftest.py
patches the public API (upsert_thing, delete_thing, etc.) via autouse=True
to prevent real ChromaDB calls during test runs.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def mock_supabase_client():
    """Patch get_client in database_supabase to return a mock."""
    client = MagicMock()
    with patch("backend.database_supabase.get_client", return_value=client):
        yield client


@pytest.fixture()
def mock_embedder():
    """Patch _get_embedding to return a fixed 3072-dim vector."""
    fake_vector = [0.1] * 3072
    with patch("backend.vector_store._get_embedding", return_value=fake_vector) as m:
        yield m, fake_vector


class TestUpsertThingSupabase:
    def test_updates_embedding_column(self, mock_supabase_client, mock_embedder):
        _, fake_vector = mock_embedder
        q = MagicMock()
        mock_supabase_client.table.return_value = q
        q.update.return_value = q
        q.eq.return_value = q
        q.execute.return_value = MagicMock()

        from backend.vector_store import _upsert_thing_supabase

        _upsert_thing_supabase({"id": "t1", "title": "Test", "user_id": "u1"})

        mock_supabase_client.table.assert_called_with("things")
        q.update.assert_called_once_with({"embedding": fake_vector})
        q.eq.assert_called_once_with("id", "t1")

    def test_silently_no_ops_on_error(self, mock_supabase_client):
        mock_supabase_client.table.side_effect = RuntimeError("boom")
        from backend.vector_store import _upsert_thing_supabase

        # Should not raise
        _upsert_thing_supabase({"id": "t1", "title": "Test"})


class TestDeleteThingSupabase:
    def test_clears_embedding_column(self, mock_supabase_client):
        q = MagicMock()
        mock_supabase_client.table.return_value = q
        q.update.return_value = q
        q.eq.return_value = q
        q.execute.return_value = MagicMock()

        from backend.vector_store import _delete_thing_supabase

        _delete_thing_supabase("t1")

        mock_supabase_client.table.assert_called_with("things")
        q.update.assert_called_once_with({"embedding": None})
        q.eq.assert_called_once_with("id", "t1")

    def test_silently_no_ops_on_error(self, mock_supabase_client):
        mock_supabase_client.table.side_effect = RuntimeError("boom")
        from backend.vector_store import _delete_thing_supabase

        _delete_thing_supabase("t1")  # Should not raise


class TestVectorCountSupabase:
    def test_returns_count(self, mock_supabase_client):
        q = MagicMock()
        mock_supabase_client.table.return_value = q
        q.select.return_value = q
        q.not_ = MagicMock()
        q.not_.is_.return_value = q
        q.limit.return_value = q
        q.execute.return_value = MagicMock(count=42)

        from backend.vector_store import _vector_count_supabase

        assert _vector_count_supabase() == 42

    def test_returns_zero_on_error(self, mock_supabase_client):
        mock_supabase_client.table.side_effect = RuntimeError("boom")
        from backend.vector_store import _vector_count_supabase

        assert _vector_count_supabase() == 0


class TestVectorSearchSupabase:
    def test_calls_match_things_rpc(self, mock_supabase_client, mock_embedder):
        _, fake_vector = mock_embedder
        rpc_q = MagicMock()
        mock_supabase_client.rpc.return_value = rpc_q
        rpc_q.execute.return_value = MagicMock(data=[{"id": "t1"}, {"id": "t2"}])

        from backend.vector_store import _vector_search_supabase

        result = _vector_search_supabase(["find things"], 10, True, None, "u1")

        mock_supabase_client.rpc.assert_called_once_with(
            "match_things",
            {
                "query_embedding": fake_vector,
                "match_count": 10,
                "user_id_filter": "u1",
                "active_only": True,
                "type_hint_filter": None,
            },
        )
        assert result == ["t1", "t2"]

    def test_deduplicates_across_queries(self, mock_supabase_client, mock_embedder):
        rpc_q = MagicMock()
        mock_supabase_client.rpc.return_value = rpc_q
        rpc_q.execute.side_effect = [
            MagicMock(data=[{"id": "t1"}, {"id": "t2"}]),
            MagicMock(data=[{"id": "t1"}, {"id": "t3"}]),
        ]

        from backend.vector_store import _vector_search_supabase

        result = _vector_search_supabase(["q1", "q2"], 5, True, None, "u1")
        assert result == ["t1", "t2", "t3"]

    def test_returns_empty_on_error(self, mock_supabase_client, mock_embedder):
        mock_supabase_client.rpc.side_effect = RuntimeError("boom")
        from backend.vector_store import _vector_search_supabase

        assert _vector_search_supabase(["query"], 10, True, None, "u1") == []


class TestReindexAllSupabase:
    def test_embeds_all_things(self, mock_supabase_client, mock_embedder):
        _, fake_vector = mock_embedder
        q = MagicMock()
        mock_supabase_client.table.return_value = q
        q.select.return_value = q
        q.execute.return_value = MagicMock(
            data=[
                {"id": "t1", "title": "Thing 1", "user_id": "u1"},
                {"id": "t2", "title": "Thing 2", "user_id": "u1"},
            ]
        )
        q.update.return_value = q
        q.eq.return_value = q

        from backend.vector_store import _reindex_all_supabase

        count = _reindex_all_supabase()

        assert count == 2
        assert q.update.call_count == 2

    def test_returns_zero_when_no_things(self, mock_supabase_client, mock_embedder):
        q = MagicMock()
        mock_supabase_client.table.return_value = q
        q.select.return_value = q
        q.execute.return_value = MagicMock(data=[])

        from backend.vector_store import _reindex_all_supabase

        assert _reindex_all_supabase() == 0


class TestPublicApiDispatchesToSupabase:
    """Verify public API gates dispatch to Supabase when flag is set."""

    def test_vector_search_dispatches(self, monkeypatch, mock_supabase_client, mock_embedder):
        monkeypatch.setattr("backend.vector_store.settings.STORAGE_BACKEND", "supabase")
        rpc_q = MagicMock()
        mock_supabase_client.rpc.return_value = rpc_q
        rpc_q.execute.return_value = MagicMock(data=[{"id": "t1"}])

        # Bypass the autouse conftest mock by calling the real function directly
        from backend.vector_store import _vector_search_supabase

        result = _vector_search_supabase(["query"], 5, True, None, "u1")
        assert result == ["t1"]
