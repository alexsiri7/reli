"""Tests for vector_store functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.vector_store import vector_search_with_scores


class TestVectorSearchWithScores:
    def test_returns_similarity_scores(self):
        """Converts cosine distance to similarity (1 - distance)."""
        mock_collection = MagicMock()
        mock_collection.count.return_value = 5
        mock_collection.query.return_value = {
            "ids": [["id-a", "id-b"]],
            "distances": [[0.2, 0.6]],
        }

        with patch("backend.vector_store._get_collection", return_value=mock_collection):
            scores = vector_search_with_scores(queries=["test query"], n_results=5)

        assert scores == {"id-a": 0.8, "id-b": 0.4}

    def test_keeps_best_score_across_queries(self):
        """When multiple queries match the same ID, keeps the best score."""
        mock_collection = MagicMock()
        mock_collection.count.return_value = 5

        def _query(**kwargs):
            q = kwargs["query_texts"][0]
            if q == "q1":
                return {"ids": [["id-a"]], "distances": [[0.5]]}
            return {"ids": [["id-a"]], "distances": [[0.1]]}

        mock_collection.query.side_effect = _query

        with patch("backend.vector_store._get_collection", return_value=mock_collection):
            scores = vector_search_with_scores(queries=["q1", "q2"], n_results=5)

        # q2 gives distance=0.1 → similarity=0.9, which is better than q1's 0.5
        assert abs(scores["id-a"] - 0.9) < 0.001

    def test_empty_collection(self):
        """Returns empty dict when collection is empty."""
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0

        with patch("backend.vector_store._get_collection", return_value=mock_collection):
            scores = vector_search_with_scores(queries=["test"])

        assert scores == {}

    def test_error_returns_empty(self):
        """Returns empty dict on ChromaDB error."""
        with patch("backend.vector_store._get_collection", side_effect=Exception("DB error")):
            scores = vector_search_with_scores(queries=["test"])

        assert scores == {}
