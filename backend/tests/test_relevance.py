"""Tests for relevance ranking and trimming."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.relevance import (
    DEFAULT_CONTEXT_BUDGET,
    rank_and_trim,
)


def _make_thing(
    id: str = "t-1",
    title: str = "Test",
    priority: int = 3,
    type_hint: str | None = None,
    updated_at: str | None = None,
    last_referenced: str | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": id,
        "title": title,
        "priority": priority,
        "type_hint": type_hint,
        "updated_at": updated_at or now.isoformat(),
        "last_referenced": last_referenced,
        "active": True,
    }


class TestRankAndTrim:
    def test_empty_input(self):
        assert rank_and_trim([]) == []

    def test_returns_all_within_budget(self):
        things = [_make_thing(id=f"t-{i}") for i in range(3)]
        result = rank_and_trim(things, context_budget=10)
        assert len(result) == 3

    def test_trims_to_budget(self):
        things = [_make_thing(id=f"t-{i}") for i in range(10)]
        result = rank_and_trim(things, context_budget=5)
        assert len(result) == 5

    def test_semantic_scores_influence_ranking(self):
        """Things with higher semantic similarity should rank higher."""
        t_high = _make_thing(id="high", title="High Sem")
        t_low = _make_thing(id="low", title="Low Sem")
        scores = {"high": 0.95, "low": 0.1}

        result = rank_and_trim(
            [t_low, t_high],
            semantic_scores=scores,
            context_budget=2,
        )
        assert result[0]["id"] == "high"

    def test_recency_influences_ranking(self):
        """Recently referenced Things should rank higher than stale ones."""
        now = datetime.now(timezone.utc)
        recent = _make_thing(
            id="recent",
            last_referenced=now.isoformat(),
        )
        stale = _make_thing(
            id="stale",
            last_referenced=(now - timedelta(days=30)).isoformat(),
        )

        result = rank_and_trim(
            [stale, recent],
            context_budget=2,
        )
        assert result[0]["id"] == "recent"

    def test_priority_influences_ranking(self):
        """Higher priority (lower number) Things should rank higher."""
        high_pri = _make_thing(id="p1", priority=1)
        low_pri = _make_thing(id="p5", priority=5)

        result = rank_and_trim(
            [low_pri, high_pri],
            context_budget=2,
        )
        assert result[0]["id"] == "p1"

    def test_type_relevance(self):
        """Things matching the requested type should score higher."""
        matching = _make_thing(id="match", type_hint="task")
        other = _make_thing(id="other", type_hint="person")

        result = rank_and_trim(
            [other, matching],
            requested_type="task",
            context_budget=2,
        )
        assert result[0]["id"] == "match"

    def test_graph_proximity_seeds_rank_higher(self):
        """Seed IDs should rank higher than non-seeds."""
        seed = _make_thing(id="seed")
        nonseed = _make_thing(id="nonseed")

        result = rank_and_trim(
            [nonseed, seed],
            seed_ids={"seed"},
            context_budget=2,
        )
        assert result[0]["id"] == "seed"

    def test_graph_proximity_related_to_seed(self):
        """Things related to seeds should rank higher than unconnected things."""
        related = _make_thing(id="related")
        unconnected = _make_thing(id="unconnected")
        rels = [{"from_thing_id": "seed-1", "to_thing_id": "related", "relationship_type": "uses"}]

        result = rank_and_trim(
            [unconnected, related],
            seed_ids={"seed-1"},
            relationships=rels,
            context_budget=2,
        )
        assert result[0]["id"] == "related"

    def test_default_budget(self):
        """Without explicit budget, uses DEFAULT_CONTEXT_BUDGET."""
        things = [_make_thing(id=f"t-{i}") for i in range(DEFAULT_CONTEXT_BUDGET + 10)]
        result = rank_and_trim(things)
        assert len(result) == DEFAULT_CONTEXT_BUDGET

    def test_combined_signals(self):
        """A thing that is semantically close AND recent should beat one that's only recent."""
        now = datetime.now(timezone.utc)
        both = _make_thing(id="both", last_referenced=now.isoformat())
        only_recent = _make_thing(id="recent_only", last_referenced=now.isoformat())
        scores = {"both": 0.9, "recent_only": 0.0}

        result = rank_and_trim(
            [only_recent, both],
            semantic_scores=scores,
            context_budget=2,
        )
        assert result[0]["id"] == "both"

    def test_no_semantic_scores_graceful(self):
        """Ranking works when no semantic scores are available (SQL fallback path)."""
        now = datetime.now(timezone.utc)
        recent = _make_thing(id="recent", last_referenced=now.isoformat(), priority=1)
        old = _make_thing(
            id="old",
            last_referenced=(now - timedelta(days=60)).isoformat(),
            priority=5,
        )

        result = rank_and_trim([old, recent], context_budget=2)
        assert result[0]["id"] == "recent"
