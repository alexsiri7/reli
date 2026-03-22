"""Chat history endpoints and the multi-agent chat pipeline."""

import asyncio
import json
import logging
import sqlite3
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from ..auth import require_user, user_filter
from ..database import db, get_latest_summary
from ..models import (
    CallUsage,
    ChatMessage,
    ChatMessageCreate,
    ChatRequest,
    ChatResponse,
    MigrateSessionRequest,
    ModelUsage,
    SessionUsage,
    ThinkRequest,
    ThinkResponse,
    UsageInfo,
)
from ..pipeline import ChatPipeline
from .settings import get_user_api_key, get_user_chat_context_window, get_user_interaction_style, get_user_models

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


def _parse_dt(val: str | None) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    return datetime.fromisoformat(val)


def _row_to_msg(row: sqlite3.Row, usage_rows: list[sqlite3.Row] | None = None) -> ChatMessage:
    changes = row["applied_changes"]
    if isinstance(changes, str):
        changes = json.loads(changes) if changes else None
    # Prefer per-call usage from the dedicated table; fall back to applied_changes JSON
    per_call_usage: list[CallUsage] = []
    if usage_rows:
        per_call_usage = [
            CallUsage(
                model=u["model"],
                prompt_tokens=u["prompt_tokens"],
                completion_tokens=u["completion_tokens"],
                cost_usd=u["cost_usd"],
            )
            for u in usage_rows
        ]
    elif isinstance(changes, dict) and "per_call_usage" in changes:
        per_call_usage = [CallUsage(**c) for c in changes["per_call_usage"]]
    return ChatMessage(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        applied_changes=changes,
        prompt_tokens=row["prompt_tokens"] or 0,
        completion_tokens=row["completion_tokens"] or 0,
        cost_usd=row["cost_usd"] or 0.0,
        model=row["model"],
        per_call_usage=per_call_usage,
        timestamp=_parse_dt(row["timestamp"]) or datetime.min,
    )


