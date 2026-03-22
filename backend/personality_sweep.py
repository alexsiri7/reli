"""Personality pattern aggregation for the nightly sweep.

Analyzes recent user interactions to detect implicit behavioral patterns
and stores them as preference Things. This enables Reli's personality to
adapt over time based on how the user actually interacts with the system.

Detected signal categories:
  - title_editing: User edits Thing titles after creation → Reli may be too verbose
  - finding_dismissals: User dismisses certain finding types → reduce their priority
  - finding_engagement: User acts on certain finding types → boost those surfaces
  - message_brevity: User consistently sends short messages → prefer concise responses
  - interaction_cadence: How often the user interacts (daily engagement pattern)

Patterns are stored as a preference Thing with type_hint='preference' and
structured data following the schema from GH#193.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .auth import user_filter
from .database import db

logger = logging.getLogger(__name__)

# Lookback window for pattern analysis
_LOOKBACK_DAYS = 30

# Minimum observations before a pattern is surfaced
_MIN_OBSERVATIONS = 3

# Title of the personality preference Thing (per user)
_PREFERENCE_THING_TITLE = "How {user_name} wants Reli to communicate"
_PREFERENCE_THING_TITLE_DEFAULT = "How the user wants Reli to communicate"
_PREFERENCE_TYPE_HINT = "preference"


@dataclass
class PatternSignal:
    """A raw behavioral signal detected from interaction history."""

    pattern: str
    confidence: str  # "emerging", "moderate", "strong"
    observations: int
    category: str
    detail: str = ""


def _confidence_level(observations: int) -> str:
    """Map observation count to confidence level."""
    if observations >= 10:
        return "strong"
    elif observations >= 5:
        return "moderate"
    return "emerging"


# ---------------------------------------------------------------------------
# Signal detection queries
# ---------------------------------------------------------------------------


def detect_title_editing(
    conn: sqlite3.Connection,
    user_id: str = "",
    lookback_days: int = _LOOKBACK_DAYS,
) -> PatternSignal | None:
    """Detect if the user frequently edits Thing titles after creation.

    Looks at applied_changes in chat_history for update operations that modify
    titles on Things created within the same lookback window.
    """
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    uf_sql, uf_params = user_filter(user_id)

    # Count assistant messages with applied_changes containing title updates
    rows = conn.execute(
        f"""SELECT applied_changes FROM chat_history
           WHERE role = 'assistant'
             AND applied_changes IS NOT NULL
             AND applied_changes != 'null'
             AND timestamp >= ?{uf_sql}""",
        (cutoff, *uf_params),
    ).fetchall()

    title_update_count = 0
    for row in rows:
        try:
            changes = (
                json.loads(row["applied_changes"])
                if isinstance(row["applied_changes"], str)
                else row["applied_changes"]
            )
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(changes, dict):
            continue
        for updated in changes.get("updated", []):
            if isinstance(updated, dict) and "title" in updated:
                title_update_count += 1

    if title_update_count < _MIN_OBSERVATIONS:
        return None

    # Compare to total creations to get a ratio
    create_count = 0
    for row in rows:
        try:
            changes = (
                json.loads(row["applied_changes"])
                if isinstance(row["applied_changes"], str)
                else row["applied_changes"]
            )
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(changes, dict):
            create_count += len(changes.get("created", []))

    if create_count == 0:
        return None

    ratio = title_update_count / create_count
    if ratio < 0.2:
        return None

    return PatternSignal(
        pattern="User frequently edits Thing titles after creation — Reli may be too verbose when naming",
        confidence=_confidence_level(title_update_count),
        observations=title_update_count,
        category="title_editing",
        detail=f"{title_update_count} title edits out of {create_count} creations ({ratio:.0%})",
    )


def detect_finding_dismissals(
    conn: sqlite3.Connection,
    user_id: str = "",
    lookback_days: int = _LOOKBACK_DAYS,
) -> list[PatternSignal]:
    """Detect which finding types the user dismisses most often.

    High dismissal rates for a finding type suggest it's not valuable
    to the user and should be deprioritized.
    """
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    uf_sql, uf_params = user_filter(user_id)

    rows = conn.execute(
        f"""SELECT finding_type,
                  COUNT(*) AS total,
                  SUM(CASE WHEN dismissed = 1 THEN 1 ELSE 0 END) AS dismissed_count
           FROM sweep_findings
           WHERE created_at >= ?{uf_sql}
           GROUP BY finding_type
           HAVING total >= ?""",
        (cutoff, *uf_params, _MIN_OBSERVATIONS),
    ).fetchall()

    signals: list[PatternSignal] = []
    for row in rows:
        total = row["total"]
        dismissed = row["dismissed_count"]
        if total == 0:
            continue
        dismiss_rate = dismissed / total
        if dismiss_rate >= 0.6:
            finding_type = row["finding_type"]
            signals.append(
                PatternSignal(
                    pattern=f"User ignores {finding_type.replace('_', ' ')} alerts — reduce priority",
                    confidence=_confidence_level(dismissed),
                    observations=dismissed,
                    category="finding_dismissals",
                    detail=f"{dismissed}/{total} dismissed ({dismiss_rate:.0%})",
                )
            )

    return signals


def detect_finding_engagement(
    conn: sqlite3.Connection,
    user_id: str = "",
    lookback_days: int = _LOOKBACK_DAYS,
) -> list[PatternSignal]:
    """Detect which finding types the user engages with most.

    Low dismissal rates for a finding type suggest the user values it
    and Reli should boost that surface.
    """
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    uf_sql, uf_params = user_filter(user_id)

    rows = conn.execute(
        f"""SELECT finding_type,
                  COUNT(*) AS total,
                  SUM(CASE WHEN dismissed = 1 THEN 1 ELSE 0 END) AS dismissed_count
           FROM sweep_findings
           WHERE created_at >= ?{uf_sql}
           GROUP BY finding_type
           HAVING total >= ?""",
        (cutoff, *uf_params, _MIN_OBSERVATIONS),
    ).fetchall()

    signals: list[PatternSignal] = []
    for row in rows:
        total = row["total"]
        dismissed = row["dismissed_count"]
        if total == 0:
            continue
        engage_rate = 1 - (dismissed / total)
        if engage_rate >= 0.8:
            finding_type = row["finding_type"]
            signals.append(
                PatternSignal(
                    pattern=f"User consistently engages with {finding_type.replace('_', ' ')} items"
                    " — boost this surface",
                    confidence=_confidence_level(total - dismissed),
                    observations=total - dismissed,
                    category="finding_engagement",
                    detail=f"{total - dismissed}/{total} engaged ({engage_rate:.0%})",
                )
            )

    return signals


def detect_message_brevity(
    conn: sqlite3.Connection,
    user_id: str = "",
    lookback_days: int = _LOOKBACK_DAYS,
) -> PatternSignal | None:
    """Detect if the user consistently sends short messages.

    Short user messages suggest a preference for concise communication.
    """
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    uf_sql, uf_params = user_filter(user_id)

    rows = conn.execute(
        f"""SELECT LENGTH(content) AS msg_len FROM chat_history
           WHERE role = 'user'
             AND timestamp >= ?{uf_sql}""",
        (cutoff, *uf_params),
    ).fetchall()

    if len(rows) < _MIN_OBSERVATIONS:
        return None

    lengths = [row["msg_len"] for row in rows]
    avg_len = sum(lengths) / len(lengths)
    short_count = sum(1 for length in lengths if length < 50)
    short_ratio = short_count / len(lengths)

    if avg_len < 80 and short_ratio >= 0.6:
        return PatternSignal(
            pattern="User prefers concise messages — favor brief responses",
            confidence=_confidence_level(short_count),
            observations=len(rows),
            category="message_brevity",
            detail=f"avg {avg_len:.0f} chars, {short_ratio:.0%} under 50 chars",
        )
    elif avg_len > 200:
        return PatternSignal(
            pattern="User writes detailed messages — match their level of detail",
            confidence=_confidence_level(len(rows)),
            observations=len(rows),
            category="message_brevity",
            detail=f"avg {avg_len:.0f} chars",
        )

    return None


def detect_interaction_cadence(
    conn: sqlite3.Connection,
    user_id: str = "",
    lookback_days: int = _LOOKBACK_DAYS,
) -> PatternSignal | None:
    """Detect the user's interaction cadence (how many days they use Reli).

    Helps Reli understand engagement patterns for briefing frequency tuning.
    """
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    uf_sql, uf_params = user_filter(user_id)

    rows = conn.execute(
        f"""SELECT DISTINCT DATE(timestamp) AS interaction_date
           FROM chat_history
           WHERE role = 'user'
             AND timestamp >= ?{uf_sql}""",
        (cutoff, *uf_params),
    ).fetchall()

    active_days = len(rows)
    if active_days < _MIN_OBSERVATIONS:
        return None

    daily_rate = active_days / lookback_days

    if daily_rate >= 0.7:
        return PatternSignal(
            pattern="User is a daily active user — proactive surfaces are valued",
            confidence=_confidence_level(active_days),
            observations=active_days,
            category="interaction_cadence",
            detail=f"{active_days}/{lookback_days} days active ({daily_rate:.0%})",
        )
    elif daily_rate <= 0.2:
        return PatternSignal(
            pattern="User interacts infrequently — make each briefing comprehensive",
            confidence=_confidence_level(active_days),
            observations=active_days,
            category="interaction_cadence",
            detail=f"{active_days}/{lookback_days} days active ({daily_rate:.0%})",
        )

    return None


# ---------------------------------------------------------------------------
# Aggregation: collect all signals and store as preference Thing
# ---------------------------------------------------------------------------


def collect_personality_signals(
    user_id: str = "",
    lookback_days: int = _LOOKBACK_DAYS,
) -> list[PatternSignal]:
    """Run all signal detection queries and return aggregated patterns."""
    signals: list[PatternSignal] = []

    with db() as conn:
        title_signal = detect_title_editing(conn, user_id, lookback_days)
        if title_signal:
            signals.append(title_signal)

        signals.extend(detect_finding_dismissals(conn, user_id, lookback_days))
        signals.extend(detect_finding_engagement(conn, user_id, lookback_days))

        brevity_signal = detect_message_brevity(conn, user_id, lookback_days)
        if brevity_signal:
            signals.append(brevity_signal)

        cadence_signal = detect_interaction_cadence(conn, user_id, lookback_days)
        if cadence_signal:
            signals.append(cadence_signal)

    return signals


def _get_user_name(user_id: str) -> str:
    """Look up user's name from the users table."""
    if not user_id:
        return ""
    with db() as conn:
        row = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["name"] if row else ""


