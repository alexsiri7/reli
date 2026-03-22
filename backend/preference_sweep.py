"""Preference aggregation sweep phase.

Analyzes recent chat interactions to detect repeated behavioral patterns
and aggregates weak preference signals into strong preference Things with
confidence levels.

Examples of patterns detected:
  - Rescheduling morning meetings to afternoon → "avoids mornings"
  - Always picking cheap options for travel → "cost-conscious traveler"
  - Mentioning a person in 60% of social planning → "core social group member"
  - Consistently creating tasks as high priority then downgrading → "overestimates urgency"

Preferences are stored as Things with type_hint='preference' and structured
data including confidence (0.0-1.0), supporting evidence, and category.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .auth import user_filter
from .database import db

logger = logging.getLogger(__name__)

# How many days of interactions to analyze per sweep
INTERACTION_WINDOW_DAYS = 30
# Minimum interactions needed before pattern detection is meaningful
MIN_INTERACTIONS = 5


@dataclass
class PreferenceUpdate:
    """A preference detected or updated by the aggregation sweep."""

    title: str
    category: str  # scheduling, spending, social, productivity, communication
    confidence: float  # 0.0 to 1.0
    evidence: list[str]  # supporting observations
    thing_id: str | None = None  # existing preference Thing ID, if updating


@dataclass
class PreferenceAggregationResult:
    """Result of the preference aggregation phase."""

    preferences_created: int = 0
    preferences_updated: int = 0
    preferences: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


def _fetch_recent_interactions(
    conn,
    user_id: str = "",
    days: int = INTERACTION_WINDOW_DAYS,
) -> list[dict]:
    """Fetch recent chat messages with their applied_changes for pattern analysis.

    Returns a list of dicts with keys: role, content, applied_changes, timestamp.
    Limited to the most recent interactions within the window.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    uf_sql, uf_params = user_filter(user_id)

    rows = conn.execute(
        f"""SELECT role, content, applied_changes, timestamp
           FROM chat_history
           WHERE timestamp >= ?{uf_sql}
           ORDER BY timestamp ASC
           LIMIT 500""",
        (cutoff, *uf_params),
    ).fetchall()

    interactions = []
    for row in rows:
        applied = None
        if row["applied_changes"]:
            try:
                raw = row["applied_changes"]
                applied = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                pass
        interactions.append({
            "role": row["role"],
            "content": row["content"][:500],  # truncate long messages
            "applied_changes": applied,
            "timestamp": row["timestamp"],
        })
    return interactions


def _fetch_existing_preferences(conn, user_id: str = "") -> list[dict]:
    """Fetch existing preference Things for this user."""
    uf_sql, uf_params = user_filter(user_id)
    rows = conn.execute(
        f"""SELECT id, title, data FROM things
           WHERE type_hint = 'preference'
             AND active = 1{uf_sql}""",
        uf_params,
    ).fetchall()

    preferences = []
    for row in rows:
        data = {}
        if row["data"]:
            try:
                data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
            except (json.JSONDecodeError, TypeError):
                pass
        preferences.append({
            "id": row["id"],
            "title": row["title"],
            "data": data,
        })
    return preferences


def _format_interactions_for_llm(
    interactions: list[dict],
    existing_preferences: list[dict],
) -> str:
    """Format interaction history and existing preferences into an LLM prompt."""
    lines = [
        f"Recent interactions ({len(interactions)} messages over the analysis window):",
        "",
    ]

    # Summarize interactions — group by pairs (user + assistant)
    for i, msg in enumerate(interactions):
        role = msg["role"]
        content = msg["content"]
        changes = msg.get("applied_changes")

        line = f"{i + 1}. [{role}] {content}"
        if changes:
            created = changes.get("created", [])
            updated = changes.get("updated", [])
            if created:
                titles = [c.get("title", "?") for c in created if isinstance(c, dict)]
                line += f" [created: {', '.join(titles[:3])}]"
            if updated:
                titles = [u.get("title", "?") for u in updated if isinstance(u, dict)]
                line += f" [updated: {', '.join(titles[:3])}]"
        lines.append(line)

    if existing_preferences:
        lines.append("")
        lines.append("Existing preferences (update confidence if patterns confirm/weaken):")
        for p in existing_preferences:
            conf = p["data"].get("confidence", 0.5)
            cat = p["data"].get("category", "unknown")
            lines.append(f"  - [{p['id']}] {p['title']} (confidence={conf}, category={cat})")

    return "\n".join(lines)


