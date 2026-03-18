"""Interaction style preference learning and retrieval.

Analyzes chat history to learn user interaction preferences across three
dimensions:
  - coaching_vs_consulting: 0.0 = coaching (guided, question-heavy),
                            1.0 = consulting (direct, answer-heavy)
  - verbosity: 0.0 = brief, 1.0 = detailed
  - formality: 0.0 = casual, 1.0 = formal

Learned values are stored in the interaction_style table and injected into
the response agent's system prompt to personalize responses.
"""

import logging
import re
from typing import Any

from .database import db

logger = logging.getLogger(__name__)

# The three dimensions we track
DIMENSIONS = ("coaching_vs_consulting", "verbosity", "formality")

# Default neutral values (0.5 = no preference detected)
DEFAULTS: dict[str, float] = {
    "coaching_vs_consulting": 0.5,
    "verbosity": 0.5,
    "formality": 0.5,
}


def get_style_preferences(user_id: str) -> dict[str, Any]:
    """Return current interaction style preferences for a user.

    Returns dict with each dimension containing:
      - value: effective value (manual_override if set, else learned_value)
      - learned_value: the analyzed value
      - manual_override: user's explicit preference or None
      - sample_count: number of messages analyzed
    """
    if not user_id:
        return {d: {"value": DEFAULTS[d], "learned_value": DEFAULTS[d],
                     "manual_override": None, "sample_count": 0}
                for d in DIMENSIONS}

    with db() as conn:
        rows = conn.execute(
            "SELECT dimension, learned_value, manual_override, sample_count "
            "FROM interaction_style WHERE user_id = ?",
            (user_id,),
        ).fetchall()

    prefs: dict[str, Any] = {}
    found = {row["dimension"]: row for row in rows}
    for dim in DIMENSIONS:
        if dim in found:
            row = found[dim]
            learned = row["learned_value"]
            override = row["manual_override"]
            effective = float(override) if override is not None else learned
            prefs[dim] = {
                "value": effective,
                "learned_value": learned,
                "manual_override": float(override) if override is not None else None,
                "sample_count": row["sample_count"],
            }
        else:
            prefs[dim] = {
                "value": DEFAULTS[dim],
                "learned_value": DEFAULTS[dim],
                "manual_override": None,
                "sample_count": 0,
            }
    return prefs


def get_effective_style(user_id: str) -> dict[str, float]:
    """Return just the effective values (for injection into prompts)."""
    prefs = get_style_preferences(user_id)
    return {dim: prefs[dim]["value"] for dim in DIMENSIONS}


def set_manual_override(user_id: str, dimension: str, value: float | None) -> None:
    """Set or clear a manual override for a style dimension."""
    if dimension not in DIMENSIONS:
        raise ValueError(f"Invalid dimension: {dimension}")
    if value is not None and not (0.0 <= value <= 1.0):
        raise ValueError("Value must be between 0.0 and 1.0")
    if not user_id:
        return

    override_str = str(value) if value is not None else None
    with db() as conn:
        conn.execute(
            """INSERT INTO interaction_style (user_id, dimension, manual_override, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id, dimension) DO UPDATE SET
                 manual_override = excluded.manual_override,
                 updated_at = CURRENT_TIMESTAMP""",
            (user_id, dimension, override_str),
        )


def analyze_chat_history(user_id: str) -> dict[str, Any]:
    """Analyze a user's chat history to learn interaction style preferences.

    Examines user messages for:
      - coaching_vs_consulting: question frequency, directive language
      - verbosity: average message length
      - formality: punctuation, contractions, casual markers
    """
    if not user_id:
        return get_style_preferences(user_id)

    with db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM chat_history "
            "WHERE user_id = ? ORDER BY timestamp DESC LIMIT 200",
            (user_id,),
        ).fetchall()

    user_messages = [r["content"] for r in rows if r["role"] == "user" and r["content"]]
    assistant_messages = [r["content"] for r in rows if r["role"] == "assistant" and r["content"]]
    sample_count = len(user_messages)

    if sample_count < 3:
        # Not enough data to learn from
        return get_style_preferences(user_id)

    coaching_score = _analyze_coaching_vs_consulting(user_messages)
    verbosity_score = _analyze_verbosity(user_messages)
    formality_score = _analyze_formality(user_messages)

    # Persist learned values
    with db() as conn:
        for dim, val in [
            ("coaching_vs_consulting", coaching_score),
            ("verbosity", verbosity_score),
            ("formality", formality_score),
        ]:
            conn.execute(
                """INSERT INTO interaction_style
                   (user_id, dimension, learned_value, sample_count, updated_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(user_id, dimension) DO UPDATE SET
                     learned_value = excluded.learned_value,
                     sample_count = excluded.sample_count,
                     updated_at = CURRENT_TIMESTAMP""",
                (user_id, dim, val, sample_count),
            )

    logger.info(
        "Analyzed %d messages for user %s: coaching=%.2f, verbosity=%.2f, formality=%.2f",
        sample_count, user_id, coaching_score, verbosity_score, formality_score,
    )

    return get_style_preferences(user_id)


