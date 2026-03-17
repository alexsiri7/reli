"""User behavior meta-learning — nightly sweep phase that analyzes interaction
patterns and generates Learning Things.

Conservative: requires multiple observations before creating a Learning.
Updates existing learnings with new evidence.  All learnings have clear,
human-readable descriptions.

The sweep reviews:
  - Chat session patterns (frequent topics, common request types)
  - Thing interaction patterns (what types are created/updated most)
  - Temporal patterns (when the user is most active)
  - Workflow patterns (common sequences of actions)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .database import db

logger = logging.getLogger(__name__)

# Minimum observations before a pattern becomes a Learning
MIN_OBSERVATIONS = 3

# Categories for learnings
CATEGORY_TOPIC = "topic"
CATEGORY_WORKFLOW = "workflow"
CATEGORY_TEMPORAL = "temporal"
CATEGORY_THING_TYPE = "thing_type"


@dataclass
class PatternCandidate:
    """A potential pattern detected from interaction analysis."""

    title: str
    description: str
    category: str
    observation_count: int
    confidence: float
    evidence: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SQL pattern detection queries
# ---------------------------------------------------------------------------


def _analyze_thing_type_patterns(
    conn: sqlite3.Connection,
    user_id: str,
    since: datetime,
) -> list[PatternCandidate]:
    """Detect which Thing types the user creates most frequently."""
    uf = " AND user_id = ?" if user_id else ""
    params: list = [since.isoformat()]
    if user_id:
        params.append(user_id)

    rows = conn.execute(
        f"""SELECT type_hint, COUNT(*) as cnt
            FROM things
            WHERE created_at >= ?
              AND type_hint IS NOT NULL{uf}
            GROUP BY type_hint
            HAVING cnt >= ?
            ORDER BY cnt DESC""",
        [*params, MIN_OBSERVATIONS],
    ).fetchall()

    candidates: list[PatternCandidate] = []
    for row in rows:
        type_hint = row["type_hint"]
        count = row["cnt"]
        confidence = min(1.0, count / 20.0)
        candidates.append(
            PatternCandidate(
                title=f"Frequently creates {type_hint}s",
                description=(
                    f"You've created {count} {type_hint} items recently. "
                    f"This appears to be one of your primary use patterns."
                ),
                category=CATEGORY_THING_TYPE,
                observation_count=count,
                confidence=confidence,
                evidence=[f"Created {count} {type_hint} items since {since.date().isoformat()}"],
            )
        )
    return candidates


def _analyze_session_frequency(
    conn: sqlite3.Connection,
    user_id: str,
    since: datetime,
) -> list[PatternCandidate]:
    """Detect temporal patterns in user activity (which hours they're active)."""
    uf = " AND user_id = ?" if user_id else ""
    params: list = [since.isoformat()]
    if user_id:
        params.append(user_id)

    rows = conn.execute(
        f"""SELECT CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                   COUNT(*) as cnt
            FROM chat_history
            WHERE role = 'user'
              AND timestamp >= ?{uf}
            GROUP BY hour
            HAVING cnt >= ?
            ORDER BY cnt DESC
            LIMIT 3""",
        [*params, MIN_OBSERVATIONS],
    ).fetchall()

    candidates: list[PatternCandidate] = []
    for row in rows:
        hour = row["hour"]
        count = row["cnt"]
        if hour < 6:
            label = "late night"
        elif hour < 12:
            label = "morning"
        elif hour < 17:
            label = "afternoon"
        elif hour < 21:
            label = "evening"
        else:
            label = "night"
        confidence = min(1.0, count / 30.0)
        candidates.append(
            PatternCandidate(
                title=f"Most active in the {label}",
                description=(
                    f"You tend to interact most around {hour:02d}:00 "
                    f"({count} messages in that hour recently). "
                    f"This is your peak {label} activity window."
                ),
                category=CATEGORY_TEMPORAL,
                observation_count=count,
                confidence=confidence,
                evidence=[f"{count} user messages at hour {hour:02d} since {since.date().isoformat()}"],
            )
        )
    return candidates


def _analyze_topic_patterns(
    conn: sqlite3.Connection,
    user_id: str,
    since: datetime,
) -> list[PatternCandidate]:
    """Detect recurring topic patterns from applied_changes in chat history.

    Looks at what types of Things the user frequently creates/updates through chat.
    """
    uf = " AND user_id = ?" if user_id else ""
    params: list = [since.isoformat()]
    if user_id:
        params.append(user_id)

    rows = conn.execute(
        f"""SELECT applied_changes
            FROM chat_history
            WHERE role = 'assistant'
              AND applied_changes IS NOT NULL
              AND applied_changes != 'null'
              AND timestamp >= ?{uf}""",
        params,
    ).fetchall()

    # Count type_hints from created/updated things across all sessions
    type_counts: dict[str, int] = {}
    update_counts: dict[str, int] = {}

    for row in rows:
        try:
            raw = row["applied_changes"]
            changes = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(changes, dict):
            continue

        for thing in changes.get("created", []):
            if isinstance(thing, dict) and thing.get("type_hint"):
                type_counts[thing["type_hint"]] = type_counts.get(thing["type_hint"], 0) + 1

        for thing in changes.get("updated", []):
            if isinstance(thing, dict) and thing.get("type_hint"):
                update_counts[thing["type_hint"]] = update_counts.get(thing["type_hint"], 0) + 1

    candidates: list[PatternCandidate] = []

    # Frequent creation patterns via chat
    for type_hint, count in type_counts.items():
        if count >= MIN_OBSERVATIONS:
            confidence = min(1.0, count / 15.0)
            candidates.append(
                PatternCandidate(
                    title=f"Regularly creates {type_hint}s through conversation",
                    description=(
                        f"You've created {count} {type_hint} items through chat recently. "
                        f"Conversation is your preferred way to manage {type_hint}s."
                    ),
                    category=CATEGORY_TOPIC,
                    observation_count=count,
                    confidence=confidence,
                    evidence=[f"{count} {type_hint} items created via chat since {since.date().isoformat()}"],
                )
            )

    # Frequent update patterns via chat
    for type_hint, count in update_counts.items():
        if count >= MIN_OBSERVATIONS:
            confidence = min(1.0, count / 15.0)
            candidates.append(
                PatternCandidate(
                    title=f"Regularly updates {type_hint}s through conversation",
                    description=(
                        f"You've updated {count} {type_hint} items through chat recently. "
                        f"You actively manage and refine your {type_hint}s."
                    ),
                    category=CATEGORY_WORKFLOW,
                    observation_count=count,
                    confidence=confidence,
                    evidence=[f"{count} {type_hint} items updated via chat since {since.date().isoformat()}"],
                )
            )

    return candidates


def _analyze_session_length_patterns(
    conn: sqlite3.Connection,
    user_id: str,
    since: datetime,
) -> list[PatternCandidate]:
    """Detect patterns in conversation length (brief vs extended sessions)."""
    uf = " AND user_id = ?" if user_id else ""
    params: list = [since.isoformat()]
    if user_id:
        params.append(user_id)

    rows = conn.execute(
        f"""SELECT session_id, COUNT(*) as msg_count
            FROM chat_history
            WHERE role = 'user'
              AND timestamp >= ?{uf}
            GROUP BY session_id""",
        params,
    ).fetchall()

    if len(rows) < MIN_OBSERVATIONS:
        return []

    msg_counts = [row["msg_count"] for row in rows]
    avg_msgs = sum(msg_counts) / len(msg_counts)

    short_sessions = sum(1 for c in msg_counts if c <= 2)
    long_sessions = sum(1 for c in msg_counts if c >= 5)
    total = len(msg_counts)

    candidates: list[PatternCandidate] = []

    if short_sessions / total >= 0.6 and total >= MIN_OBSERVATIONS:
        candidates.append(
            PatternCandidate(
                title="Prefers quick, focused interactions",
                description=(
                    f"Most of your sessions are brief ({short_sessions}/{total} have 1-2 messages). "
                    f"You tend to use quick commands rather than extended conversations."
                ),
                category=CATEGORY_WORKFLOW,
                observation_count=total,
                confidence=min(1.0, short_sessions / total),
                evidence=[
                    f"{short_sessions}/{total} sessions have <= 2 messages",
                    f"Average: {avg_msgs:.1f} messages per session",
                ],
            )
        )
    elif long_sessions / total >= 0.4 and total >= MIN_OBSERVATIONS:
        candidates.append(
            PatternCandidate(
                title="Prefers extended conversations",
                description=(
                    f"Many of your sessions are extended ({long_sessions}/{total} have 5+ messages). "
                    f"You tend to think through topics in depth during conversations."
                ),
                category=CATEGORY_WORKFLOW,
                observation_count=total,
                confidence=min(1.0, long_sessions / total),
                evidence=[
                    f"{long_sessions}/{total} sessions have >= 5 messages",
                    f"Average: {avg_msgs:.1f} messages per session",
                ],
            )
        )

    return candidates


# ---------------------------------------------------------------------------
# LLM reflection for meta-learning
# ---------------------------------------------------------------------------

META_LEARNING_SYSTEM = """\
You are the Meta-Learning Analyst for Reli, an AI personal information manager.
You receive pattern candidates detected from user interaction analysis.

Your job: refine these patterns into clear, actionable learnings about the user's
behavior and preferences. Be conservative — only confirm patterns that have strong
evidence.

Respond with ONLY valid JSON (no markdown, no explanation):
{
  "learnings": [
    {
      "title": "Short, clear title describing the pattern",
      "description": "Human-readable description of what was observed and why it matters",
      "category": "topic|workflow|temporal|thing_type",
      "confidence": 0.7,
      "should_create": true
    }
  ]
}

Rules:
- confidence: 0.0-1.0 (0.5+ = worth creating, 0.8+ = strong pattern)
- should_create: false to reject weak or misleading patterns
- title: written for the USER, warm and specific
  Good: "You're a morning planner — most tasks get created before noon"
  Bad: "High morning activity detected in temporal analysis"
- description: explain what was observed and how Reli can help
- Keep to 1-5 learnings. Quality over quantity.
- If patterns are weak or trivial, return {"learnings": []}
"""


@dataclass
class MetaLearningResult:
    """Result of the meta-learning sweep phase."""

    learnings_created: int = 0
    learnings_updated: int = 0
    candidates_analyzed: int = 0
    usage: dict = field(default_factory=dict)


def collect_pattern_candidates(
    user_id: str = "",
    lookback_days: int = 30,
) -> list[PatternCandidate]:
    """Run all SQL pattern detection queries and return combined candidates."""
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    with db() as conn:
        candidates = (
            _analyze_thing_type_patterns(conn, user_id, since)
            + _analyze_session_frequency(conn, user_id, since)
            + _analyze_topic_patterns(conn, user_id, since)
            + _analyze_session_length_patterns(conn, user_id, since)
        )

    candidates.sort(key=lambda c: (-c.confidence, -c.observation_count))
    return candidates


def _format_candidates_for_llm(candidates: list[PatternCandidate]) -> str:
    """Format pattern candidates for LLM review."""
    if not candidates:
        return "No pattern candidates detected."

    lines = [f"Detected {len(candidates)} pattern candidates:", ""]
    for i, c in enumerate(candidates, 1):
        evidence_str = "; ".join(c.evidence) if c.evidence else "N/A"
        lines.append(
            f"{i}. [{c.category}] {c.title} "
            f"(observations={c.observation_count}, confidence={c.confidence:.2f})\n"
            f"   Evidence: {evidence_str}\n"
            f"   Description: {c.description}"
        )
    return "\n".join(lines)


def _upsert_learning(
    conn: sqlite3.Connection,
    user_id: str,
    title: str,
    description: str,
    category: str,
    confidence: float,
    evidence: list[str],
) -> tuple[str, bool]:
    """Insert a new learning or update an existing one with new evidence.

    Returns (learning_id, is_new).
    Matching is done by category + fuzzy title match (exact for now).
    """
    now = datetime.now(timezone.utc).isoformat()
    uf = " AND user_id = ?" if user_id else ""
    params: list = [category]
    if user_id:
        params.append(user_id)

    # Check for existing learning in the same category with similar title
    existing = conn.execute(
        f"""SELECT id, observation_count, evidence, confidence
            FROM learnings
            WHERE category = ?{uf}
              AND active = 1
            ORDER BY updated_at DESC""",
        params,
    ).fetchall()

    # Check if any existing learning in this category can be updated
    for row in existing:
        existing_id = row["id"]
        # Load existing evidence
        try:
            old_evidence = json.loads(row["evidence"]) if row["evidence"] else []
        except (json.JSONDecodeError, TypeError):
            old_evidence = []

        # Combine evidence (keep latest 10 entries)
        combined_evidence = list(set(old_evidence + evidence))[-10:]

        # Update existing learning
        new_count = row["observation_count"] + 1
        new_confidence = min(1.0, max(confidence, row["confidence"]))

        conn.execute(
            """UPDATE learnings
               SET description = ?,
                   confidence = ?,
                   observation_count = ?,
                   evidence = ?,
                   last_observed_at = ?,
                   updated_at = ?
               WHERE id = ?""",
            (
                description,
                new_confidence,
                new_count,
                json.dumps(combined_evidence),
                now,
                now,
                existing_id,
            ),
        )
        return existing_id, False

    # Create new learning
    learning_id = f"lr-{uuid.uuid4().hex[:8]}"
    conn.execute(
        """INSERT INTO learnings
           (id, user_id, title, description, category, confidence,
            observation_count, evidence, active, last_observed_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
        (
            learning_id,
            user_id or None,
            title,
            description,
            category,
            confidence,
            1,
            json.dumps(evidence),
            now,
            now,
            now,
        ),
    )
    return learning_id, True


async def analyze_and_learn(
    user_id: str = "",
    lookback_days: int = 30,
) -> MetaLearningResult:
    """Run meta-learning analysis: detect patterns, optionally refine via LLM,
    and upsert learnings.

    This is the main entry point called by the sweep scheduler.
    """
    from .agents import UsageStats, _chat

    candidates = collect_pattern_candidates(user_id, lookback_days)
    result = MetaLearningResult(candidates_analyzed=len(candidates))

    if not candidates:
        logger.info("Meta-learning: no pattern candidates found")
        return result

    # Phase 2: LLM reflection on candidates
    usage_stats = UsageStats()
    prompt = _format_candidates_for_llm(candidates)

    try:
        raw = await _chat(
            messages=[
                {"role": "system", "content": META_LEARNING_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            model=None,
            response_format={"type": "json_object"},
            usage_stats=usage_stats,
        )
        result.usage = usage_stats.to_dict()
    except Exception:
        logger.exception("Meta-learning LLM reflection failed")
        # Fall back to SQL-only learnings (skip LLM refinement)
        return _save_candidates_directly(candidates, user_id, result)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Meta-learning reflection returned invalid JSON: %s", raw[:200])
        return _save_candidates_directly(candidates, user_id, result)

    raw_learnings = parsed.get("learnings", [])
    if not isinstance(raw_learnings, list):
        raw_learnings = []

    with db() as conn:
        for learning in raw_learnings:
            if not isinstance(learning, dict):
                continue
            if not learning.get("should_create", True):
                continue

            title = str(learning.get("title", "")).strip()
            description = str(learning.get("description", "")).strip()
            if not title or not description:
                continue

            category = learning.get("category", "behavior")
            if category not in (CATEGORY_TOPIC, CATEGORY_WORKFLOW, CATEGORY_TEMPORAL, CATEGORY_THING_TYPE):
                category = "behavior"

            confidence = learning.get("confidence", 0.5)
            if not isinstance(confidence, (int, float)):
                confidence = 0.5
            confidence = max(0.0, min(1.0, float(confidence)))

            if confidence < 0.5:
                continue

            # Match evidence from original candidates
            evidence = []
            for c in candidates:
                if c.category == category:
                    evidence.extend(c.evidence)

            _, is_new = _upsert_learning(conn, user_id, title, description, category, confidence, evidence)
            if is_new:
                result.learnings_created += 1
            else:
                result.learnings_updated += 1

    logger.info(
        "Meta-learning complete: %d created, %d updated (from %d candidates)",
        result.learnings_created,
        result.learnings_updated,
        result.candidates_analyzed,
    )
    return result


def _save_candidates_directly(
    candidates: list[PatternCandidate],
    user_id: str,
    result: MetaLearningResult,
) -> MetaLearningResult:
    """Save SQL-detected candidates directly as learnings (LLM fallback)."""
    with db() as conn:
        for c in candidates:
            if c.confidence < 0.5:
                continue
            _, is_new = _upsert_learning(
                conn, user_id, c.title, c.description, c.category, c.confidence, c.evidence
            )
            if is_new:
                result.learnings_created += 1
            else:
                result.learnings_updated += 1
    return result
