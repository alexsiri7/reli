"""Personality signal detection for the Reli chat pipeline.

Analyzes user messages and conversation history to detect personality
preference signals — positive, negative, explicit corrections, and implicit
corrections. Detected signals are persisted as preference Things, enabling
the response agent to adapt over time (personality backpropagation).

Signal types:
  - positive: user follows suggestion, says thanks, engages
  - negative: user says "too much detail", ignores suggestion, rephrases
  - explicit_correction: direct instruction like "no emoji", "be more concise"
  - implicit_correction: behavioral pattern like consistently editing output
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from .agents import REQUESTY_RESPONSE_MODEL, UsageStats
from .auth import user_filter
from .database import db
from .tracing import get_tracer

logger = logging.getLogger(__name__)

_tracer = get_tracer("reli.signal_detector")

# ---------------------------------------------------------------------------
# Signal detection prompt
# ---------------------------------------------------------------------------

_SIGNAL_DETECTION_SYSTEM = """\
You are a signal detector for personality preference learning. Analyze the
user's latest message in the context of the conversation history and the
assistant's previous response to detect personality/style feedback signals.

Signal types:
1. **positive** — User shows satisfaction with the response style (says thanks,
   follows suggestion, engages enthusiastically, expresses approval of format).
   Only flag when the positive signal is clearly about HOW Reli communicated,
   not just about WHAT Reli did (e.g. "thanks for tracking that" is about the
   action, not the style — do NOT flag it).
2. **negative** — User shows dissatisfaction with response style (says "too
   much detail", "too long", ignores the response structure, rephrases what
   Reli said more concisely).
3. **explicit_correction** — User directly instructs a style change: "don't
   use emoji", "be more concise", "stop asking so many questions", "use bullet
   points", "be less formal".
4. **implicit_correction** — User's behavior implies a style mismatch. For
   example: user consistently gives terse replies to verbose responses, user
   never engages with proactive suggestions, user rephrases Reli's output in
   a notably different style.

Output JSON:
{
  "signals": [
    {
      "type": "positive|negative|explicit_correction|implicit_correction",
      "pattern": "Short description of the preference pattern detected",
      "dimension": "Dimension: response_length, emoji, formality, proactivity, question_frequency, structure",
      "direction": "strengthen|weaken",
      "confidence": "high|medium|low"
    }
  ]
}

Rules:
- Return an empty signals array if no personality signals are detected.
- Most messages have NO personality signals — be conservative.
- Only detect signals about communication STYLE, not content correctness.
- "Thanks" alone after a task creation is NOT a positive style signal — it's
  just politeness about the action taken.
- Explicit corrections are high confidence. Implicit corrections are low.
- A single instance of an implicit pattern is NOT enough — note it only if
  there is a clear pattern across multiple messages in the history.
