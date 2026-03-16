"""Chat history endpoints and the multi-agent chat pipeline."""

import json
import logging
import sqlite3
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

logger = logging.getLogger(__name__)

from ..agents import (
    UsageStats,
    apply_storage_changes,
    run_context_agent,
    run_reasoning_agent,
    run_response_agent,
)
from ..auth import require_user, user_filter
from ..database import db
from .settings import get_chat_context_window
from ..google_calendar import fetch_upcoming_events
from ..google_calendar import is_connected as gcal_connected
from ..models import (
    CallUsage,
    ChatMessage,
    ChatMessageCreate,
    ChatRequest,
    ChatResponse,
    MigrateSessionRequest,
    ModelUsage,
    SessionUsage,
    UsageInfo,
)
from ..vector_store import VECTOR_SEARCH_THRESHOLD, vector_count, vector_search
from ..web_search import google_search, is_search_configured

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
            CallUsage(model=u["model"], prompt_tokens=u["prompt_tokens"], completion_tokens=u["completion_tokens"], cost_usd=u["cost_usd"])
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
            rows = list(reversed(rows))
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
# Multi-agent pipeline endpoint
# ---------------------------------------------------------------------------


def _sql_things_count(conn: sqlite3.Connection) -> int:
    """Return total number of Things in SQLite."""
    row = conn.execute("SELECT COUNT(*) as cnt FROM things").fetchone()
    return row["cnt"] if row else 0


def _fetch_with_family(conn: sqlite3.Connection, seed_ids: list[str]) -> list[dict[str, Any]]:
    """Given seed Thing IDs, return those Things plus their parents, children, and related Things via relationships."""
    seen_ids: set[str] = set()
    results: list[dict] = []

    def _add_row(row: sqlite3.Row) -> None:
        if row["id"] not in seen_ids:
            seen_ids.add(row["id"])
            results.append(dict(row))

    # Fetch seed Things
    for thing_id in seed_ids:
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
        if row:
            _add_row(row)
            # Fetch parent (shortcut via parent_id)
            if row["parent_id"]:
                parent = conn.execute("SELECT * FROM things WHERE id = ?", (row["parent_id"],)).fetchone()
                if parent:
                    _add_row(parent)
            # Fetch children (shortcut via parent_id)
            children = conn.execute("SELECT * FROM things WHERE parent_id = ?", (thing_id,)).fetchall()
            for child in children:
                _add_row(child)
            # Fetch related Things via thing_relationships
            rels = conn.execute(
                "SELECT * FROM thing_relationships WHERE from_thing_id = ? OR to_thing_id = ?",
                (thing_id, thing_id),
            ).fetchall()
            for rel in rels:
                other_id = rel["to_thing_id"] if rel["from_thing_id"] == thing_id else rel["from_thing_id"]
                if other_id not in seen_ids:
                    other = conn.execute("SELECT * FROM things WHERE id = ?", (other_id,)).fetchone()
                    if other:
                        _add_row(other)

    return results


