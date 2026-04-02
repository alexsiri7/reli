"""Auto-connect sweep — find semantically similar but unconnected Things.

Phase 1 (Vector): Query pgvector for each active Thing, identify pairs that
are semantically similar but have no existing relationship.

Phase 2 (LLM): Validate candidate pairs and suggest relationship types.

Results are stored in the connection_suggestions table as pending suggestions
that the user can accept, dismiss, or defer.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlmodel import Session, or_, select

import backend.db_engine as _engine_mod
from .db_engine import user_filter_clause
from .db_models import (
    ConnectionSuggestionRecord,
    ThingRecord,
    ThingRelationshipRecord,
)

logger = logging.getLogger(__name__)

# Minimum similarity score (cosine distance) to consider a pair
# pgvector returns distances where lower = more similar (cosine)
# We filter by distance < threshold
MAX_DISTANCE = 0.35

# Maximum number of candidate pairs to send to LLM
MAX_LLM_CANDIDATES = 30


@dataclass
class ConnectionCandidate:
    """A pair of Things that might be related."""

    from_thing_id: str
    from_thing_title: str
    to_thing_id: str
    to_thing_title: str
    distance: float
    from_type_hint: str | None = None
    to_type_hint: str | None = None


@dataclass
class ConnectionSweepResult:
    """Result of the connection sweep."""

    candidates_found: int = 0
    suggestions_created: int = 0
    suggestions: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


def find_connection_candidates(
    user_id: str = "",
    max_per_thing: int = 5,
) -> list[ConnectionCandidate]:
    """Find semantically similar but unconnected Things using vector search.

    For each active Thing, queries pgvector for similar Things and filters out
    pairs that already have a relationship or an existing suggestion.
    """
    from .vector_store import vector_count, vector_search_with_distances

    try:
        total = vector_count()
        if total < 2:
            return []
    except Exception as exc:
        logger.error("pgvector unavailable for connection sweep: %s", exc)
        return []

    # Get all active Things
    with Session(_engine_mod.engine) as session:
        thing_stmt = select(ThingRecord).where(ThingRecord.active == True)
        if user_id:
            thing_stmt = thing_stmt.where(
                user_filter_clause(ThingRecord.user_id, user_id)
            )
        things = session.exec(thing_stmt).all()

        # Build set of existing relationships (both directions)
        rel_rows = session.exec(select(ThingRelationshipRecord)).all()
        existing_rels: set[tuple[str, str]] = set()
        for row in rel_rows:
            existing_rels.add((row.from_thing_id, row.to_thing_id))
            existing_rels.add((row.to_thing_id, row.from_thing_id))

        # Build set of existing pending/deferred suggestions
        sugg_rows = session.exec(
            select(ConnectionSuggestionRecord).where(
                ConnectionSuggestionRecord.status.in_(["pending", "deferred"])  # type: ignore[union-attr]
            )
        ).all()
        existing_suggestions: set[tuple[str, str]] = set()
        for row in sugg_rows:
            existing_suggestions.add((row.from_thing_id, row.to_thing_id))
            existing_suggestions.add((row.to_thing_id, row.from_thing_id))

        # Also exclude parent-child relationships (via parent-of relationships)
        parent_pairs: set[tuple[str, str]] = set()
        parent_rels = session.exec(
            select(ThingRelationshipRecord).where(
                ThingRelationshipRecord.relationship_type == "parent-of"
            )
        ).all()
        for rel in parent_rels:
            parent_pairs.add((rel.from_thing_id, rel.to_thing_id))
            parent_pairs.add((rel.to_thing_id, rel.from_thing_id))

    thing_map = {t.id: {"id": t.id, "title": t.title, "type_hint": t.type_hint} for t in things}
    seen_pairs: set[tuple[str, str]] = set()
    candidates: list[ConnectionCandidate] = []

    for thing in things:
        thing_id = thing.id
        thing_title = thing.title

        try:
            results = vector_search_with_distances(
                query=thing_title,
                n_results=max_per_thing + 1,
                active_only=True,
                user_id=user_id,
            )
        except Exception as exc:
            logger.debug("pgvector query failed for thing %s: %s", thing_id, exc)
            continue

        for match_id, distance in results:
            if match_id == thing_id:
                continue

            # Normalize pair order to avoid duplicates
            pair = (min(thing_id, match_id), max(thing_id, match_id))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            # Skip if already connected
            if pair in existing_rels or (pair[1], pair[0]) in existing_rels:
                continue
            if pair in existing_suggestions or (pair[1], pair[0]) in existing_suggestions:
                continue
            if pair in parent_pairs or (pair[1], pair[0]) in parent_pairs:
                continue

            # Check distance threshold
            if distance > MAX_DISTANCE:
                continue

            match_thing = thing_map.get(match_id)
            if not match_thing:
                continue

            candidates.append(
                ConnectionCandidate(
                    from_thing_id=thing_id,
                    from_thing_title=thing_title,
                    to_thing_id=match_id,
                    to_thing_title=match_thing.get("title", ""),
                    distance=distance,
                    from_type_hint=thing.type_hint,
                    to_type_hint=match_thing.get("type_hint"),
                )
            )

    # Sort by distance (most similar first)
    candidates.sort(key=lambda c: c.distance)
    return candidates[:MAX_LLM_CANDIDATES]


CONNECTION_VALIDATION_SYSTEM = """\
You are an AI assistant for Reli, a personal information manager. You are given
pairs of Things (items the user tracks) that are semantically similar but not
yet connected. Your job is to validate which pairs genuinely should be related
and suggest an appropriate relationship type.

