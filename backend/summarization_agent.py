"""Summarization agent for conversation compression.

Compresses previous_summary + messages_since into a concise new summary.
Uses the context (cheap) model from config.yaml to keep costs low. Designed to
be triggered after every N messages via async background task.
"""

import logging
from typing import Any

from sqlmodel import Session, select

import backend.db_engine as _engine_mod

from .agents import UsageStats, estimate_cost
from .db_models import ChatHistoryRecord, ConversationSummaryRecord
from .llm import acomplete

logger = logging.getLogger(__name__)

# Use the context (cheap) model from config for summarization
from .agents import REQUESTY_MODEL as SUMMARIZATION_MODEL  # noqa: E402

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def get_latest_summary(user_id: str) -> dict[str, Any] | None:
    with Session(_engine_mod.engine) as session:
        record = session.exec(
            select(ConversationSummaryRecord)
            .where(ConversationSummaryRecord.user_id == user_id)
            .order_by(ConversationSummaryRecord.messages_summarized_up_to.desc())  # type: ignore[union-attr]
        ).first()
    if not record:
        return None
    return {
        "id": record.id,
        "summary_text": record.summary_text,
        "messages_summarized_up_to": record.messages_summarized_up_to,
        "token_count": record.token_count,
        "created_at": record.created_at,
    }


def create_summary(
    user_id: str,
    summary_text: str,
    messages_summarized_up_to: int,
    token_count: int = 0,
) -> int:
    with Session(_engine_mod.engine) as session:
        record = ConversationSummaryRecord(
            user_id=user_id,
            summary_text=summary_text,
            messages_summarized_up_to=messages_summarized_up_to,
            token_count=token_count,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        if record.id is None:
            raise RuntimeError("INSERT into conversation_summaries failed to return id")
        return record.id


def get_messages_since_summary(user_id: str) -> list[dict[str, Any]]:
    latest = get_latest_summary(user_id)
    with Session(_engine_mod.engine) as session:
        stmt = (
            select(ChatHistoryRecord).where(ChatHistoryRecord.user_id == user_id).order_by(ChatHistoryRecord.id.asc())
        )  # type: ignore[union-attr]
        if latest:
            stmt = stmt.where(ChatHistoryRecord.id > latest["messages_summarized_up_to"])
        records = session.exec(stmt).all()
    return [
        {"id": r.id, "session_id": r.session_id, "role": r.role, "content": r.content, "timestamp": r.timestamp}
        for r in records
    ]


def get_message_count_since_summary(user_id: str) -> int:
    latest = get_latest_summary(user_id)
    with Session(_engine_mod.engine) as session:
        from sqlalchemy import func

        stmt = select(func.count()).select_from(ChatHistoryRecord).where(ChatHistoryRecord.user_id == user_id)
        if latest:
            stmt = stmt.where(ChatHistoryRecord.id > latest["messages_summarized_up_to"])
        result = session.exec(stmt).one()
    return result or 0


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
