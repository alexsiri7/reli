"""Post-retrieval relevance ranking and trimming for the Context Agent.

Scores candidate Things by a weighted combination of signals:
  - Semantic similarity (from vector search)
  - Recency (last_referenced / updated_at)
  - Priority (Thing.priority field, 1=highest)
  - Type relevance (match to requested type_hint)
  - Graph proximity (direct relationships to seed IDs)

Returns the top-N Things within a configurable context budget.
"""

import logging
import math
from datetime import datetime, timezone
from typing import Any

from .tracing import get_tracer

logger = logging.getLogger(__name__)
_tracer = get_tracer()

# ---------------------------------------------------------------------------
# Configurable weights — sum to 1.0
# ---------------------------------------------------------------------------

WEIGHT_SEMANTIC = 0.40
WEIGHT_RECENCY = 0.25
WEIGHT_GRAPH = 0.15
WEIGHT_PRIORITY = 0.10
WEIGHT_TYPE = 0.10

# Default context budget (max Things to return)
DEFAULT_CONTEXT_BUDGET = 25

# Recency half-life in days — Things lose half their recency score after this
RECENCY_HALF_LIFE_DAYS = 7.0


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _parse_dt(value: Any) -> datetime | None:
    """Parse a datetime from a string or datetime, returning None on failure."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _recency_score(thing: dict[str, Any], now: datetime) -> float:
    """Score [0, 1] based on how recently the Thing was referenced or updated.

    Uses exponential decay with ``RECENCY_HALF_LIFE_DAYS``.
    """
    last_ref = _parse_dt(thing.get("last_referenced"))
    updated = _parse_dt(thing.get("updated_at"))
    best_dt = last_ref or updated
    if best_dt is None:
        return 0.0

    age_days = max((now - best_dt).total_seconds() / 86400.0, 0.0)
    return math.exp(-math.log(2) * age_days / RECENCY_HALF_LIFE_DAYS)


def _priority_score(thing: dict[str, Any]) -> float:
    """Score [0, 1] based on Thing priority (1=highest → 1.0, 5=lowest → 0.2)."""
    try:
        p = int(thing.get("priority", 3))
    except (ValueError, TypeError):
        p = 3
    p = max(1, min(5, p))
    return 1.0 - (p - 1) * 0.2


def _type_relevance_score(thing: dict[str, Any], requested_type: str | None) -> float:
    """Score 1.0 if type matches request, 0.5 otherwise (neutral when no filter)."""
    if not requested_type:
        return 0.5
    return 1.0 if thing.get("type_hint") == requested_type else 0.0


def _graph_proximity_score(
    thing_id: str,
    seed_ids: set[str],
    relationship_map: dict[str, set[str]],
) -> float:
    """Score based on graph closeness to seed IDs.

    1.0 = is a seed, 0.7 = directly related to a seed, 0.0 = no connection.
    """
    if thing_id in seed_ids:
        return 1.0
    neighbours = relationship_map.get(thing_id, set())
    if neighbours & seed_ids:
        return 0.7
    return 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def rank_and_trim(
    things: list[dict[str, Any]],
    *,
    semantic_scores: dict[str, float] | None = None,
    seed_ids: set[str] | None = None,
    relationships: list[dict[str, Any]] | None = None,
    requested_type: str | None = None,
    context_budget: int = DEFAULT_CONTEXT_BUDGET,
) -> list[dict[str, Any]]:
    """Rank retrieved Things by relevance and trim to ``context_budget``.

    Args:
        things: Candidate Things from retrieval.
        semantic_scores: ``{thing_id: similarity}`` from vector search (0–1).
        seed_ids: IDs of the original vector/SQL search hits (before family
            expansion) — used for graph proximity scoring.
        relationships: Relationship dicts with ``from_thing_id``/``to_thing_id``.
        requested_type: The ``type_hint`` the context agent asked for (if any).
        context_budget: Maximum number of Things to return.

    Returns:
        Top-N Things sorted by descending relevance score.
    """
    if not things:
        return []

    with _tracer.start_as_current_span("reli.context.ranking") as span:
        span.set_attribute("reli.ranking.candidates", len(things))
        span.set_attribute("reli.ranking.budget", context_budget)
        span.set_attribute("reli.ranking.has_semantic_scores", semantic_scores is not None)

        now = datetime.now(timezone.utc)
        sem = semantic_scores or {}
        seeds = seed_ids or set()

        # Build adjacency map for graph proximity
        rel_map: dict[str, set[str]] = {}
        for r in (relationships or []):
            a = r.get("from_thing_id", "")
            b = r.get("to_thing_id", "")
            if a and b:
                rel_map.setdefault(a, set()).add(b)
                rel_map.setdefault(b, set()).add(a)

        scored: list[tuple[float, dict[str, Any], dict[str, float]]] = []
        for thing in things:
            tid = thing.get("id", "")

            s_sem = sem.get(tid, 0.0)
            s_rec = _recency_score(thing, now)
            s_pri = _priority_score(thing)
            s_typ = _type_relevance_score(thing, requested_type)
            s_grp = _graph_proximity_score(tid, seeds, rel_map)

            total = (
                WEIGHT_SEMANTIC * s_sem
                + WEIGHT_RECENCY * s_rec
                + WEIGHT_PRIORITY * s_pri
                + WEIGHT_TYPE * s_typ
                + WEIGHT_GRAPH * s_grp
            )

            breakdown = {
                "semantic": round(s_sem, 3),
                "recency": round(s_rec, 3),
                "priority": round(s_pri, 3),
                "type": round(s_typ, 3),
                "graph": round(s_grp, 3),
                "total": round(total, 3),
            }
            scored.append((total, thing, breakdown))

        # Sort by total score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        trimmed = scored[:context_budget]
        result = [item[1] for item in trimmed]

        # Log ranking decisions
        if scored:
            top_entries = [
                f"{item[1].get('title', item[1].get('id', '?'))}={item[2]['total']}"
                for item in trimmed[:5]
            ]
            dropped_count = len(scored) - len(trimmed)
            logger.info(
                "Relevance ranking: %d candidates → %d kept (budget=%d, dropped=%d). Top: [%s]",
                len(scored),
                len(trimmed),
                context_budget,
                dropped_count,
                ", ".join(top_entries),
            )

            if dropped_count > 0:
                dropped_entries = [
                    f"{item[1].get('title', item[1].get('id', '?'))}={item[2]['total']}"
                    for item in scored[context_budget:]
                ]
                logger.debug("Dropped Things: [%s]", ", ".join(dropped_entries))

        # OTEL attributes for debugging
        span.set_attribute("reli.ranking.kept", len(result))
        span.set_attribute("reli.ranking.dropped", len(scored) - len(result))
        if trimmed:
            span.set_attribute("reli.ranking.top_score", trimmed[0][2]["total"])
            span.set_attribute(
                "reli.ranking.bottom_score",
                trimmed[-1][2]["total"],
            )

        return result