Respond with ONLY valid JSON (no markdown, no explanation):
{
  "connections": [
    {
      "from_id": "...",
      "to_id": "...",
      "relationship_type": "relates-to",
      "reason": "Both are about the user's fitness tracking goals",
      "confidence": 0.85
    }
  ]
}

Rules:
- relationship_type should be a concise, lowercase, hyphenated label
  Common types: relates-to, works-with, depends-on, part-of, inspired-by,
  similar-to, supports, contradicts, follows-up, references
- reason: One sentence explaining WHY these Things should be connected.
  Written for the USER, not a system. Be specific and helpful.
- confidence: 0.0-1.0 how confident you are they should be connected.
  Only include pairs with confidence >= 0.6
- Do NOT connect Things just because they share a common word.
  Look for meaningful semantic relationships.
- If no pairs should be connected, return {"connections": []}
- Keep results to the most meaningful connections (max 15).
"""


async def validate_candidates(
    candidates: list[ConnectionCandidate],
) -> ConnectionSweepResult:
    """Send candidate pairs to LLM for validation and create suggestions."""
    from .agents import UsageStats, _chat

    if not candidates:
        return ConnectionSweepResult()

    usage_stats = UsageStats()

    lines = [f"{len(candidates)} candidate pairs to evaluate:", ""]
    for i, c in enumerate(candidates, 1):
        from_type = f" [{c.from_type_hint}]" if c.from_type_hint else ""
        to_type = f" [{c.to_type_hint}]" if c.to_type_hint else ""
        lines.append(
            f'{i}. "{c.from_thing_title}"{from_type} (id={c.from_thing_id}) '
            f'<-> "{c.to_thing_title}"{to_type} (id={c.to_thing_id}) '
            f"[similarity={1 - c.distance:.2f}]"
        )
    prompt = "\n".join(lines)

    raw = await _chat(
        messages=[
            {"role": "system", "content": CONNECTION_VALIDATION_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        model=None,
        response_format={"type": "json_object"},
        usage_stats=usage_stats,
    )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Connection validation returned invalid JSON: %s", raw[:200])
        return ConnectionSweepResult(
            candidates_found=len(candidates),
            usage=usage_stats.to_dict(),
        )

    raw_connections = parsed.get("connections", [])
    if not isinstance(raw_connections, list):
        raw_connections = []

    # Build lookup of valid candidate pairs
    valid_pairs = {(c.from_thing_id, c.to_thing_id) for c in candidates} | {
        (c.to_thing_id, c.from_thing_id) for c in candidates
    }

    now = datetime.now(timezone.utc).isoformat()
    created: list[dict] = []

    with Session(_engine_mod.engine) as session:
        for c in raw_connections:
            if not isinstance(c, dict):
                continue

            from_id = c.get("from_id", "")
            to_id = c.get("to_id", "")
            if not from_id or not to_id:
                continue

            # Validate this pair was in our candidates
            if (from_id, to_id) not in valid_pairs:
                continue

            rel_type = str(c.get("relationship_type", "relates-to")).strip()
            if not rel_type:
                rel_type = "relates-to"

            reason = str(c.get("reason", "")).strip()
            if not reason:
                continue

            confidence = c.get("confidence", 0.5)
            if not isinstance(confidence, (int, float)):
                confidence = 0.5
            confidence = max(0.0, min(1.0, float(confidence)))

            if confidence < 0.6:
                continue

            sugg_id = f"cs-{uuid.uuid4().hex[:8]}"

            # Determine user_id from one of the things
            from_thing = session.get(ThingRecord, from_id)
            user_id = from_thing.user_id if from_thing else None

            suggestion = ConnectionSuggestionRecord(
                id=sugg_id,
                from_thing_id=from_id,
                to_thing_id=to_id,
                suggested_relationship_type=rel_type,
                reason=reason,
                confidence=confidence,
                status="pending",
                created_at=datetime.fromisoformat(now),
                user_id=user_id,
            )
            session.add(suggestion)
            created.append(
                {
                    "id": sugg_id,
                    "from_thing_id": from_id,
                    "to_thing_id": to_id,
                    "suggested_relationship_type": rel_type,
                    "reason": reason,
                    "confidence": confidence,
                }
            )
        session.commit()

    return ConnectionSweepResult(
        candidates_found=len(candidates),
        suggestions_created=len(created),
        suggestions=created,
        usage=usage_stats.to_dict(),
    )


async def run_connection_sweep(user_id: str = "") -> ConnectionSweepResult:
    """Run the full connection sweep: vector candidates + LLM validation."""
    candidates = find_connection_candidates(user_id=user_id)
    logger.info("Connection sweep: %d candidate pairs found", len(candidates))

    if not candidates:
        return ConnectionSweepResult()

    result = await validate_candidates(candidates)
    logger.info(
        "Connection sweep complete: %d suggestions created",
        result.suggestions_created,
    )
    return result