def _fetch_relevant_things(
    conn: sqlite3.Connection, search_queries: list[str], filter_params: dict[str, Any],
    user_id: str = "",
) -> list[dict[str, Any]]:
    """Retrieve relevant Things using vector search (≥500 Things) or SQL LIKE fallback (<500).

    Always augments results with parent and children of every matched Thing.
    """
    active_only = filter_params.get("active_only", True)
    type_hint = filter_params.get("type_hint")
    uf_sql, uf_params = user_filter(user_id)

    # Choose retrieval strategy based on indexed count
    vc = vector_count()
    use_vector = vc >= VECTOR_SEARCH_THRESHOLD
    sql_thing_count = _sql_things_count(conn)

    logger.info(
        "Retrieval strategy: vector_count=%d, sql_things=%d, threshold=%d, use_vector=%s, active_only=%s, type_hint=%r",
        vc,
        sql_thing_count,
        VECTOR_SEARCH_THRESHOLD,
        use_vector,
        active_only,
        type_hint,
    )

    seed_ids: list[str] = []

    if use_vector:
        # --- Vector search path ---
        seed_ids = vector_search(
            queries=search_queries,
            n_results=20,
            active_only=active_only,
            type_hint=type_hint,
        )
        logger.info("Vector search returned %d seed IDs", len(seed_ids))
        # If vector search returns nothing (embedding failure), fall through to SQL
        if not seed_ids:
            use_vector = False

    if not use_vector:
        # --- SQL LIKE fallback ---
        seen_sql: set[str] = set()
        for query in search_queries[:3]:
            pattern = f"%{query}%"
            sql = "SELECT id FROM things WHERE (title LIKE ? OR data LIKE ?)"
            params: list = [pattern, pattern]
            sql += uf_sql
            params.extend(uf_params)
            if active_only:
                sql += " AND active = 1"
            if type_hint:
                sql += " AND type_hint = ?"
                params.append(type_hint)
            sql += " ORDER BY updated_at DESC LIMIT 20"
            matches = conn.execute(sql, params).fetchall()
            logger.info("SQL LIKE query=%r matched %d rows", query, len(matches))
            for row in matches:
                if row["id"] not in seen_sql:
                    seen_sql.add(row["id"])
                    seed_ids.append(row["id"])

    logger.info("Total seed IDs before hydration: %d", len(seed_ids))

    # Hydrate seed IDs with parent/children expansion
    results = _fetch_with_family(conn, seed_ids)
    logger.info("After family expansion: %d Things", len(results))

    # Always include recent active things when there aren't enough results
    if len(results) < 5:
        seen_ids = {r["id"] for r in results}
        recent_sql = "SELECT * FROM things WHERE active = 1" + uf_sql + " ORDER BY updated_at DESC LIMIT 10"
        for row in conn.execute(recent_sql, uf_params).fetchall():
            if row["id"] not in seen_ids:
                seen_ids.add(row["id"])
                results.append(dict(row))

    return results


def _fetch_gmail_context(query: str) -> list[dict[str, Any]]:
    """Fetch Gmail messages matching query for injection into the reasoning agent."""
    try:
        from .gmail import _get_service, _parse_message

        service = _get_service()
        result = service.users().messages().list(userId="me", q=query, maxResults=10).execute()
        msg_refs = result.get("messages", [])
        messages = []
        for ref in msg_refs[:10]:
            msg = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
            parsed = _parse_message(msg)
            messages.append(
                {
                    "id": parsed.id,
                    "subject": parsed.subject,
                    "from": parsed.sender,
                    "date": parsed.date,
                    "snippet": parsed.snippet,
                }
            )
        return messages
    except Exception:
        return []


def _enrich_history_content(row: sqlite3.Row) -> str:
    """Append Thing metadata summary to assistant messages that have applied_changes.

    This gives the context/reasoning agents visibility into which Things were
    involved in prior turns, improving pronoun/reference resolution.
    """
    content: str = row["content"] or ""
    if row["role"] != "assistant":
        return content

    raw = row["applied_changes"]
    if not raw:
        return content

    changes = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(changes, dict):
        return content

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

    if parts:
        return content + "\n" + "\n".join(parts)
    return content


