"""Chat history endpoints and the multi-agent chat pipeline."""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, text
from sqlmodel import Session, select

import backend.db_engine as _engine_mod

from ..auth import require_user
from ..db_engine import user_filter_clause, user_filter_text
from ..db_models import (
    ChatHistoryRecord,
    ChatMessageUsageRecord,
    ChatSessionRecord,
    ConversationSummaryRecord,
    UsageLogRecord,
)
from ..models import (
    CallUsage,
    ChatMessage,
    ChatMessageCreate,
    ChatRequest,
    ChatResponse,
    ChatSessionSummary,
    CreateSessionRequest,
    MigrateSessionRequest,
    ModelUsage,
    PatchSessionRequest,
    SessionUsage,
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


def _record_to_msg(record: ChatHistoryRecord, usage_records: list[ChatMessageUsageRecord] | None = None) -> ChatMessage:
    changes = record.applied_changes
    if isinstance(changes, str):
        changes = json.loads(changes) if changes else None
    per_call_usage: list[CallUsage] = []
    if usage_records:
        per_call_usage = [
            CallUsage(
                model=u.model,
                prompt_tokens=u.prompt_tokens,
                completion_tokens=u.completion_tokens,
                cost_usd=u.cost_usd,
            )
            for u in usage_records
        ]
    elif isinstance(changes, dict) and "per_call_usage" in changes:
        per_call_usage = [CallUsage(**c) for c in changes["per_call_usage"]]
    return ChatMessage(
        id=record.id,
        session_id=record.session_id,
        role=record.role,
        content=record.content,
        applied_changes=changes,
        prompt_tokens=record.prompt_tokens or 0,
        completion_tokens=record.completion_tokens or 0,
        cost_usd=record.cost_usd or 0.0,
        model=record.model,
        per_call_usage=per_call_usage,
        timestamp=record.timestamp or datetime.min,
    )


def _row_to_msg(row: Any, usage_rows: Any = None) -> ChatMessage:
    changes = row.applied_changes
    if isinstance(changes, str):
        changes = json.loads(changes) if changes else None
    # Prefer per-call usage from the dedicated table; fall back to applied_changes JSON
    per_call_usage: list[CallUsage] = []
    if usage_rows:
        per_call_usage = [
            CallUsage(
                model=u.model,
                prompt_tokens=u.prompt_tokens,
                completion_tokens=u.completion_tokens,
                cost_usd=u.cost_usd,
            )
            for u in usage_rows
        ]
    elif isinstance(changes, dict) and "per_call_usage" in changes:
        per_call_usage = [CallUsage(**c) for c in changes["per_call_usage"]]
    return ChatMessage(
        id=row.id,
        session_id=row.session_id,
        role=row.role,
        content=row.content,
        applied_changes=changes,
        prompt_tokens=row.prompt_tokens or 0,
        completion_tokens=row.completion_tokens or 0,
        cost_usd=row.cost_usd or 0.0,
        model=row.model,
        per_call_usage=per_call_usage,
        timestamp=_parse_dt(row.timestamp) or datetime.min,
    )


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


@router.get("/history/{session_id}", response_model=list[ChatMessage], summary="Get chat history for a session")
def get_history(
    session_id: str,
    limit: int = Query(50, ge=1, le=500, description="Maximum number of messages to return"),
    before: int | None = Query(None, description="Return messages with id < before (for loading older messages)"),
    user_id: str = Depends(require_user),
) -> list[ChatMessage]:
    """Retrieve chat messages for a session, ordered chronologically. Supports cursor-based pagination via `before`."""
    with Session(_engine_mod.engine) as session:
        stmt = select(ChatHistoryRecord).where(
            ChatHistoryRecord.session_id == session_id,
            user_filter_clause(ChatHistoryRecord.user_id, user_id),
        )
        if before is not None:
            stmt = stmt.where(ChatHistoryRecord.id < before)
            stmt = stmt.order_by(ChatHistoryRecord.id.desc()).limit(limit)  # type: ignore[union-attr]
            records = list(session.exec(stmt).all())
        else:
            stmt = stmt.order_by(ChatHistoryRecord.id.desc()).limit(limit)  # type: ignore[union-attr]
            records = list(reversed(session.exec(stmt).all()))

        # Fetch per-call usage from chat_message_usage table
        msg_ids = [r.id for r in records]
        usage_by_msg: dict[int, list[ChatMessageUsageRecord]] = {}
        if msg_ids:
            usage_records = session.exec(
                select(ChatMessageUsageRecord)
                .where(ChatMessageUsageRecord.chat_message_id.in_(msg_ids))  # type: ignore[union-attr]
                .order_by(ChatMessageUsageRecord.id)  # type: ignore[arg-type]
            ).all()
            for u in usage_records:
                usage_by_msg.setdefault(u.chat_message_id, []).append(u)

    return [_record_to_msg(r, usage_by_msg.get(r.id)) for r in records]


@router.post(
    "/history", response_model=ChatMessage, status_code=status.HTTP_201_CREATED, summary="Append a chat message"
)
def append_message(body: ChatMessageCreate, user_id: str = Depends(require_user)) -> ChatMessage:
    """Append a single chat message to a session's history."""
    changes_json = body.applied_changes  # SQLModel handles JSON serialization
    now = datetime.now(timezone.utc)
    with Session(_engine_mod.engine) as session:
        # Upsert session last_active_at
        existing_session = session.exec(
            select(ChatSessionRecord).where(ChatSessionRecord.id == body.session_id)
        ).first()
        if existing_session:
            existing_session.last_active_at = now
            session.add(existing_session)

        record = ChatHistoryRecord(
            session_id=body.session_id,
            role=body.role,
            content=body.content,
            applied_changes=changes_json,
            user_id=user_id or None,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
    return _record_to_msg(record)


@router.delete(
    "/history/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a session's chat history"
)
def delete_history(session_id: str, user_id: str = Depends(require_user)) -> None:
    """Delete all messages in a chat session."""
    with Session(_engine_mod.engine) as session:
        records = session.exec(
            select(ChatHistoryRecord).where(
                ChatHistoryRecord.session_id == session_id,
                user_filter_clause(ChatHistoryRecord.user_id, user_id),
            )
        ).all()
        if not records:
            raise HTTPException(status_code=404, detail=f"No chat history found for session '{session_id}'")
        for rec in records:
            session.delete(rec)
        session.commit()


# ---------------------------------------------------------------------------
# Chat Sessions CRUD
# ---------------------------------------------------------------------------


@router.get("/sessions", response_model=list[ChatSessionSummary], summary="List chat sessions")
def list_sessions(user_id: str = Depends(require_user)) -> list[ChatSessionSummary]:
    """List all chat sessions for the current user, ordered by last_active_at desc."""
    with Session(_engine_mod.engine) as session:
        stmt = (
            select(
                ChatSessionRecord,
                func.count(ChatHistoryRecord.id).label("message_count"),
            )
            .outerjoin(ChatHistoryRecord, ChatHistoryRecord.session_id == ChatSessionRecord.id)
            .where(user_filter_clause(ChatSessionRecord.user_id, user_id))
            .group_by(ChatSessionRecord.id)
            .order_by(ChatSessionRecord.last_active_at.desc())
        )
        rows = session.exec(stmt).all()
    return [
        ChatSessionSummary(
            id=row[0].id,
            title=row[0].title,
            origin=row[0].origin,
            created_at=row[0].created_at,
            last_active_at=row[0].last_active_at,
            message_count=row[1],
        )
        for row in rows
    ]


@router.post("/sessions", response_model=ChatSessionSummary, status_code=status.HTTP_201_CREATED, summary="Create a chat session")
def create_session(body: CreateSessionRequest, user_id: str = Depends(require_user)) -> ChatSessionSummary:
    """Create a new named chat session."""
    session_id = body.session_id or str(uuid.uuid4())
    with Session(_engine_mod.engine) as session:
        existing = session.exec(
            select(ChatSessionRecord).where(ChatSessionRecord.id == session_id)
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Session '{session_id}' already exists")
        record = ChatSessionRecord(id=session_id, user_id=user_id, title=body.title, origin=body.origin)
        session.add(record)
        session.commit()
        session.refresh(record)
    return ChatSessionSummary(
        id=record.id,
        title=record.title,
        origin=record.origin,
        created_at=record.created_at,
        last_active_at=record.last_active_at,
        message_count=0,
    )


@router.patch("/sessions/{session_id}", response_model=ChatSessionSummary, summary="Rename a chat session")
def rename_session(session_id: str, body: PatchSessionRequest, user_id: str = Depends(require_user)) -> ChatSessionSummary:
    """Rename an existing chat session."""
    with Session(_engine_mod.engine) as session:
        record = session.exec(
            select(ChatSessionRecord).where(
                ChatSessionRecord.id == session_id,
                user_filter_clause(ChatSessionRecord.user_id, user_id),
            )
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        record.title = body.title
        session.add(record)
        session.commit()
        session.refresh(record)
        msg_count = session.execute(
            text("SELECT COUNT(*) FROM chat_history WHERE session_id = :sid"),
            {"sid": session_id},
        ).scalar() or 0
    return ChatSessionSummary(
        id=record.id,
        title=record.title,
        origin=record.origin,
        created_at=record.created_at,
        last_active_at=record.last_active_at,
        message_count=msg_count,
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a chat session")
def delete_session(session_id: str, user_id: str = Depends(require_user)) -> None:
    """Delete a chat session and all its history."""
    with Session(_engine_mod.engine) as session:
        record = session.exec(
            select(ChatSessionRecord).where(
                ChatSessionRecord.id == session_id,
                user_filter_clause(ChatSessionRecord.user_id, user_id),
            )
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        # Delete chat history for this session
        history_records = session.exec(
            select(ChatHistoryRecord).where(ChatHistoryRecord.session_id == session_id)
        ).all()
        for rec in history_records:
            session.delete(rec)
        session.delete(record)
        session.commit()


@router.post("/migrate-session", status_code=status.HTTP_200_OK, summary="Migrate chat history to a new session ID")
def migrate_session(body: MigrateSessionRequest, user_id: str = Depends(require_user)) -> dict:
    """Migrate all chat history and usage records from old_session_id to new_session_id for the current user."""
    if body.old_session_id == body.new_session_id:
        return {"migrated": 0}
    with Session(_engine_mod.engine) as session:
        # Migrate chat history
        chat_records = session.exec(
            select(ChatHistoryRecord).where(
                ChatHistoryRecord.session_id == body.old_session_id,
                user_filter_clause(ChatHistoryRecord.user_id, user_id),
            )
        ).all()
        for rec in chat_records:
            rec.session_id = body.new_session_id
            session.add(rec)

        # Migrate usage log
        usage_records = session.exec(
            select(UsageLogRecord).where(
                UsageLogRecord.session_id == body.old_session_id,
                user_filter_clause(UsageLogRecord.user_id, user_id),
            )
        ).all()
        for rec in usage_records:
            rec.session_id = body.new_session_id
            session.add(rec)

        session.commit()
    return {"migrated": len(chat_records) + len(usage_records)}


# ---------------------------------------------------------------------------
# History enrichment
# ---------------------------------------------------------------------------


def _extract_thing_context(raw_applied_changes: Any) -> dict[str, Any]:
    """Extract structured Thing context from applied_changes JSON.

    Returns a dict with 'context_things' and/or 'referenced_things' lists
    so the reasoning agent has structured access to which Things were involved.
    Returns an empty dict if there is nothing to report.
    """
    if not raw_applied_changes:
        return {}

    changes = json.loads(raw_applied_changes) if isinstance(raw_applied_changes, str) else raw_applied_changes
    if not isinstance(changes, dict):
        return {}

    result: dict[str, Any] = {}
    context_things = changes.get("context_things", [])
    if context_things:
        result["context_things"] = context_things
    referenced_things = changes.get("referenced_things", [])
    if referenced_things:
        result["referenced_things"] = referenced_things
    return result


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


def _maybe_auto_title_session(session_id: str, user_message: str) -> None:
    """Generate a short auto-title for a new session after the first exchange."""

    async def _run() -> None:
        try:
            with Session(_engine_mod.engine) as sess:
                record = sess.exec(
                    select(ChatSessionRecord).where(ChatSessionRecord.id == session_id)
                ).first()
                if not record or record.title != "New chat":
                    return
                msg_count = sess.execute(
                    text("SELECT COUNT(*) FROM chat_history WHERE session_id = :sid"),
                    {"sid": session_id},
                ).scalar() or 0
                if msg_count > 2:
                    return

            import anthropic

            client = anthropic.Anthropic()
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=20,
                messages=[
                    {
                        "role": "user",
                        "content": f"Generate a 4-6 word title for a conversation that starts with: {user_message}. Reply with only the title, no quotes.",
                    }
                ],
            )
            title = resp.content[0].text.strip().strip('"\'')

            with Session(_engine_mod.engine) as sess:
                record = sess.exec(
                    select(ChatSessionRecord).where(ChatSessionRecord.id == session_id)
                ).first()
                if record and record.title == "New chat":
                    record.title = title
                    sess.add(record)
                    sess.commit()
        except Exception:
            logger.exception("Auto-title generation failed for session %s", session_id)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        pass


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
        with Session(_engine_mod.engine) as _sum_sess:
            _sum_record = _sum_sess.exec(
                select(ConversationSummaryRecord)
                .where(ConversationSummaryRecord.user_id == user_id)
                .order_by(ConversationSummaryRecord.messages_summarized_up_to.desc())  # type: ignore[union-attr]
            ).first()
        latest_summary: dict[str, Any] | None = (
            {
                "id": _sum_record.id,
                "summary_text": _sum_record.summary_text,
                "messages_summarized_up_to": _sum_record.messages_summarized_up_to,
                "token_count": _sum_record.token_count,
                "created_at": _sum_record.created_at,
            }
            if _sum_record
            else None
        )
        if latest_summary:
            with Session(_engine_mod.engine) as session:
                records = session.exec(
                    select(ChatHistoryRecord)
                    .where(
                        ChatHistoryRecord.session_id == session_id,
                        ChatHistoryRecord.id > latest_summary["messages_summarized_up_to"],
                    )
                    .order_by(ChatHistoryRecord.timestamp)
                    .limit(history_limit)
                ).all()
            messages = []
            for r in records:
                entry: dict[str, Any] = {"role": r.role, "content": r.content or ""}
                if r.role == "assistant":
                    ctx = _extract_thing_context(r.applied_changes)
                    entry.update(ctx)
                messages.append(entry)
            # Prepend summary as context
            return [
                {"role": "system", "content": f"[Conversation summary]\n{latest_summary['summary_text']}"},
                *messages,
            ]

    # Fallback: raw history (no summary available or no user_id)
    with Session(_engine_mod.engine) as session:
        records = session.exec(
            select(ChatHistoryRecord)
            .where(ChatHistoryRecord.session_id == session_id)
            .order_by(ChatHistoryRecord.timestamp)
            .limit(history_limit)
        ).all()
    result = []
    for r in records:
        entry = {"role": r.role, "content": r.content or ""}
        if r.role == "assistant":
            ctx = _extract_thing_context(r.applied_changes)
            entry.update(ctx)
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
    if result.referenced_things:
        applied_with_sources["referenced_things"] = result.referenced_things
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

    now = datetime.now(timezone.utc)

    with Session(_engine_mod.engine) as session:
        # Upsert ChatSessionRecord.last_active_at
        existing_session = session.exec(
            select(ChatSessionRecord).where(ChatSessionRecord.id == session_id)
        ).first()
        if existing_session:
            existing_session.last_active_at = now
            session.add(existing_session)
        else:
            new_session_record = ChatSessionRecord(
                id=session_id, user_id=user_id or "", title="New chat", last_active_at=now
            )
            session.add(new_session_record)

        # Insert user message
        user_record = ChatHistoryRecord(
            session_id=session_id,
            role="user",
            content=message,
            applied_changes=None,
            user_id=user_id or None,
        )
        session.add(user_record)

        # Insert assistant message
        assistant_record = ChatHistoryRecord(
            session_id=session_id,
            role="assistant",
            content=reply,
            applied_changes=applied_with_sources,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost_usd=usage.cost_usd,
            api_calls=usage.api_calls,
            model=usage.model,
            user_id=user_id or None,
        )
        session.add(assistant_record)
        session.flush()  # Get the ID for the assistant message

        # Insert per-call usage into chat_message_usage for structured retrieval
        num_calls = len(usage.calls)
        stage_labels: list[str | None] = []
        if num_calls >= 1:
            for _ in range(max(0, num_calls - 1)):
                stage_labels.append("reasoning")
            stage_labels.append("response")
        while len(stage_labels) < num_calls:
            stage_labels.append(None)
        for i, call in enumerate(usage.calls):
            stage = stage_labels[i] if i < len(stage_labels) else None
            usage_record = ChatMessageUsageRecord(
                chat_message_id=assistant_record.id,
                stage=stage,
                model=call.model,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                cost_usd=call.cost_usd,
            )
            session.add(usage_record)

        # Insert per-call usage records into usage_log for daily aggregation
        for call in usage.calls:
            log_record = UsageLogRecord(
                session_id=session_id,
                model=call.model,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                cost_usd=call.cost_usd,
                user_id=user_id or None,
            )
            session.add(log_record)

        session.commit()
    return applied_with_sources


@router.post("", response_model=ChatResponse, summary="Send a message through the multi-agent pipeline")
async def chat(body: ChatRequest, user_id: str = Depends(require_user)) -> ChatResponse:
    """4-stage pipeline: Context -> Retrieve -> Reasoning -> Validate -> Respond."""
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
    _maybe_auto_title_session(session_id, message)

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
            _maybe_auto_title_session(session_id, message)

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
    uf_frag, uf_p = user_filter_text(user_id)
    with Session(_engine_mod.engine) as session:
        totals_row = session.execute(
            text(
                "SELECT COALESCE(SUM(prompt_tokens), 0) as pt, COALESCE(SUM(completion_tokens), 0) as ct, "
                "COUNT(*) as calls, COALESCE(SUM(cost_usd), 0) as cost "
                f"FROM usage_log WHERE timestamp >= :today_start{uf_frag}"
            ),
            {"today_start": today_start, **uf_p},
        ).fetchone()

        model_rows = session.execute(
            text(
                "SELECT model, COALESCE(SUM(prompt_tokens), 0) as pt, COALESCE(SUM(completion_tokens), 0) as ct, "
                "COUNT(*) as calls, COALESCE(SUM(cost_usd), 0) as cost "
                f"FROM usage_log WHERE timestamp >= :today_start{uf_frag} "
                "GROUP BY model ORDER BY cost DESC"
            ),
            {"today_start": today_start, **uf_p},
        ).fetchall()

    per_model = [
        ModelUsage(
            model=r.model,
            prompt_tokens=r.pt,
            completion_tokens=r.ct,
            total_tokens=r.pt + r.ct,
            api_calls=r.calls,
            cost_usd=round(r.cost, 6),
        )
        for r in model_rows
    ]

    return SessionUsage(
        prompt_tokens=totals_row.pt,
        completion_tokens=totals_row.ct,
        total_tokens=totals_row.pt + totals_row.ct,
        api_calls=totals_row.calls,
        cost_usd=round(totals_row.cost, 6),
        per_model=per_model,
    )


@router.get("/stats/today", response_model=SessionUsage, summary="Get today's usage stats")
def get_daily_stats(user_id: str = Depends(require_user)) -> SessionUsage:
    """Return aggregated usage stats for today (since midnight local time)."""
    return _compute_daily_usage(user_id)