def _find_existing_preference_thing(
    conn: sqlite3.Connection,
    user_id: str = "",
) -> dict | None:
    """Find an existing personality preference Thing for this user."""
    uf_sql, uf_params = user_filter(user_id)
    row = conn.execute(
        f"""SELECT id, title, data FROM things
           WHERE type_hint = ? AND active = 1{uf_sql}
           LIMIT 1""",
        (_PREFERENCE_TYPE_HINT, *uf_params),
    ).fetchone()
    if row:
        return {"id": row["id"], "title": row["title"], "data": row["data"]}
    return None


def store_personality_patterns(
    signals: list[PatternSignal],
    user_id: str = "",
) -> str | None:
    """Create or update the personality preference Thing with detected patterns.

    Returns the Thing ID if patterns were stored, None if no signals.
    """
    if not signals:
        logger.info("No personality patterns detected for user %s", user_id[:8] if user_id else "legacy")
        return None

    import uuid

    patterns = [
        {
            "pattern": s.pattern,
            "confidence": s.confidence,
            "observations": s.observations,
            "category": s.category,
            "detail": s.detail,
        }
        for s in signals
    ]

    user_name = _get_user_name(user_id)
    title = _PREFERENCE_THING_TITLE.format(user_name=user_name) if user_name else _PREFERENCE_THING_TITLE_DEFAULT

    now = datetime.now(timezone.utc).isoformat()

    with db() as conn:
        existing = _find_existing_preference_thing(conn, user_id)

        if existing:
            # Merge patterns: keep existing patterns not in current sweep,
            # update ones that match by category
            try:
                old_data = json.loads(existing["data"]) if isinstance(existing["data"], str) else existing["data"]
            except (json.JSONDecodeError, TypeError):
                old_data = {}

            old_patterns = old_data.get("patterns", []) if isinstance(old_data, dict) else []

            # Index new patterns by category
            new_by_category = {p["category"]: p for p in patterns}

            # Keep old patterns that aren't superseded by new ones
            merged = [p for p in old_patterns if p.get("category") not in new_by_category]
            merged.extend(patterns)

            new_data = json.dumps({"patterns": merged, "last_sweep": now})

            conn.execute(
                "UPDATE things SET data = ?, updated_at = ? WHERE id = ?",
                (new_data, now, existing["id"]),
            )
            logger.info(
                "Updated personality preference Thing %s with %d patterns",
                existing["id"],
                len(merged),
            )
            thing_id_str: str = existing["id"]
            return thing_id_str
        else:
            # Create new preference Thing
            thing_id = f"thing-{uuid.uuid4().hex[:12]}"
            new_data = json.dumps({"patterns": patterns, "last_sweep": now})

            conn.execute(
                """INSERT INTO things
                   (id, title, type_hint, priority, active, surface, data,
                    created_at, updated_at, user_id)
                   VALUES (?, ?, ?, 3, 1, 0, ?, ?, ?, ?)""",
                (thing_id, title, _PREFERENCE_TYPE_HINT, new_data, now, now, user_id or None),
            )
            logger.info(
                "Created personality preference Thing %s with %d patterns",
                thing_id,
                len(patterns),
            )
            return thing_id


@dataclass
class PersonalitySweepResult:
    """Result of the personality pattern aggregation sweep."""

    signals_detected: int = 0
    thing_id: str | None = None
    patterns: list[dict] = field(default_factory=list)


async def run_personality_sweep(
    user_id: str = "",
    lookback_days: int = _LOOKBACK_DAYS,
) -> PersonalitySweepResult:
    """Run the full personality pattern aggregation for a user.

    Called by the sweep scheduler after the main sweep completes.
    """
    signals = collect_personality_signals(user_id, lookback_days)

    thing_id = store_personality_patterns(signals, user_id)

    return PersonalitySweepResult(
        signals_detected=len(signals),
        thing_id=thing_id,
        patterns=[
            {
                "pattern": s.pattern,
                "confidence": s.confidence,
                "observations": s.observations,
                "category": s.category,
            }
            for s in signals
        ],
    )
