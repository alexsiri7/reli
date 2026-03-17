"""Dynamic interaction style calibration between coaching and consultant modes.

Determines whether Reli should act as a coach (asking questions, guiding
discovery) or a consultant (providing answers, recommending actions) based
on user preferences and conversational context.
"""

from enum import Enum
from typing import Any


class InteractionStyle(str, Enum):
    """Interaction style modes."""

    COACHING = "coaching"
    CONSULTANT = "consultant"
    ADAPTIVE = "adaptive"  # dynamically choose based on context


# ---------------------------------------------------------------------------
# Context signal detection
# ---------------------------------------------------------------------------

# Keywords/patterns that suggest the user wants guidance (coaching)
_COACHING_SIGNALS = {
    "how should i",
    "what do you think",
    "help me decide",
    "not sure",
    "i'm stuck",
    "where do i start",
    "help me figure",
    "what would you suggest",
    "any ideas",
    "brainstorm",
    "thinking about",
    "considering",
    "torn between",
    "pros and cons",
    "what are my options",
}

# Keywords/patterns that suggest the user wants direct answers (consultant)
_CONSULTANT_SIGNALS = {
    "just do it",
    "just tell me",
    "what's the answer",
    "give me",
    "i need",
    "set up",
    "create",
    "schedule",
    "remind me",
    "add",
    "delete",
    "update",
    "change",
    "mark",
    "done",
    "finished",
    "complete",
}


def _detect_context_style(message: str, history: list[dict[str, Any]]) -> InteractionStyle | None:
    """Analyze the message and recent history to suggest a style.

    Returns None if no strong signal is detected (let the default apply).
    """
    msg_lower = message.lower()

    coaching_score: float = sum(1 for signal in _COACHING_SIGNALS if signal in msg_lower)
    consultant_score: float = sum(1 for signal in _CONSULTANT_SIGNALS if signal in msg_lower)

    # Check if this is a question (coaching-leaning)
    if msg_lower.rstrip().endswith("?"):
        coaching_score += 1

    # Check recent history for patterns — if the user has been asking lots of
    # questions, lean coaching; if they've been giving commands, lean consultant
    recent = history[-4:] if history else []
    for entry in recent:
        if entry.get("role") == "user":
            content = (entry.get("content") or "").lower()
            if content.rstrip().endswith("?"):
                coaching_score += 0.5
            if any(s in content for s in ("create", "add", "schedule", "remind")):
                consultant_score += 0.5

    if coaching_score > consultant_score + 1:
        return InteractionStyle.COACHING
    if consultant_score > coaching_score + 1:
        return InteractionStyle.CONSULTANT

    return None


def determine_style(
    user_preference: str,
    message: str,
    history: list[dict[str, Any]],
    briefing_mode: bool = False,
) -> InteractionStyle:
    """Determine the effective interaction style for this turn.

    Args:
        user_preference: The user's stored preference ("coaching", "consultant", "adaptive").
        message: The current user message.
        history: Recent conversation history.
        briefing_mode: Whether we're in briefing mode (always consultant).

    Returns:
        The style to use for this interaction turn.
    """
    # Briefing mode is always consultant-style (direct, action-oriented)
    if briefing_mode:
        return InteractionStyle.CONSULTANT

    # If user has an explicit non-adaptive preference, respect it
    try:
        pref = InteractionStyle(user_preference)
    except ValueError:
        pref = InteractionStyle.ADAPTIVE

    if pref != InteractionStyle.ADAPTIVE:
        return pref

    # Adaptive mode: detect from context
    detected = _detect_context_style(message, history)
    if detected:
        return detected

    # Default to a balanced consultant style (most users expect direct help)
    return InteractionStyle.CONSULTANT


# ---------------------------------------------------------------------------
# Style-specific prompt fragments
# ---------------------------------------------------------------------------

COACHING_RESPONSE_STYLE = """\
Interaction Style: COACHING MODE
You are guiding the user toward their own insights. Your approach:
- Ask thought-provoking questions before giving answers
- Help the user explore options rather than prescribing solutions
- Use phrases like "What do you think would happen if...", "Have you considered...",
  "What matters most to you about this?"
- Reflect back what the user said to deepen understanding
- Celebrate the user's own realizations: "That's a great insight!"
- When the user is stuck, offer gentle nudges rather than full solutions
- Frame suggestions as possibilities: "One approach could be..." not "You should..."
- Still be warm, supportive, and proactive — but lead with questions
"""

CONSULTANT_RESPONSE_STYLE = """\
Interaction Style: CONSULTANT MODE
You are providing expert, decisive guidance. Your approach:
- Lead with recommendations and action items
- Be direct and confident: "Here's what I'd recommend..." or "The best move is..."
- Provide clear, prioritized next steps
- When presenting options, rank them with your recommendation highlighted
- Proactively suggest improvements and optimizations
- Be efficient — give the answer first, context second
- Use decisive language: "Let's do X" rather than "Maybe we could try X?"
- Still be warm and supportive — but lead with answers, not questions
"""

STYLE_PROMPTS = {
    InteractionStyle.COACHING: COACHING_RESPONSE_STYLE,
    InteractionStyle.CONSULTANT: CONSULTANT_RESPONSE_STYLE,
}


def get_style_prompt(style: InteractionStyle) -> str:
    """Return the prompt fragment for the given interaction style."""
    return STYLE_PROMPTS.get(style, CONSULTANT_RESPONSE_STYLE)


# ---------------------------------------------------------------------------
# Reasoning agent style hints
# ---------------------------------------------------------------------------

COACHING_REASONING_HINT = """\
Interaction Style Hint: The user prefers a COACHING approach. When generating
questions_for_user, prefer open-ended exploratory questions that guide discovery.
Frame priority_question as a thought-provoking prompt rather than a direct ask.
Favor asking the user to reflect on their goals before making changes.
"""

CONSULTANT_REASONING_HINT = """\
Interaction Style Hint: The user prefers a CONSULTANT approach. When generating
questions_for_user, prefer specific clarifying questions that help you take action.
Frame priority_question as a decision point rather than an exploration. Favor making
changes proactively and confirming afterward rather than asking first.
"""

REASONING_STYLE_HINTS = {
    InteractionStyle.COACHING: COACHING_REASONING_HINT,
    InteractionStyle.CONSULTANT: CONSULTANT_REASONING_HINT,
}


def get_reasoning_style_hint(style: InteractionStyle) -> str:
    """Return the reasoning agent hint for the given interaction style."""
    return REASONING_STYLE_HINTS.get(style, "")
