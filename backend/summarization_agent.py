"""Summarization agent for conversation compression.

Compresses previous_summary + messages_since into a concise new summary.
Uses a cheap model (gemini-2.5-flash-lite) to keep costs low. Designed to
be triggered after every N messages via async background task.
"""

import logging
from typing import Any

from .agents import UsageStats, estimate_cost
from .database import (
    create_summary,
    get_latest_summary,
    get_message_count_since_summary,
    get_messages_since_summary,
)
from .llm import acomplete

logger = logging.getLogger(__name__)

# Default model for summarization — cheap and fast
SUMMARIZATION_MODEL = "google/gemini-2.5-flash-lite"

# Default number of messages before triggering summarization
DEFAULT_SUMMARY_TRIGGER_N = 20

SUMMARIZATION_SYSTEM_PROMPT = """\
You are a conversation summarizer for a personal information management app called Reli.

Your job is to compress a conversation history into a concise summary that preserves
the essential context needed for future interactions.

## What to PRESERVE:
- User identity details (name, preferences, personal context)
- Ongoing topics and active projects being discussed
- Recent decisions and their rationale
- References to Things (tasks, notes, people, projects, etc.) by title
- Action items or commitments made
- Unresolved questions or open threads
- User's emotional tone or urgency if relevant

## What to DROP:
- Exact wording of messages (paraphrase instead)
- Redundant back-and-forth (e.g., clarification exchanges — just keep the conclusion)
- Resolved questions (only note the resolution if it affects future context)
- Pleasantries, greetings, and small talk
- Technical details about how the system processed requests
- Duplicate information already in the previous summary

## Output format:
Write a concise summary in plain text paragraphs. Use present tense for ongoing
states ("User is working on...") and past tense for completed actions ("User created...").
Group related topics together. Keep the summary under 500 words.

If a previous summary is provided, integrate the new messages into it — don't just
append. Merge overlapping topics and drop information that is no longer relevant.
"""


async def summarize_conversation(
    user_id: str,
    *,
    model: str | None = None,
    usage_stats: UsageStats | None = None,
    api_key: str | None = None,
) -> dict[str, Any] | None:
    """Generate a conversation summary from recent messages.

    Returns a dict with summary_text, messages_summarized_up_to, token_count,
    or None if there are no messages to summarize.
    """
    model = model or SUMMARIZATION_MODEL
    messages_since = get_messages_since_summary(user_id)

    if not messages_since:
        logger.debug("No messages to summarize for user %s", user_id)
        return None

    # Build the user prompt
    previous_summary = get_latest_summary(user_id)
    prompt_parts: list[str] = []

    if previous_summary:
        prompt_parts.append(f"## Previous Summary\n{previous_summary['summary_text']}")

    prompt_parts.append("## New Messages")
    for msg in messages_since:
        role_label = "User" if msg["role"] == "user" else "Assistant"
        content = msg["content"]
        # Truncate very long messages to avoid blowing up the context
        if len(content) > 2000:
            content = content[:2000] + "... [truncated]"
        prompt_parts.append(f"**{role_label}**: {content}")

    prompt_parts.append(
        "\n---\nPlease produce an updated summary integrating the new messages with any previous summary."
    )

    llm_messages = [
        {"role": "system", "content": SUMMARIZATION_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(prompt_parts)},
    ]

    kwargs: dict[str, Any] = {}
    if api_key:
        kwargs["api_key"] = api_key

    response = await acomplete(llm_messages, model, **kwargs)

    summary_text = response.choices[0].message.content or ""

    # Track usage
    usage = response.usage
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0
    total_tokens = prompt_tokens + completion_tokens
    cost = estimate_cost(model, prompt_tokens, completion_tokens)

    if usage_stats:
        usage_stats.accumulate(
            prompt_tokens,
            completion_tokens,
            total_tokens,
            cost,
            model,
        )

    # Persist the summary
    last_msg_id = messages_since[-1]["id"]
    row_id = create_summary(
        user_id=user_id,
        summary_text=summary_text,
        messages_summarized_up_to=last_msg_id,
        token_count=total_tokens,
    )

    logger.info(
        "Created conversation summary #%d for user %s: %d messages compressed, %d tokens used, $%.6f cost",
        row_id,
        user_id,
        len(messages_since),
        total_tokens,
        cost,
    )

    return {
        "id": row_id,
        "summary_text": summary_text,
        "messages_summarized_up_to": last_msg_id,
        "messages_compressed": len(messages_since),
        "token_count": total_tokens,
        "cost_usd": cost,
    }


def should_summarize(user_id: str, trigger_n: int = DEFAULT_SUMMARY_TRIGGER_N) -> bool:
    """Check if the message count since last summary has reached the trigger threshold."""
    count = get_message_count_since_summary(user_id)
    return count >= trigger_n