PREFERENCE_AGGREGATION_SYSTEM = """\
You are the Preference Analyst for Reli, an AI personal information manager.
You analyze recent user interactions to detect repeated behavioral patterns
and aggregate weak signals into preference insights.

Your job: find patterns in how the user behaves — not what they explicitly say
they prefer, but what their actions reveal. Look for:

1. **Scheduling patterns**: Do they avoid certain times? Reschedule consistently?
2. **Priority patterns**: Do they over/under-estimate urgency? Focus on certain types?
3. **Social patterns**: Who appears frequently? In what contexts?
4. **Decision patterns**: Do they consistently choose certain options (cheap, fast, etc.)?
5. **Productivity patterns**: When are they most active? How do they organize work?
6. **Communication patterns**: Tone preferences, brevity vs detail, formality level?

Respond with ONLY valid JSON matching this schema (no markdown, no explanation):
{
  "preferences": [
    {
      "title": "Short, descriptive preference name",
      "category": "scheduling|spending|social|productivity|communication|other",
      "confidence": 0.6,
      "evidence": ["Observation 1", "Observation 2"],
      "existing_id": null
    }
  ]
}

Rules:
- confidence: 0.0 to 1.0 — how certain you are this is a real pattern
  - 0.3-0.5: weak signal, needs more data
  - 0.5-0.7: moderate pattern, worth tracking
  - 0.7-0.9: strong pattern, well-evidenced
  - 0.9-1.0: very strong, consistent across many interactions
- Only report preferences with confidence >= 0.3
- Each preference needs at least 2 pieces of evidence from the interactions
- If an existing preference is confirmed by new evidence, include its ID in
  existing_id and adjust confidence UP (max 0.05 increase per sweep)
- If an existing preference is contradicted, include its ID and adjust
  confidence DOWN (max 0.1 decrease per sweep)
- Don't fabricate patterns — if the interaction history is too sparse, return
  {"preferences": []}
- Keep to 1-5 preferences per sweep. Quality over quantity.
- title should be user-friendly: "Prefers afternoon meetings" not "scheduling_afternoon"
"""


async def aggregate_preference_patterns(
    user_id: str = "",
) -> PreferenceAggregationResult:
    """Analyze recent interactions and create/update preference Things.

    This is the preference aggregation phase of the nightly sweep. It:
    1. Fetches recent chat interactions (last 30 days)
    2. Fetches existing preference Things
    3. Sends both to an LLM for pattern detection
    4. Creates new preference Things or updates existing ones
    """
    from .agents import REQUESTY_REASONING_MODEL, UsageStats, _chat

    with db() as conn:
        interactions = _fetch_recent_interactions(conn, user_id)
        existing_preferences = _fetch_existing_preferences(conn, user_id)

    if len(interactions) < MIN_INTERACTIONS:
        logger.info(
            "Preference sweep: only %d interactions (need %d), skipping",
            len(interactions),
            MIN_INTERACTIONS,
        )
        return PreferenceAggregationResult()

    usage_stats = UsageStats()
    prompt = _format_interactions_for_llm(interactions, existing_preferences)

    raw = await _chat(
        messages=[
            {"role": "system", "content": PREFERENCE_AGGREGATION_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        model=REQUESTY_REASONING_MODEL,
        response_format={"type": "json_object"},
        usage_stats=usage_stats,
    )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Preference sweep returned invalid JSON: %s", raw[:200])
        return PreferenceAggregationResult(usage=usage_stats.to_dict())

    raw_prefs = parsed.get("preferences", [])
    if not isinstance(raw_prefs, list):
        raw_prefs = []

    # Build lookup of existing preferences by ID
    existing_by_id = {p["id"]: p for p in existing_preferences}

    created_count = 0
    updated_count = 0
    result_prefs: list[dict] = []

    now = datetime.now(timezone.utc).isoformat()

    with db() as conn:
        for pref in raw_prefs:
            if not isinstance(pref, dict):
                continue

            title = str(pref.get("title", "")).strip()
            if not title:
                continue

            category = str(pref.get("category", "other")).strip()
            confidence = pref.get("confidence", 0.5)
            if not isinstance(confidence, (int, float)):
                confidence = 0.5
            confidence = max(0.0, min(1.0, float(confidence)))

            evidence = pref.get("evidence", [])
            if not isinstance(evidence, list):
                evidence = []
            evidence = [str(e) for e in evidence if e]

            existing_id = pref.get("existing_id")

            if existing_id and existing_id in existing_by_id:
                # Update existing preference Thing
                existing = existing_by_id[existing_id]
                existing_data = existing.get("data", {})
                old_confidence = existing_data.get("confidence", 0.5)

                # Merge evidence (keep last 10)
                old_evidence = existing_data.get("evidence", [])
                merged_evidence = old_evidence + evidence
                merged_evidence = merged_evidence[-10:]

                updated_data = {
                    **existing_data,
                    "confidence": confidence,
                    "evidence": merged_evidence,
                    "category": category,
                    "last_sweep": now,
                    "sweep_count": existing_data.get("sweep_count", 0) + 1,
                }

                conn.execute(
                    "UPDATE things SET data = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(updated_data), now, existing_id),
                )
                updated_count += 1
                result_prefs.append({
                    "id": existing_id,
                    "title": title,
                    "action": "updated",
                    "old_confidence": old_confidence,
                    "new_confidence": confidence,
                })
            else:
                # Create new preference Thing
                thing_id = f"pref-{uuid.uuid4().hex[:8]}"
                pref_data = {
                    "confidence": confidence,
                    "evidence": evidence,
                    "category": category,
                    "last_sweep": now,
                    "sweep_count": 1,
                }

                conn.execute(
                    """INSERT INTO things
                       (id, title, type_hint, priority, active, surface, data,
                        created_at, updated_at, user_id)
                       VALUES (?, ?, 'preference', 3, 1, 0, ?, ?, ?, ?)""",
                    (thing_id, title, json.dumps(pref_data), now, now, user_id or None),
                )
                created_count += 1
                result_prefs.append({
                    "id": thing_id,
                    "title": title,
                    "action": "created",
                    "confidence": confidence,
                })

    return PreferenceAggregationResult(
        preferences_created=created_count,
        preferences_updated=updated_count,
        preferences=result_prefs,
        usage=usage_stats.to_dict(),
    )