@router.get("/history/{session_id}", response_model=list[ChatMessage], summary="Get chat history for a session")
def get_history(
    session_id: str,
    limit: int = Query(50, ge=1, le=500, description="Maximum number of messages to return"),
    before: int | None = Query(None, description="Return messages with id < before (for loading older messages)"),
    user_id: str = Depends(require_user),
) -> list[ChatMessage]:
    """Retrieve chat messages for a session, ordered chronologically. Supports cursor-based pagination via `before`."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        if before is not None:
            rows = conn.execute(
                f"SELECT * FROM chat_history WHERE session_id = ? AND id < ?{uf_sql} ORDER BY id DESC LIMIT ?",
                [session_id, before, *uf_params, limit],
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM chat_history WHERE session_id = ?{uf_sql} ORDER BY id DESC LIMIT ?",
                [session_id, *uf_params, limit],
            ).fetchall()
            rows = list(reversed(rows))

        # Fetch per-call usage from chat_message_usage table
        msg_ids = [r["id"] for r in rows]
        usage_by_msg: dict[int, list[sqlite3.Row]] = {}
        if msg_ids:
            placeholders = ",".join("?" for _ in msg_ids)
            usage_rows = conn.execute(
                f"SELECT * FROM chat_message_usage WHERE chat_message_id IN ({placeholders}) ORDER BY id",
                msg_ids,
            ).fetchall()
            for u in usage_rows:
                usage_by_msg.setdefault(u["chat_message_id"], []).append(u)

    return [_row_to_msg(r, usage_by_msg.get(r["id"])) for r in rows]


@router.post(
    "/history", response_model=ChatMessage, status_code=status.HTTP_201_CREATED, summary="Append a chat message"
)
def append_message(body: ChatMessageCreate, user_id: str = Depends(require_user)) -> ChatMessage:
    """Append a single chat message to a session's history."""
    changes_json = json.dumps(body.applied_changes) if body.applied_changes is not None else None
    with db() as conn:
        cursor = conn.execute(
            "INSERT INTO chat_history (session_id, role, content, applied_changes, user_id) VALUES (?, ?, ?, ?, ?)",
            (body.session_id, body.role, body.content, changes_json, user_id or None),
        )
        row = conn.execute("SELECT * FROM chat_history WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _row_to_msg(row)


@router.delete(
    "/history/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a session's chat history"
)
def delete_history(session_id: str, user_id: str = Depends(require_user)) -> None:
    """Delete all messages in a chat session."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        result = conn.execute(f"DELETE FROM chat_history WHERE session_id = ?{uf_sql}", [session_id, *uf_params])
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"No chat history found for session '{session_id}'")


@router.post("/migrate-session", status_code=status.HTTP_200_OK, summary="Migrate chat history to a new session ID")
def migrate_session(body: MigrateSessionRequest, user_id: str = Depends(require_user)) -> dict:
    """Migrate all chat history and usage records from old_session_id to new_session_id for the current user."""
    if body.old_session_id == body.new_session_id:
        return {"migrated": 0}
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        chat_result = conn.execute(
            f"UPDATE chat_history SET session_id = ? WHERE session_id = ?{uf_sql}",
            [body.new_session_id, body.old_session_id, *uf_params],
        )
        usage_result = conn.execute(
            f"UPDATE usage_log SET session_id = ? WHERE session_id = ?{uf_sql}",
            [body.new_session_id, body.old_session_id, *uf_params],
        )
    return {"migrated": chat_result.rowcount + usage_result.rowcount}


# ---------------------------------------------------------------------------
# History enrichment
# ---------------------------------------------------------------------------


def _build_enrichment_summary(raw_applied_changes: Any) -> str:
    """Build a human-readable enrichment summary from applied_changes JSON.

    Returns a short summary string describing which Things were involved
    (context, created, updated) or an empty string if there's nothing to report.
    """
    if not raw_applied_changes:
        return ""

    changes = json.loads(raw_applied_changes) if isinstance(raw_applied_changes, str) else raw_applied_changes
    if not isinstance(changes, dict):
        return ""

    parts: list[str] = []

    # Context things: Things that informed the response
    context_things = changes.get("context_things", [])
    if context_things:
        labels = [
            f"{t.get('title', t.get('id', '?'))}" + (f" ({t['type_hint']})" if t.get("type_hint") else "")
            for t in context_things
        ]
        parts.append(f"[Context: {', '.join(labels)}]")

    # Created/updated things from storage changes
    for key, verb in [("created", "Created"), ("updated", "Updated")]:
        items = changes.get(key, [])
        if items:
            labels = [
                f"{t.get('title', t.get('id', '?'))}" + (f" ({t.get('type_hint', '')})" if t.get("type_hint") else "")
                for t in items
            ]
            parts.append(f"[{verb}: {', '.join(labels)}]")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Async summarization trigger
# ---------------------------------------------------------------------------


def _maybe_trigger_summarization(user_id: str) -> None:
    """Fire-and-forget summarization if message count has reached the threshold.

    Runs in a background asyncio task so it never blocks the chat response.
    """
    from ..summarization_agent import should_summarize, summarize_conversation

    if not user_id or not should_summarize(user_id):
        return

    async def _run() -> None:
        try:
            await summarize_conversation(user_id)
        except Exception:
            logger.exception("Background summarization failed for user %s", user_id)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        # No running event loop — skip (shouldn't happen in normal FastAPI flow)
        logger.warning("No event loop available for background summarization")


# ---------------------------------------------------------------------------
# Multi-agent pipeline endpoints
# ---------------------------------------------------------------------------


def _build_pipeline(user_id: str, mode: str = "normal") -> ChatPipeline:
    """Build a ChatPipeline configured for the given user and mode."""
    user_api_key = get_user_api_key(user_id)
    user_models = get_user_models(user_id)
    context_window = get_user_chat_context_window(user_id)
    interaction_style = get_user_interaction_style(user_id)

    pipeline = ChatPipeline(
        user_id=user_id,
        user_api_key=user_api_key,
        user_models=user_models,
        context_window=context_window,
        mode=mode,
        interaction_style=interaction_style,
    )
    return pipeline


def _fetch_history(session_id: str, context_window: int, user_id: str = "") -> list[dict[str, Any]]:
    """Fetch conversation history for the pipeline.

    If a conversation summary exists for the user, returns the summary as a
    system message followed by only the messages since that summary. Otherwise
    falls back to the most recent N messages (original behaviour).
    """
    history_limit = context_window * 2

    # Try summary-based history if we have a user_id
    if user_id:
        latest_summary = get_latest_summary(user_id)
        if latest_summary:
            with db() as conn:
                rows = conn.execute(
                    "SELECT role, content, applied_changes FROM chat_history"
                    " WHERE session_id = ? AND id > ?"
                    " ORDER BY timestamp ASC LIMIT ?",
                    (session_id, latest_summary["messages_summarized_up_to"], history_limit),
                ).fetchall()
            messages = []
            for r in rows:
                entry: dict[str, Any] = {"role": r["role"], "content": r["content"] or ""}
                if r["role"] == "assistant":
                    s = _build_enrichment_summary(r["applied_changes"])
                    if s:
                        entry["enrichment_metadata"] = s
                messages.append(entry)
            # Prepend summary as context
            return [
                {"role": "system", "content": f"[Conversation summary]\n{latest_summary['summary_text']}"},
                *messages,
            ]

    # Fallback: raw history (no summary available or no user_id)
    with db() as conn:
        rows = conn.execute(
            "SELECT role, content, applied_changes FROM chat_history"
            " WHERE session_id = ? ORDER BY timestamp ASC LIMIT ?",
            (session_id, history_limit),
        ).fetchall()
    result = []
    for r in rows:
        entry = {"role": r["role"], "content": r["content"] or ""}
        if r["role"] == "assistant":
            summary = _build_enrichment_summary(r["applied_changes"])
            if summary:
                entry["enrichment_metadata"] = summary
        result.append(entry)
    return result


def _persist_exchange(
    session_id: str,
    user_id: str,
    message: str,
    reply: str,
    result: Any,
    usage: Any,
) -> dict[str, Any]:
    """Persist both sides of a chat exchange and return enriched applied_changes."""
    applied_changes: dict[str, Any] = result.applied_changes

    # Build context_things list
    context_things = [
        {"id": t["id"], "title": t.get("title", ""), "type_hint": t.get("type_hint")} for t in result.relevant_things
    ]

    applied_with_sources = applied_changes.copy()
    applied_with_sources["context_things"] = context_things
    if result.web_results:
        applied_with_sources["web_results"] = result.web_results
    if usage.calls:
        applied_with_sources["per_call_usage"] = [
            {
                "model": c.model,
                "prompt_tokens": c.prompt_tokens,
                "completion_tokens": c.completion_tokens,
                "cost_usd": round(c.cost_usd, 6),
            }
            for c in usage.calls
        ]
    if result.gmail_context:
        applied_with_sources["gmail_context"] = result.gmail_context
    if result.calendar_events:
        applied_with_sources["calendar_events"] = result.calendar_events
    changes_json = json.dumps(applied_with_sources)

    with db() as conn:
        conn.execute(
            "INSERT INTO chat_history (session_id, role, content, applied_changes, user_id) VALUES (?, ?, ?, ?, ?)",
            (session_id, "user", message, None, user_id or None),
        )
        cursor = conn.execute(
            "INSERT INTO chat_history"
            " (session_id, role, content, applied_changes,"
            " prompt_tokens, completion_tokens, cost_usd, api_calls, model, user_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                "assistant",
                reply,
                changes_json,
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.cost_usd,
                usage.api_calls,
                usage.model,
                user_id or None,
            ),
        )
        assistant_msg_id = cursor.lastrowid

        # Insert per-call usage into chat_message_usage for structured retrieval
        num_calls = len(usage.calls)
        stage_labels: list[str | None] = []
        if num_calls >= 1:
            # Last call is response, all others are reasoning
            # (reasoning agent may make multiple calls due to tool use)
            for _ in range(max(0, num_calls - 1)):
                stage_labels.append("reasoning")
            stage_labels.append("response")
        while len(stage_labels) < num_calls:
            stage_labels.append(None)
        for i, call in enumerate(usage.calls):
            stage = stage_labels[i] if i < len(stage_labels) else None
            conn.execute(
                "INSERT INTO chat_message_usage"
                " (chat_message_id, stage, model, prompt_tokens, completion_tokens, cost_usd)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (assistant_msg_id, stage, call.model, call.prompt_tokens, call.completion_tokens, call.cost_usd),
            )

        # Insert per-call usage records into usage_log for daily aggregation
        for call in usage.calls:
            conn.execute(
                "INSERT INTO usage_log (session_id, model, prompt_tokens, completion_tokens, cost_usd, user_id)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, call.model, call.prompt_tokens, call.completion_tokens, call.cost_usd, user_id or None),
            )

    return applied_with_sources


@router.post("", response_model=ChatResponse, summary="Send a message through the multi-agent pipeline")
async def chat(body: ChatRequest, user_id: str = Depends(require_user)) -> ChatResponse:
    """4-stage pipeline: Context → Retrieve → Reasoning → Validate → Respond."""
    session_id = body.session_id
    message = body.message
    mode = body.mode if body.mode in ("normal", "planning") else "normal"

    pipeline = _build_pipeline(user_id, mode=mode)
    history = _fetch_history(session_id, pipeline.context_window, user_id)

    result = await pipeline.run(message, history, session_id=session_id)

    applied_with_sources = _persist_exchange(
        session_id,
        user_id,
        message,
        result.reply,
        result,
        result.usage,
    )

    # Trigger async summarization if message count threshold reached
    _maybe_trigger_summarization(user_id)

    daily_usage = _compute_daily_usage(user_id)

    return ChatResponse(
        session_id=session_id,
        reply=result.reply,
        applied_changes=applied_with_sources,
        questions_for_user=result.questions_for_user,
        mode=mode,
        usage=UsageInfo(**result.usage.to_dict()),
        session_usage=daily_usage,
    )


@router.post("/think", response_model=ThinkResponse, summary="Run reasoning agent only (no response generation)")
async def think(body: ThinkRequest, user_id: str = Depends(require_user)) -> ThinkResponse:
    """Reasoning-as-a-service: run the reasoning agent on a natural-language
    message and return structured instructions (what was created, updated,
    linked, deleted).  No user-facing response is generated.

    Designed for MCP ``reli_think`` tool where the calling agent handles
    presentation and may follow up with CRUD tools.
    """
    mode = body.mode if body.mode in ("normal", "planning") else "normal"
    pipeline = _build_pipeline(user_id, mode=mode)

    history: list[dict[str, Any]] = []
    if body.session_id:
        history = _fetch_history(body.session_id, pipeline.context_window, user_id)

    result = await pipeline.think(body.message, history, session_id=body.session_id)

    usage_stats = result.get("usage")
    usage_info = UsageInfo(**usage_stats.to_dict()) if usage_stats else None

    return ThinkResponse(
        applied_changes=result["applied_changes"],
        questions_for_user=result["questions_for_user"],
        priority_question=result["priority_question"],
        reasoning_summary=result["reasoning_summary"],
        briefing_mode=result["briefing_mode"],
        relevant_things=result["relevant_things"],
        usage=usage_info,
    )


@router.post("/stream", summary="Stream a chat response via SSE")
async def chat_stream(body: ChatRequest, user_id: str = Depends(require_user)) -> StreamingResponse:
    """SSE streaming version of the chat pipeline.

    Emits events:
      - stage: {"stage": "<name>", "status": "started"|"complete"}
      - token: {"text": "<chunk>"}
      - complete: full ChatResponse JSON (same schema as POST /chat)
      - error: {"message": "<error>"}
    """

    async def event_generator() -> AsyncIterator[str]:
        try:
            session_id = body.session_id
            message = body.message
            mode = body.mode if body.mode in ("normal", "planning") else "normal"

            pipeline = _build_pipeline(user_id, mode=mode)
            history = _fetch_history(session_id, pipeline.context_window, user_id)

            result = None
            reply = ""

            async for event in pipeline.run_stream(message, history, session_id=session_id):
                if event.type == "stage_start":
                    yield _sse("stage", {"stage": event.stage, "status": "started"})
                elif event.type == "stage_complete":
                    yield _sse("stage", {"stage": event.stage, "status": "complete"})
                elif event.type == "token":
                    yield _sse("token", {"text": event.data})
                elif event.type == "complete":
                    result = event.data

            if result is None:
                yield _sse("error", {"message": "Pipeline did not produce a result"})
                return

            reply = result.reply

            applied_with_sources = _persist_exchange(
                session_id,
                user_id,
                message,
                reply,
                result,
                result.usage,
            )

            # Trigger async summarization if message count threshold reached
            _maybe_trigger_summarization(user_id)

            daily_usage = _compute_daily_usage(user_id)

            complete_data = ChatResponse(
                session_id=session_id,
                reply=reply,
                applied_changes=applied_with_sources,
                questions_for_user=result.questions_for_user,
                mode=mode,
                usage=UsageInfo(**result.usage.to_dict()),
                session_usage=daily_usage,
            )
            yield _sse("complete", complete_data.model_dump())

        except Exception as e:
            logger.exception("Streaming chat pipeline error")
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: str, data: Any) -> str:  # noqa: ANN401
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _compute_daily_usage(user_id: str = "") -> SessionUsage:
    """Aggregate usage stats for today (since midnight local time)."""
    today_start = datetime.combine(date.today(), datetime.min.time()).isoformat()
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        totals_row = conn.execute(
            "SELECT COALESCE(SUM(prompt_tokens), 0) as pt, COALESCE(SUM(completion_tokens), 0) as ct, "
            "COUNT(*) as calls, COALESCE(SUM(cost_usd), 0) as cost "
            f"FROM usage_log WHERE timestamp >= ?{uf_sql}",
            [today_start, *uf_params],
        ).fetchone()

        model_rows = conn.execute(
            "SELECT model, COALESCE(SUM(prompt_tokens), 0) as pt, COALESCE(SUM(completion_tokens), 0) as ct, "
            "COUNT(*) as calls, COALESCE(SUM(cost_usd), 0) as cost "
            f"FROM usage_log WHERE timestamp >= ?{uf_sql} "
            "GROUP BY model ORDER BY cost DESC",
            [today_start, *uf_params],
        ).fetchall()

    per_model = [
        ModelUsage(
            model=r["model"],
            prompt_tokens=r["pt"],
            completion_tokens=r["ct"],
            total_tokens=r["pt"] + r["ct"],
            api_calls=r["calls"],
            cost_usd=round(r["cost"], 6),
        )
        for r in model_rows
    ]

    return SessionUsage(
        prompt_tokens=totals_row["pt"],
        completion_tokens=totals_row["ct"],
        total_tokens=totals_row["pt"] + totals_row["ct"],
        api_calls=totals_row["calls"],
        cost_usd=round(totals_row["cost"], 6),
        per_model=per_model,
    )


@router.get("/stats/today", response_model=SessionUsage, summary="Get today's usage stats")
def get_daily_stats(user_id: str = Depends(require_user)) -> SessionUsage:
    """Return aggregated usage stats for today (since midnight local time)."""
    return _compute_daily_usage(user_id)