- Focus on the LATEST user message but use history for pattern context.
- Maximum 3 signals per analysis (most turns will have 0).
"""


# ---------------------------------------------------------------------------
# Confidence mapping
# ---------------------------------------------------------------------------

# Map signal confidence + type to the preference confidence level and
# observation increment. Explicit corrections are strong immediately.
_CONFIDENCE_MAP: dict[str, dict[str, tuple[str, int]]] = {
    "explicit_correction": {
        "high": ("strong", 3),
        "medium": ("established", 2),
        "low": ("established", 1),
    },
    "positive": {
        "high": ("established", 2),
        "medium": ("emerging", 1),
        "low": ("emerging", 1),
    },
    "negative": {
        "high": ("established", 2),
        "medium": ("emerging", 1),
        "low": ("emerging", 1),
    },
    "implicit_correction": {
        "high": ("emerging", 1),
        "medium": ("emerging", 1),
        "low": ("emerging", 1),
    },
}

# Confidence progression: more observations → higher confidence
_CONFIDENCE_THRESHOLDS = {
    "emerging": 0,  # default for new patterns
    "established": 5,  # after 5 observations
    "strong": 12,  # after 12 observations
}


def _compute_confidence(observations: int) -> str:
    """Derive confidence level from total observation count."""
    if observations >= _CONFIDENCE_THRESHOLDS["strong"]:
        return "strong"
    if observations >= _CONFIDENCE_THRESHOLDS["established"]:
        return "established"
    return "emerging"


# ---------------------------------------------------------------------------
# Signal detection via LLM
# ---------------------------------------------------------------------------


async def _detect_signals_llm(
    message: str,
    history: list[dict[str, Any]],
    last_assistant_reply: str,
    usage_stats: UsageStats | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Call a lightweight LLM to detect personality signals in the conversation.

    Returns a list of signal dicts with keys: type, pattern, dimension,
    direction, confidence.
    """
    from google.adk.agents import LlmAgent

    from .context_agent import _make_litellm_model, _run_agent_for_text

    # Build a compact history summary (last 6 turns max)
    history_block = ""
    for h in history[-6:]:
        role = h.get("role", "user")
        content = h.get("content", "")
        # Truncate long messages to keep prompt small
        if len(content) > 500:
            content = content[:500] + "..."
        history_block += f"<{role}>{content}</{role}>\n"

    user_prompt = (
        f"Conversation history:\n{history_block}\n"
        f"Last assistant response:\n<assistant>{last_assistant_reply[:800]}</assistant>\n\n"
        f"Latest user message:\n<user>{message}</user>\n\n"
        "Analyze for personality signals. Return JSON."
    )

    litellm_model = _make_litellm_model(
        model=model or REQUESTY_RESPONSE_MODEL,
        api_key=api_key,
    )

    agent = LlmAgent(
        name="signal_detector",
        description="Detects personality preference signals from user messages.",
        model=litellm_model,
        instruction=_SIGNAL_DETECTION_SYSTEM,
    )

    with _tracer.start_as_current_span("reli.signal_detection") as span:
        try:
            raw = await _run_agent_for_text(agent, user_prompt, usage_stats)
            span.set_attribute("reli.signal_detection.raw_length", len(raw) if raw else 0)
        except Exception as exc:
            logger.warning("Signal detection LLM call failed: %s", exc)
            span.set_attribute("reli.signal_detection.error", str(exc))
            return []

    if not raw:
        return []

    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last fence lines
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Signal detector returned non-JSON: %s", text[:200])
        return []

    signals = result.get("signals", [])
    if not isinstance(signals, list):
        return []

    # Validate signal structure
    valid_types = {"positive", "negative", "explicit_correction", "implicit_correction"}
    valid_directions = {"strengthen", "weaken"}
    validated: list[dict[str, Any]] = []
    for s in signals[:3]:  # max 3 signals
        if not isinstance(s, dict):
            continue
        if s.get("type") not in valid_types:
            continue
        if s.get("direction") not in valid_directions:
            continue
        if not s.get("pattern"):
            continue
        validated.append(
            {
                "type": s["type"],
                "pattern": str(s["pattern"])[:200],
                "dimension": str(s.get("dimension", "general"))[:50],
                "direction": s["direction"],
                "confidence": s.get("confidence", "low"),
            }
        )

    return validated


# ---------------------------------------------------------------------------
# Preference Thing persistence
# ---------------------------------------------------------------------------

_PREFERENCE_THING_TITLE = "Reli Communication Preferences"


def _find_preference_thing(user_id: str) -> dict[str, Any] | None:
    """Find the user's personality preference Thing, if it exists."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        row = conn.execute(
            f"SELECT * FROM things WHERE type_hint = 'preference' AND active = 1 AND title = ?{uf_sql} LIMIT 1",
            [_PREFERENCE_THING_TITLE, *uf_params],
        ).fetchone()
        return dict(row) if row else None


def _load_existing_patterns(thing: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse patterns from a preference Thing's data field."""
    raw = thing.get("data")
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return []
    patterns = data.get("patterns", [])
    return [p for p in patterns if isinstance(p, dict) and "pattern" in p]


def _match_existing_pattern(
    existing: list[dict[str, Any]],
    new_pattern: str,
    dimension: str,
) -> int | None:
    """Find index of an existing pattern matching the new signal.

    Matches by dimension first, then by pattern text similarity.
    Returns the index or None.
    """
    new_lower = new_pattern.lower()
    # Exact dimension match with similar pattern text
    for i, p in enumerate(existing):
        p_dim = p.get("dimension", "general")
        if p_dim == dimension:
            # Same dimension — likely the same preference evolving
            return i
        # Fuzzy: check if patterns are textually very similar
        p_lower = p.get("pattern", "").lower()
        if p_lower == new_lower:
            return i
    return None