def _analyze_coaching_vs_consulting(messages: list[str]) -> float:
    """Analyze whether user prefers coaching (guided discovery) vs consulting (direct answers).

    Low score = user asks open-ended questions, wants guidance (coaching)
    High score = user gives directives, wants direct answers (consulting)
    """
    if not messages:
        return 0.5

    directive_patterns = re.compile(
        r"\b(make|create|set up|update|add|remove|delete|change|fix|tell me|give me|show me|list|do this|do that|do it)\b",
        re.IGNORECASE,
    )
    question_patterns = re.compile(
        r"\b(what do you think|how should|what would you suggest|help me think|"
        r"what are my options|should i|could you help me figure|advice)\b",
        re.IGNORECASE,
    )

    directive_count = 0
    question_count = 0
    for msg in messages:
        if directive_patterns.search(msg):
            directive_count += 1
        if question_patterns.search(msg):
            question_count += 1

    total = directive_count + question_count
    if total == 0:
        return 0.5

    # More directives = higher (consulting), more questions = lower (coaching)
    return min(1.0, max(0.0, directive_count / total))


def _analyze_verbosity(messages: list[str]) -> float:
    """Analyze user's preferred verbosity level.

    Based on average message length:
      <20 chars = 0.0 (very brief)
      20-50 = 0.25
      50-100 = 0.5
      100-200 = 0.75
      >200 = 1.0 (very detailed)
    """
    if not messages:
        return 0.5

    avg_len = sum(len(m) for m in messages) / len(messages)

    if avg_len < 20:
        return 0.1
    if avg_len < 50:
        return 0.3
    if avg_len < 100:
        return 0.5
    if avg_len < 200:
        return 0.7
    return 0.9


def _analyze_formality(messages: list[str]) -> float:
    """Analyze user's formality level.

    Casual markers: contractions, slang, emoji, lowercase starts
    Formal markers: complete sentences, punctuation, capitalization
    """
    if not messages:
        return 0.5

    casual_patterns = re.compile(
        r"(don't|can't|won't|isn't|i'm|it's|that's|what's|here's|there's|"
        r"gonna|wanna|gotta|ya|yep|nope|hey|hi|ok\b|lol|haha|!{2,}|"
        r"\.{3,}|btw|imo|tbh)",
        re.IGNORECASE,
    )
    formal_patterns = re.compile(
        r"(please|thank you|could you|would you|I would|"
        r"appreciate|regarding|furthermore|however|therefore|"
        r"in addition|accordingly)",
        re.IGNORECASE,
    )

    casual_count = 0
    formal_count = 0
    for msg in messages:
        casual_count += len(casual_patterns.findall(msg))
        formal_count += len(formal_patterns.findall(msg))

    total = casual_count + formal_count
    if total == 0:
        return 0.5

    # More formal markers = higher score
    return min(1.0, max(0.0, formal_count / total))


def build_style_instruction(style: dict[str, float]) -> str:
    """Build a style instruction string to inject into the response agent prompt.

    Returns empty string if all values are near default (0.5).
    """
    parts: list[str] = []

    cv = style.get("coaching_vs_consulting", 0.5)
    if cv < 0.35:
        parts.append(
            "This user prefers a coaching approach — ask guiding questions, "
            "help them think through problems, offer options rather than directives."
        )
    elif cv > 0.65:
        parts.append(
            "This user prefers a consulting approach — give direct answers and "
            "recommendations, be action-oriented, minimize back-and-forth."
        )

    vb = style.get("verbosity", 0.5)
    if vb < 0.35:
        parts.append("Keep responses very brief and to-the-point.")
    elif vb > 0.65:
        parts.append(
            "This user appreciates detailed responses — include context, "
            "reasoning, and thorough explanations."
        )

    fm = style.get("formality", 0.5)
    if fm < 0.35:
        parts.append("Use a casual, conversational tone.")
    elif fm > 0.65:
        parts.append("Use a more professional, polished tone.")

    if not parts:
        return ""

    return "\n\nInteraction style preferences (learned from this user's history):\n" + "\n".join(
        f"- {p}" for p in parts
    )
