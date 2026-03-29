"""Preference aggregation sweep phase.

Analyzes recent chat interactions to detect repeated behavioral patterns
and aggregates weak preference signals into strong preference Things with
confidence levels.

Examples of patterns detected:
  - Rescheduling morning meetings to afternoon → "avoids mornings"
  - Always picking cheap options for travel → "cost-conscious traveler"
  - Mentioning a person in 60% of social planning → "core social group member"
  - Consistently creating tasks as high importance then downgrading → "overestimates urgency"

Preferences are stored as Things with type_hint='preference' and structured
data including confidence (0.0-1.0), supporting evidence, and category.

Communication style preferences (category='reli_communication') are handled
separately by aggregate_communication_style_patterns(). They use a different
data schema: a patterns array with text confidence levels and observation counts
rather than a single float confidence.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .auth import user_filter
from sqlmodel import Session

import backend.db_engine as _engine_mod
from .db_engine import _exec

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


@dataclass
class CommStyleAggregationResult:
    """Result of the communication style aggregation phase."""

    patterns_added: int = 0
    patterns_reinforced: int = 0
    patterns_removed: int = 0
    thing_id: str | None = None  # ID of the reli_communication preference Thing
    usage: dict = field(default_factory=dict)


def _fetch_recent_interactions(
    session: Session,
    user_id: str = "",
    days: int = INTERACTION_WINDOW_DAYS,
) -> list[dict]:
    """Fetch recent chat messages with their applied_changes for pattern analysis.

    Returns a list of dicts with keys: role, content, applied_changes, timestamp.
    Limited to the most recent interactions within the window.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    uf_sql, uf_params = user_filter(user_id)

    rows = _exec(session, 
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
        if row.applied_changes:
            try:
                raw = row.applied_changes
                applied = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                pass
        interactions.append(
            {
                "role": row.role,
                "content": row.content[:500],  # truncate long messages
                "applied_changes": applied,
                "timestamp": row.timestamp,
            }
        )
    return interactions


def _fetch_existing_preferences(session: Session, user_id: str = "") -> list[dict]:
    """Fetch existing preference Things for this user.

    Excludes reli_communication preferences — those use a different schema
    and are handled by aggregate_communication_style_patterns().
    """
    uf_sql, uf_params = user_filter(user_id)
    rows = _exec(session, 
        f"""SELECT id, title, data FROM things
           WHERE type_hint = 'preference'
             AND active = 1{uf_sql}""",
        uf_params,
    ).fetchall()

    preferences = []
    for row in rows:
        data = {}
        if row.data:
            try:
                data = json.loads(row.data) if isinstance(row.data, str) else row.data
            except (json.JSONDecodeError, TypeError):
                pass
        # Skip reli_communication preferences — they have a different data schema
        if data.get("category") == "reli_communication":
            continue
        preferences.append(
            {
                "id": row.id,
                "title": row.title,
                "data": data,
            }
        )
    return preferences


def _fetch_communication_style_things(session: Session, user_id: str = "") -> list[dict]:
    """Fetch existing reli_communication preference Things for this user."""
    uf_sql, uf_params = user_filter(user_id)
    rows = _exec(session, 
        f"""SELECT id, title, data FROM things
           WHERE type_hint = 'preference'
             AND active = 1{uf_sql}""",
        uf_params,
    ).fetchall()

    result = []
    for row in rows:
        data = {}
        if row.data:
            try:
                data = json.loads(row.data) if isinstance(row.data, str) else row.data
            except (json.JSONDecodeError, TypeError):
                pass
        if data.get("category") == "reli_communication":
            result.append({"id": row.id, "title": row.title, "data": data})
    return result


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

    with Session(_engine_mod.engine) as session:
        interactions = _fetch_recent_interactions(session, user_id)
        existing_preferences = _fetch_existing_preferences(session, user_id)

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

    with Session(_engine_mod.engine) as session:
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

                _exec(session, 
                    "UPDATE things SET data = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(updated_data), now, existing_id),
                )
                updated_count += 1
                result_prefs.append(
                    {
                        "id": existing_id,
                        "title": title,
                        "action": "updated",
                        "old_confidence": old_confidence,
                        "new_confidence": confidence,
                    }
                )
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

                _exec(session, 
                    """INSERT INTO things
                       (id, title, type_hint, importance, active, surface, data,
                        created_at, updated_at, user_id)
                       VALUES (?, ?, 'preference', 2, 1, 0, ?, ?, ?, ?)""",
                    (thing_id, title, json.dumps(pref_data), now, now, user_id or None),
                )
                created_count += 1
                result_prefs.append(
                    {
                        "id": thing_id,
                        "title": title,
                        "action": "created",
                        "confidence": confidence,
                    }
                )
        session.commit()

    return PreferenceAggregationResult(
        preferences_created=created_count,
        preferences_updated=updated_count,
        preferences=result_prefs,
        usage=usage_stats.to_dict(),
    )


# ---------------------------------------------------------------------------
# Communication style aggregation
# ---------------------------------------------------------------------------

# Observation thresholds for confidence upgrades
_CONF_ESTABLISHED_THRESHOLD = 2  # emerging → established
_CONF_STRONG_THRESHOLD = 4  # established → strong


def _comm_confidence_from_observations(observations: int, explicit: bool) -> str:
    """Derive confidence level from observation count and signal type."""
    if explicit:
        # Explicit corrections start at established
        if observations >= _CONF_STRONG_THRESHOLD:
            return "strong"
        return "established"
    # Implicit signals start at emerging
    if observations >= _CONF_STRONG_THRESHOLD:
        return "strong"
    if observations >= _CONF_ESTABLISHED_THRESHOLD:
        return "established"
    return "emerging"


COMM_STYLE_AGGREGATION_SYSTEM = """\
You are the Communication Style Analyst for Reli, an AI personal information manager.
You analyze recent user interactions to detect signals about how the user wants RELI
ITSELF to communicate — not how the user communicates with others.

Look for:

**Explicit corrections** (strong signals):
- Direct style instructions: "don't use emoji", "stop using bullet points",
  "be more concise", "too verbose", "just answer directly", "no preamble",
  "shorter responses", "don't explain yourself"
- The user is explicitly telling Reli to change how it responds.

**Implicit corrections** (weaker signals):
- User says "just" at the start: "just tell me X", "just do Y"
- User says "simpler", "shorter", "brief", "quick", "tldr" in a follow-up
- User appears to be correcting Reli's response length or style

For each detected pattern, describe it briefly (e.g., "avoids emoji",
"prefers concise responses", "no bullet points").

Also look for contradictions — if the user explicitly reverses a prior preference
(e.g., "actually use emoji now"), flag that pattern as contradicted.

Respond with ONLY valid JSON (no markdown, no explanation):
{
  "detected": [
    {
      "pattern": "short description of the style rule",
      "explicit": true,
      "signal_count": 2
    }
  ],
  "reinforced": ["exact pattern text that was seen again"],
  "contradicted": ["exact pattern text that was explicitly reversed"]
}

Rules:
- Only include patterns with at least 1 clear signal in the interaction window
- "explicit" is true only for direct style corrections, false for implicit signals
- "signal_count" is how many times this signal appeared in the interactions
- Keep pattern descriptions concise and specific
- If no communication style signals are found, return {"detected": [], "reinforced": [], "contradicted": []}
- Do NOT flag patterns about the user's communication with others (only Reli's behavior)
"""


def _format_interactions_for_comm_style(
    interactions: list[dict],
    existing_things: list[dict],
) -> str:
    """Format interaction history and existing reli_communication Things for the LLM."""
    lines = [
        f"Recent interactions ({len(interactions)} messages over the analysis window):",
        "",
    ]

    for i, msg in enumerate(interactions):
        lines.append(f"{i + 1}. [{msg['role']}] {msg['content']}")

    if existing_things:
        lines.append("")
        lines.append("Existing communication style patterns (check if reinforced or contradicted):")
        for thing in existing_things:
            patterns = thing["data"].get("patterns", [])
            for p in patterns:
                conf = p.get("confidence", "emerging")
                obs = p.get("observations", 1)
                lines.append(f"  - \"{p['pattern']}\" (confidence={conf}, observations={obs})")

    return "\n".join(lines)


async def aggregate_communication_style_patterns(
    user_id: str = "",
) -> CommStyleAggregationResult:
    """Aggregate reli_communication preference patterns from recent interactions.

    Complements the reasoning agent's real-time detection by sweeping the full
    interaction window and reinforcing or adding patterns in the reli_communication
    preference Thing.

    If multiple reli_communication Things exist (shouldn't happen normally), they
    are consolidated into one.
    """
    from .agents import REQUESTY_REASONING_MODEL, UsageStats, _chat

    with Session(_engine_mod.engine) as session:
        interactions = _fetch_recent_interactions(session, user_id)
        existing_things = _fetch_communication_style_things(session, user_id)

    if len(interactions) < MIN_INTERACTIONS:
        logger.info(
            "Comm style sweep: only %d interactions (need %d), skipping",
            len(interactions),
            MIN_INTERACTIONS,
        )
        return CommStyleAggregationResult()

    usage_stats = UsageStats()
    prompt = _format_interactions_for_comm_style(interactions, existing_things)

    raw = await _chat(
        messages=[
            {"role": "system", "content": COMM_STYLE_AGGREGATION_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        model=REQUESTY_REASONING_MODEL,
        response_format={"type": "json_object"},
        usage_stats=usage_stats,
    )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Comm style sweep returned invalid JSON: %s", raw[:200])
        return CommStyleAggregationResult(usage=usage_stats.to_dict())

    detected = parsed.get("detected", [])
    reinforced_names = set(parsed.get("reinforced", []))
    contradicted_names = set(parsed.get("contradicted", []))

    if not isinstance(detected, list):
        detected = []

    now = datetime.now(timezone.utc).isoformat()

    # Consolidate all existing Things into one canonical set of patterns
    # (handles the edge case of multiple reli_communication Things)
    merged_patterns: list[dict] = []
    primary_thing_id: str | None = None

    for thing in existing_things:
        if primary_thing_id is None:
            primary_thing_id = thing["id"]
        for p in thing["data"].get("patterns", []):
            if isinstance(p, dict) and p.get("pattern"):
                merged_patterns.append(
                    {
                        "pattern": p["pattern"],
                        "confidence": p.get("confidence", "emerging"),
                        "observations": int(p.get("observations", 1)),
                    }
                )

    patterns_added = 0
    patterns_reinforced = 0
    patterns_removed = 0

    # Remove contradicted patterns
    contradicted_lower = {c.lower() for c in contradicted_names}
    before_count = len(merged_patterns)
    merged_patterns = [
        p for p in merged_patterns if p["pattern"].lower() not in contradicted_lower
    ]
    patterns_removed = before_count - len(merged_patterns)

    # Reinforce existing patterns
    existing_pattern_map = {p["pattern"].lower(): p for p in merged_patterns}
    for name in reinforced_names:
        key = name.lower()
        if key in existing_pattern_map:
            ep = existing_pattern_map[key]
            ep["observations"] += 1
            ep["confidence"] = _comm_confidence_from_observations(
                ep["observations"], ep["confidence"] == "established" or ep["confidence"] == "strong"
            )
            patterns_reinforced += 1

    # Add newly detected patterns
    for item in detected:
        if not isinstance(item, dict):
            continue
        pattern_text = str(item.get("pattern", "")).strip()
        if not pattern_text:
            continue
        explicit = bool(item.get("explicit", False))
        signal_count = max(1, int(item.get("signal_count", 1)))

        key = pattern_text.lower()
        if key in existing_pattern_map:
            # Already exists — reinforce it
            ep = existing_pattern_map[key]
            ep["observations"] += signal_count
            ep["confidence"] = _comm_confidence_from_observations(ep["observations"], explicit)
            patterns_reinforced += 1
        else:
            # New pattern
            new_pattern = {
                "pattern": pattern_text,
                "confidence": _comm_confidence_from_observations(signal_count, explicit),
                "observations": signal_count,
            }
            merged_patterns.append(new_pattern)
            existing_pattern_map[key] = new_pattern
            patterns_added += 1

    needs_consolidation = len(existing_things) > 1
    has_changes = patterns_added > 0 or patterns_reinforced > 0 or patterns_removed > 0

    if not has_changes and not needs_consolidation and primary_thing_id is None:
        # Nothing to do at all
        return CommStyleAggregationResult(
            thing_id=primary_thing_id,
            usage=usage_stats.to_dict(),
        )

    with Session(_engine_mod.engine) as session:
        if primary_thing_id:
            if has_changes or needs_consolidation:
                # Update the primary Thing with merged patterns
                thing_data = {
                    "category": "reli_communication",
                    "patterns": merged_patterns,
                    "last_sweep": now,
                }
                _exec(session, 
                    "UPDATE things SET data = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(thing_data), now, primary_thing_id),
                )

            # Deactivate any extra reli_communication Things (duplicates)
            for thing in existing_things[1:]:
                _exec(session, 
                    "UPDATE things SET active = 0, updated_at = ? WHERE id = ?",
                    (now, thing["id"]),
                )
        else:
            # No existing Thing — create one if we have patterns
            if merged_patterns:
                primary_thing_id = f"pref-{uuid.uuid4().hex[:8]}"
                thing_data = {
                    "category": "reli_communication",
                    "patterns": merged_patterns,
                    "last_sweep": now,
                }
                _exec(session, 
                    """INSERT INTO things
                       (id, title, type_hint, importance, active, surface, data,
                        created_at, updated_at, user_id)
                       VALUES (?, ?, 'preference', 2, 1, 0, ?, ?, ?, ?)""",
                    (
                        primary_thing_id,
                        "How the user wants Reli to communicate",
                        json.dumps(thing_data),
                        now,
                        now,
                        user_id or None,
                    ),
                )
        session.commit()

    return CommStyleAggregationResult(
        patterns_added=patterns_added,
        patterns_reinforced=patterns_reinforced,
        patterns_removed=patterns_removed,
        thing_id=primary_thing_id,
        usage=usage_stats.to_dict(),
    )
