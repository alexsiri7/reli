"""Tests for vector_store.py — semantic search fallback behavior."""

import pytest
from unittest.mock import MagicMock, patch

from backend.vector_store import upsert_thing, vector_search, vector_search_with_distances

# Capture real function references at import time, before the conftest autouse
# mock_vector_store fixture replaces these names on the module object.
import backend.vector_store as _vs_module
_REAL_VECTOR_SEARCH = _vs_module.vector_search
_REAL_VECTOR_SEARCH_WITH_DISTANCES = _vs_module.vector_search_with_distances


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


class TestVectorSearchWhereFragmentGuard:
    """SEC-12: verify the WHERE fragment guard actually raises on unexpected fragments.

    The conftest autouse fixture ``mock_vector_store`` replaces the ``vector_search``
    and ``vector_search_with_distances`` module attributes with mocks before each test.
    These tests call the real function objects (captured at import time as
    ``_REAL_VECTOR_SEARCH`` / ``_REAL_VECTOR_SEARCH_WITH_DISTANCES``) directly, so
    the guard code runs even though the module-level names are mocked.
    """

    def test_vector_search_guard_fires_on_unexpected_fragment(self):
        """Guard raises ValueError (not swallowed) when an unknown fragment is present."""
        import backend.vector_store as vs_mod

        with patch.object(vs_mod, "_SQL_WHERE_FRAGMENTS", frozenset()):
            with pytest.raises(ValueError, match="SQL injection guard"):
                # Call the real function object directly (not vs_mod.vector_search
                # which is replaced by the autouse mock at this point).
                _REAL_VECTOR_SEARCH(
                    queries=["test"],
                    n_results=5,
                    active_only=True,  # causes "t.active = true" to enter where_clauses
                )

    def test_vector_search_with_distances_guard_fires_on_unexpected_fragment(self):
        """Guard raises ValueError (not swallowed) when an unknown fragment is present."""
        import backend.vector_store as vs_mod

        with patch.object(vs_mod, "_SQL_WHERE_FRAGMENTS", frozenset()):
            with pytest.raises(ValueError, match="SQL injection guard"):
                # Call the real function object directly (autouse mock does not patch
                # vector_search_with_distances, but we use the captured ref for consistency).
                _REAL_VECTOR_SEARCH_WITH_DISTANCES(
                    query="test",
                    n_results=5,
                    active_only=True,  # causes "t.active = true" to enter where_clauses
                )


class TestUpsertThing:
    def test_logs_error_on_embedder_failure(self):
        """When embedding call fails, upsert_thing logs error but doesn't raise."""
        with patch("backend.vector_store._embedder", side_effect=Exception("Embedding down")):
            # Should not raise
            upsert_thing({"id": "test-1", "title": "Test Thing"})
