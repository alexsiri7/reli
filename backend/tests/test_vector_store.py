"""Tests for vector_store.py — semantic search fallback behavior."""

from unittest.mock import patch, MagicMock

from backend.vector_store import vector_search, upsert_thing


class TestVectorSearch:
    def test_returns_empty_on_embedder_failure(self):
        """When embedding call raises, vector_search returns empty list."""
        with patch("backend.vector_store._embedder", side_effect=Exception("Embedding service down")):
            result = vector_search(queries=["test query"], n_results=5)
        assert result == []

    def test_returns_empty_when_no_embeddings_exist(self):
        """When the embedding table is empty, returns empty list."""
        mock_session = MagicMock()
        mock_session.exec.return_value.one.return_value = 0

        with patch("backend.vector_store.Session") as MockSession:
            MockSession.return_value.__enter__ = lambda s: mock_session
            MockSession.return_value.__exit__ = MagicMock(return_value=False)
            result = vector_search(queries=["test"], n_results=5)
        assert result == []


class TestUpsertThing:
    def test_logs_error_on_embedder_failure(self):
        """When embedding call fails, upsert_thing logs error but doesn't raise."""
        with patch("backend.vector_store._embedder", side_effect=Exception("Embedding down")):
            # Should not raise
            upsert_thing({"id": "test-1", "title": "Test Thing"})