@router.post("", response_model=ChatResponse, summary="Send a message through the multi-agent pipeline")
async def chat(body: ChatRequest, user_id: str = Depends(require_user)) -> ChatResponse:
    """4-stage pipeline: Context → Retrieve → Reasoning → Validate → Respond."""
    session_id = body.session_id
    message = body.message

    # Read configured context window size
    context_window = get_chat_context_window()

    # Fetch conversation history (2x window as buffer, agents slice to window size)
    history_limit = context_window * 2
    with db() as conn:
        rows = conn.execute(
            "SELECT role, content, applied_changes FROM chat_history WHERE session_id = ? ORDER BY timestamp ASC LIMIT ?",
            (session_id, history_limit),
        ).fetchall()
    history = [{"role": r["role"], "content": _enrich_history_content(r)} for r in rows]

    # Track usage across all pipeline stages
    usage = UsageStats()

    # Stage 1: Context Agent
    context_result = await run_context_agent(message, history, usage_stats=usage, context_window=context_window)
    search_queries = context_result.get("search_queries", [message])
    filter_params = context_result.get("filter_params", {})
    gmail_query = context_result.get("gmail_query")

    logger.info(
        "Context agent result — search_queries=%r, filter_params=%r, gmail_query=%r, "
        "needs_web_search=%r, include_calendar=%r",
        search_queries,
        filter_params,
        gmail_query,
        context_result.get("needs_web_search"),
        context_result.get("include_calendar"),
    )

    # Retrieve relevant Things and update last_referenced
    with db() as conn:
        relevant_things = _fetch_relevant_things(conn, search_queries, filter_params, user_id=user_id)
        logger.info(
            "Retrieved %d relevant Things for queries %r (vector_count=%d, threshold=%d)",
            len(relevant_things),
            search_queries,
            vector_count(),
            VECTOR_SEARCH_THRESHOLD,
        )
        if relevant_things:
            from datetime import timezone

            now = datetime.now(timezone.utc).isoformat()
            ids = [t["id"] for t in relevant_things]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE things SET last_referenced = ? WHERE id IN ({placeholders})",
                [now] + ids,
            )

    # Web search (if Context Agent requested it and API is configured)
    web_results: list[dict] | None = None
    if context_result.get("needs_web_search") and is_search_configured():
        web_query = context_result.get("web_search_query") or message
        results = await google_search(web_query)
        if results:
            web_results = [r.to_dict() for r in results]

    # Optionally fetch Gmail context
    gmail_context = _fetch_gmail_context(gmail_query) if gmail_query else []

    # Fetch calendar events if requested by Context Agent and connected
    calendar_events: list[dict] | None = None
    if context_result.get("include_calendar") and gcal_connected():
        try:
            calendar_events = fetch_upcoming_events(max_results=15, days_ahead=7)
        except Exception:
            calendar_events = None

    # Stage 2: Reasoning Agent
    reasoning_result = await run_reasoning_agent(
        message,
        history,
        relevant_things,
        web_results,
        gmail_context,
        calendar_events,
        usage_stats=usage,
        context_window=context_window,
    )
    storage_changes = reasoning_result.get("storage_changes", {})
    questions_for_user = reasoning_result.get("questions_for_user", [])
    reasoning_summary = reasoning_result.get("reasoning_summary", "")

    # Stage 3: Validator — apply changes
    with db() as conn:
        applied_changes = apply_storage_changes(storage_changes, conn)

    # Collect open_questions from relevant Things and newly created/updated Things
    open_questions_by_thing: dict[str, list[str]] = {}
    for thing in relevant_things:
        oq = thing.get("open_questions")
        if oq:
            parsed = json.loads(oq) if isinstance(oq, str) else oq
            if parsed:
                open_questions_by_thing[thing.get("title", thing["id"])] = parsed
    for thing in applied_changes.get("created", []) + applied_changes.get("updated", []):
        oq = thing.get("open_questions")
        if oq:
            parsed = json.loads(oq) if isinstance(oq, str) else oq
            if parsed:
                open_questions_by_thing[thing.get("title", thing.get("id", ""))] = parsed

    # Stage 4: Response Agent
    reply = await run_response_agent(
        message,
        reasoning_summary,
        questions_for_user,
        applied_changes,
        web_results,
        usage_stats=usage,
        open_questions_by_thing=open_questions_by_thing or None,
    )

    # Build context_things list from the Things that informed this response
    context_things = [
        {"id": t["id"], "title": t.get("title", ""), "type_hint": t.get("type_hint")} for t in relevant_things
    ]

    # Persist both sides of the exchange to chat history
    applied_with_sources = applied_changes.copy()
    applied_with_sources["context_things"] = context_things
    if web_results:
        applied_with_sources["web_results"] = web_results
    # Store per-call usage breakdown so it's available when loading history
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
    if gmail_context:
        applied_with_sources["gmail_context"] = gmail_context
    if calendar_events:
        applied_with_sources["calendar_events"] = calendar_events
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
        stage_names = ["context", "reasoning", "response"]
        for i, call in enumerate(usage.calls):
            stage = stage_names[i] if i < len(stage_names) else None
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

    daily_usage = _compute_daily_usage(user_id)

    return ChatResponse(
        session_id=session_id,
        reply=reply,
        applied_changes=applied_with_sources,
        questions_for_user=questions_for_user,
        usage=UsageInfo(**usage.to_dict()),
        session_usage=daily_usage,
    )


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