def apply_signals(
    signals: list[dict[str, Any]],
    user_id: str,
) -> dict[str, Any]:
    """Apply detected signals to the user's personality preference Thing.

    Creates the preference Thing if it doesn't exist. Updates pattern
    confidence and observation counts for existing patterns, or adds new ones.

    Returns a summary dict of what changed.
    """
    if not signals or not user_id:
        return {"updated": 0, "created": 0}

    now = datetime.now(timezone.utc).isoformat()
    pref_thing = _find_preference_thing(user_id)
    existing_patterns = _load_existing_patterns(pref_thing) if pref_thing else []

    created_count = 0
    updated_count = 0

    for signal in signals:
        sig_type = signal["type"]
        sig_confidence = signal.get("confidence", "low")
        pattern_text = signal["pattern"]
        dimension = signal.get("dimension", "general")
        direction = signal["direction"]

        # Get confidence bump from the signal type/confidence
        pref_confidence, obs_increment = _CONFIDENCE_MAP.get(sig_type, {}).get(sig_confidence, ("emerging", 1))

        # Check for existing pattern on this dimension
        idx = _match_existing_pattern(existing_patterns, pattern_text, dimension)

        if idx is not None:
            # Update existing pattern
            existing = existing_patterns[idx]
            old_obs = existing.get("observations", 1)

            if direction == "weaken":
                # Weakening reduces observations (min 0)
                new_obs = max(0, old_obs - obs_increment)
                if new_obs == 0:
                    # Pattern has been fully weakened — remove it
                    existing_patterns.pop(idx)
                    updated_count += 1
                    continue
            else:
                new_obs = old_obs + obs_increment

            existing["observations"] = new_obs
            existing["confidence"] = _compute_confidence(new_obs)
            existing["pattern"] = pattern_text  # Update text to latest wording
            existing["dimension"] = dimension
            existing["last_signal"] = now
            updated_count += 1
        else:
            if direction == "weaken":
                # Can't weaken a pattern that doesn't exist — skip
                continue
            # Create new pattern
            existing_patterns.append(
                {
                    "pattern": pattern_text,
                    "dimension": dimension,
                    "confidence": pref_confidence,
                    "observations": obs_increment,
                    "last_signal": now,
                }
            )
            created_count += 1

    # Persist to database
    patterns_data = json.dumps({"patterns": existing_patterns})

    with db() as conn:
        if pref_thing:
            # Update existing preference Thing
            conn.execute(
                "UPDATE things SET data = ?, updated_at = ? WHERE id = ?",
                (patterns_data, now, pref_thing["id"]),
            )
        else:
            # Create new preference Thing
            import uuid

            thing_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO things
                   (id, title, type_hint, active, surface, data,
                    created_at, updated_at, user_id, priority)
                   VALUES (?, ?, 'preference', 1, 0, ?, ?, ?, ?, 3)""",
                (thing_id, _PREFERENCE_THING_TITLE, patterns_data, now, now, user_id),
            )

    logger.info(
        "Signal detection applied: %d updated, %d created patterns for user %s",
        updated_count,
        created_count,
        user_id,
    )

    return {"updated": updated_count, "created": created_count}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def detect_and_apply_signals(
    message: str,
    history: list[dict[str, Any]],
    last_assistant_reply: str,
    user_id: str,
    usage_stats: UsageStats | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Detect personality signals from the latest message and apply them.

    This is the main entry point called from the pipeline after both the
    reasoning and response stages complete.

    Returns a summary dict with signal detection results.
    """
    if not user_id:
        return {"signals": [], "applied": {"updated": 0, "created": 0}}

    with _tracer.start_as_current_span("reli.personality_backprop") as span:
        signals = await _detect_signals_llm(
            message,
            history,
            last_assistant_reply,
            usage_stats=usage_stats,
            api_key=api_key,
            model=model,
        )

        span.set_attribute("reli.signals_detected", len(signals))

        if not signals:
            return {"signals": [], "applied": {"updated": 0, "created": 0}}

        logger.info(
            "Detected %d personality signals: %s",
            len(signals),
            json.dumps(signals, default=str),
        )

        applied = apply_signals(signals, user_id)
        span.set_attribute("reli.signals_applied_updated", applied["updated"])
        span.set_attribute("reli.signals_applied_created", applied["created"])

        return {"signals": signals, "applied": applied}
