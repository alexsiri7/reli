"""Tests for vector_store.py — semantic search fallback behavior."""

from unittest.mock import MagicMock, patch

import pytest

from backend.vector_store import _build_where_sql, upsert_thing, vector_search


class TestBuildWhereSql:
    """Unit tests for _build_where_sql SEC-12 guard (all three code paths)."""

    def test_empty_clauses_returns_empty_string(self):
        assert _build_where_sql([]) == ""

    def test_single_valid_clause(self):
        result = _build_where_sql(["t.active = true"])
        assert result == "WHERE t.active = true"

    def test_multiple_valid_clauses(self):
        result = _build_where_sql(["t.active = true", "t.type_hint = :type_hint"])
        assert result == "WHERE t.active = true AND t.type_hint = :type_hint"

    def test_rejects_unexpected_fragment(self):
        with pytest.raises(ValueError, match="SQL injection guard"):
            _build_where_sql(["1=1; DROP TABLE things--"])

    def test_rejects_mix_of_valid_and_invalid(self):
        with pytest.raises(ValueError, match="SQL injection guard"):
            _build_where_sql(["t.active = true", "EVIL CLAUSE"])


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

    def test_upsert_sql_does_not_reference_content(self):
        """INSERT SQL must not include content column (removed in r2s3t4u5v6w7)."""
        captured_sql: list[str] = []
        mock_session = MagicMock()
        mock_session.execute.side_effect = lambda stmt, *a, **kw: captured_sql.append(str(stmt))

        with patch("backend.vector_store._embedder", return_value=[[0.1] * 1536]):
            with patch("backend.vector_store._engine_mod") as mock_engine_mod:
                mock_engine_mod.engine = MagicMock()
                with patch("backend.vector_store.Session") as MockSession:
                    MockSession.return_value.__enter__ = lambda s: mock_session
                    MockSession.return_value.__exit__ = MagicMock(return_value=False)
                    upsert_thing({"id": "t1", "title": "Test"})

        assert captured_sql, "session.execute was not called"
        assert "content" not in captured_sql[0].lower(), (
            "INSERT SQL must not reference the removed content column"
        )
