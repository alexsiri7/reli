"""Chat history endpoints and the multi-agent chat pipeline."""

import json
import logging
import sqlite3
from datetime import date, datetime
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

from ..agents import (
    UsageStats,
    apply_storage_changes,
    run_context_agent,
    run_context_refinement,
    run_reasoning_agent,
    run_response_agent,
    run_response_agent_stream,
)
from ..auth import require_user, user_filter
from ..database import db
from .settings import get_user_api_key, get_user_chat_context_window, get_user_models
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


def _fetch_user_relationships(
    conn: sqlite3.Connection,
    user_thing_id: str,
    search_queries: list[str],
    user_id: str = "",
) -> list[dict[str, Any]]:
    """Fetch 1-hop relationships from the user Thing, filtered by search query relevance.

    Only returns related Things whose title or data match at least one search
    query (case-insensitive LIKE).  Results are ordered by last_referenced DESC
    (recently-mentioned first) so the most relevant connections surface first.
    This prevents context bloat for power users with hundreds of relationships.
    """
    if not user_thing_id or not search_queries:
        return []

    # Fetch all relationship edges touching the user Thing
    rels = conn.execute(
        "SELECT * FROM thing_relationships WHERE from_thing_id = ? OR to_thing_id = ?",
        (user_thing_id, user_thing_id),
    ).fetchall()
    if not rels:
        return []

    # Collect the IDs of the "other" side of each relationship
    other_ids: list[str] = []
    for rel in rels:
        other_id = rel["to_thing_id"] if rel["from_thing_id"] == user_thing_id else rel["from_thing_id"]
        other_ids.append(other_id)

    if not other_ids:
        return []

    # Fetch the related Things that match any search query
    placeholders = ",".join("?" for _ in other_ids)
    uf_sql, uf_params = user_filter(user_id)

    # Build LIKE clauses for each query
    like_clauses: list[str] = []
    like_params: list[str] = []
    for query in search_queries[:3]:
        pattern = f"%{query}%"
        like_clauses.append("(title LIKE ? OR data LIKE ?)")
        like_params.extend([pattern, pattern])

    query_filter = " OR ".join(like_clauses)
    sql = (
        f"SELECT * FROM things WHERE id IN ({placeholders})"
        f"{uf_sql}"
        f" AND ({query_filter})"
        " ORDER BY"
        " CASE WHEN last_referenced IS NOT NULL THEN 0 ELSE 1 END,"
        " last_referenced DESC,"
        " updated_at DESC"
        " LIMIT 10"
    )
    params: list = [*other_ids, *uf_params, *like_params]
    rows = conn.execute(sql, params).fetchall()
    logger.info(
        "User relationship search: %d edges, %d query-matched (queries=%r)",
        len(other_ids),
        len(rows),
        search_queries[:3],
    )
    return [dict(r) for r in rows]


def _fetch_user_thing(conn: sqlite3.Connection, user_id: str) -> dict[str, Any] | None:
    """Fetch the user's own Thing (type_hint='person', matching user_id).

    Returns None if no user Thing exists (e.g. legacy accounts created before
    the auto-create feature).
    """
    if not user_id:
        return None
    row = conn.execute(
        "SELECT * FROM things WHERE user_id = ? AND type_hint = 'person' LIMIT 1",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def _fetch_relevant_things(
    conn: sqlite3.Connection,
    search_queries: list[str],
    filter_params: dict[str, Any],
    user_id: str = "",
) -> list[dict[str, Any]]:
    """Retrieve relevant Things using vector search (≥500 Things) or SQL LIKE fallback (<500).

    Always augments results with parent and children of every matched Thing.
    Always prepends the user's own Thing (type_hint='person') so every
    interaction is grounded in who the user is.
    """
    active_only = filter_params.get("active_only", True)
    type_hint = filter_params.get("type_hint")
    uf_sql, uf_params = user_filter(user_id)

    # Always inject the user's own Thing first (cheap single-row lookup)
    user_thing = _fetch_user_thing(conn, user_id)
    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    if user_thing:
        seen_ids.add(user_thing["id"])
        results.append(user_thing)

        # Load 1-hop relationships that match the search queries, ordered by
        # last_referenced recency.  This keeps relevant connections accessible
        # without preloading all relationships (which could be hundreds).
        user_rels = _fetch_user_relationships(
            conn, user_thing["id"], search_queries, user_id
        )
        for rel_thing in user_rels:
            if rel_thing["id"] not in seen_ids:
                seen_ids.add(rel_thing["id"])
                results.append(rel_thing)

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
            user_id=user_id,
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
    family_results = _fetch_with_family(conn, seed_ids)
    logger.info("After family expansion: %d Things", len(family_results))

    # Merge family results, skipping the user Thing if already present
    for thing in family_results:
        if thing["id"] not in seen_ids:
            seen_ids.add(thing["id"])
            results.append(thing)

    # Always include recent active things when there aren't enough results
    if len(results) < 5:
        recent_sql = "SELECT * FROM things WHERE active = 1" + uf_sql + " ORDER BY updated_at DESC LIMIT 10"
        for row in conn.execute(recent_sql, uf_params).fetchall():
            if row["id"] not in seen_ids:
                seen_ids.add(row["id"])
                results.append(dict(row))

    return results


def _fetch_gmail_context(query: str, user_id: str = "") -> list[dict[str, Any]]:
    """Fetch Gmail messages matching query for injection into the reasoning agent."""
    try:
        from .gmail import _get_service, _parse_message

        service = _get_service(user_id=user_id)
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

    # Read per-user settings (API key, models, context window)
    user_api_key = get_user_api_key(user_id)
    user_models = get_user_models(user_id)
    context_window = get_user_chat_context_window(user_id)

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

    # Stage 1: Context Agent (iterative loop)
    MAX_CONTEXT_ITERATIONS = 4

    context_result = await run_context_agent(
        message, history, usage_stats=usage, context_window=context_window,
        api_key=user_api_key, model=user_models["context"],
    )
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

    # Iterative context gathering: fetch Things, ask context agent if more needed
    all_queries: list[str] = list(search_queries)
    seen_thing_ids: set[str] = set()
    relevant_things: list[dict[str, Any]] = []

    # Initial fetch
    with db() as conn:
        initial_things = _fetch_relevant_things(conn, search_queries, filter_params, user_id=user_id)
        for t in initial_things:
            if t["id"] not in seen_thing_ids:
                seen_thing_ids.add(t["id"])
                relevant_things.append(t)

    logger.info(
        "Initial retrieval: %d Things for queries %r",
        len(relevant_things), search_queries,
    )

    # Refinement loop: ask context agent if it needs more
    for iteration in range(1, MAX_CONTEXT_ITERATIONS):
        if not relevant_things:
            break  # nothing to refine on

        # Fetch relationships for found Things to help refinement agent follow links
        thing_relationships: list[dict[str, Any]] = []
        with db() as conn:
            thing_id_list = list(seen_thing_ids)
            if thing_id_list:
                ph = ",".join("?" for _ in thing_id_list)
                rel_rows = conn.execute(
                    f"SELECT from_thing_id, to_thing_id, relationship_type FROM thing_relationships "
                    f"WHERE from_thing_id IN ({ph}) OR to_thing_id IN ({ph})",
                    thing_id_list + thing_id_list,
                ).fetchall()
                thing_relationships = [dict(r) for r in rel_rows]

        refinement = await run_context_refinement(
            message, history, relevant_things, all_queries,
            relationships=thing_relationships,
            usage_stats=usage, context_window=context_window,
            api_key=user_api_key, model=user_models["context"],
        )

        if refinement.get("done", True):
            logger.info("Context refinement done after %d iteration(s)", iteration)
            break

        new_queries = refinement.get("search_queries", [])
        thing_ids_to_fetch = refinement.get("thing_ids", [])
        refinement_filter = refinement.get("filter_params", filter_params)

        if not new_queries and not thing_ids_to_fetch:
            logger.info("Context refinement returned no new queries or IDs, stopping")
            break

        prev_count = len(relevant_things)

        # Fetch by new text queries
        if new_queries:
            all_queries.extend(new_queries)
            with db() as conn:
                new_things = _fetch_relevant_things(conn, new_queries, refinement_filter, user_id=user_id)
                for t in new_things:
                    if t["id"] not in seen_thing_ids:
                        seen_thing_ids.add(t["id"])
                        relevant_things.append(t)

        # Fetch by direct Thing IDs (for following relationships)
        if thing_ids_to_fetch:
            with db() as conn:
                new_from_ids = _fetch_with_family(conn, [
                    tid for tid in thing_ids_to_fetch if tid not in seen_thing_ids
                ])
                for t in new_from_ids:
                    if t["id"] not in seen_thing_ids:
                        seen_thing_ids.add(t["id"])
                        relevant_things.append(t)

        new_count = len(relevant_things) - prev_count
        logger.info(
            "Context refinement iteration %d: +%d new Things (total %d), queries=%r, ids=%r",
            iteration, new_count, len(relevant_things), new_queries, thing_ids_to_fetch,
        )

        # Dead end detection: no new Things found
        if new_count == 0:
            logger.info("Context refinement found nothing new, stopping")
            break

    # Update last_referenced on all retrieved Things
    if relevant_things:
        with db() as conn:
            from datetime import timezone

            now = datetime.now(timezone.utc).isoformat()
            ids = [t["id"] for t in relevant_things]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE things SET last_referenced = ? WHERE id IN ({placeholders})",
                [now] + ids,
            )

    logger.info(
        "Final context: %d Things after up to %d iterations",
        len(relevant_things), MAX_CONTEXT_ITERATIONS,
    )

    # Web search (if Context Agent requested it and API is configured)
    web_results: list[dict] | None = None
    if context_result.get("needs_web_search") and is_search_configured():
        web_query = context_result.get("web_search_query") or message
        results = await google_search(web_query)
        if results:
            web_results = [r.to_dict() for r in results]

    # Optionally fetch Gmail context
    gmail_context = _fetch_gmail_context(gmail_query, user_id=user_id) if gmail_query else []

    # Fetch calendar events if requested by Context Agent and connected
    calendar_events: list[dict] | None = None
    if context_result.get("include_calendar") and gcal_connected(user_id=user_id):
        try:
            calendar_events = fetch_upcoming_events(max_results=15, days_ahead=7, user_id=user_id)
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
        api_key=user_api_key,
        model=user_models["reasoning"],
    )
    storage_changes = reasoning_result.get("storage_changes", {})
    questions_for_user = reasoning_result.get("questions_for_user", [])
    reasoning_summary = reasoning_result.get("reasoning_summary", "")

    # Stage 3: Validator — apply changes
    with db() as conn:
        applied_changes = apply_storage_changes(storage_changes, conn, user_id=user_id)

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
        api_key=user_api_key,
        model=user_models["response"],
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
        # Calls: context, [refinement x N], reasoning, response
        num_calls = len(usage.calls)
        stage_labels: list[str | None] = []
        if num_calls >= 1:
            stage_labels.append("context")
        # Middle calls are refinement (between context and reasoning+response)
        for _ in range(max(0, num_calls - 3)):
            stage_labels.append("context_refinement")
        if num_calls >= 2:
            stage_labels.append("reasoning")
        if num_calls >= 3:
            stage_labels.append("response")
        # Pad with None if somehow there are extra calls
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

    daily_usage = _compute_daily_usage(user_id)

    return ChatResponse(
        session_id=session_id,
        reply=reply,
        applied_changes=applied_with_sources,
        questions_for_user=questions_for_user,
        usage=UsageInfo(**usage.to_dict()),
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

    async def event_generator() -> AsyncIterator[str]:  # noqa: C901
        try:
            session_id = body.session_id
            message = body.message

            user_api_key = get_user_api_key(user_id)
            user_models = get_user_models(user_id)
            context_window = get_user_chat_context_window(user_id)

            history_limit = context_window * 2
            with db() as conn:
                rows = conn.execute(
                    "SELECT role, content, applied_changes FROM chat_history WHERE session_id = ? ORDER BY timestamp ASC LIMIT ?",
                    (session_id, history_limit),
                ).fetchall()
            history = [{"role": r["role"], "content": _enrich_history_content(r)} for r in rows]

            usage = UsageStats()

            # Stage 1: Context Agent
            yield _sse("stage", {"stage": "context", "status": "started"})

            MAX_CONTEXT_ITERATIONS = 4
            context_result = await run_context_agent(
                message, history, usage_stats=usage, context_window=context_window,
                api_key=user_api_key, model=user_models["context"],
            )
            search_queries = context_result.get("search_queries", [message])
            filter_params = context_result.get("filter_params", {})
            gmail_query = context_result.get("gmail_query")

            # Iterative context gathering
            all_queries: list[str] = list(search_queries)
            seen_thing_ids: set[str] = set()
            relevant_things: list[dict[str, Any]] = []

            with db() as conn:
                initial_things = _fetch_relevant_things(conn, search_queries, filter_params, user_id=user_id)
                for t in initial_things:
                    if t["id"] not in seen_thing_ids:
                        seen_thing_ids.add(t["id"])
                        relevant_things.append(t)

            for iteration in range(1, MAX_CONTEXT_ITERATIONS):
                if not relevant_things:
                    break
                thing_relationships: list[dict[str, Any]] = []
                with db() as conn:
                    thing_id_list = list(seen_thing_ids)
                    if thing_id_list:
                        ph = ",".join("?" for _ in thing_id_list)
                        rel_rows = conn.execute(
                            f"SELECT from_thing_id, to_thing_id, relationship_type FROM thing_relationships "
                            f"WHERE from_thing_id IN ({ph}) OR to_thing_id IN ({ph})",
                            thing_id_list + thing_id_list,
                        ).fetchall()
                        thing_relationships = [dict(r) for r in rel_rows]

                refinement = await run_context_refinement(
                    message, history, relevant_things, all_queries,
                    relationships=thing_relationships,
                    usage_stats=usage, context_window=context_window,
                    api_key=user_api_key, model=user_models["context"],
                )
                if refinement.get("done", True):
                    break
                new_queries = refinement.get("search_queries", [])
                thing_ids_to_fetch = refinement.get("thing_ids", [])
                refinement_filter = refinement.get("filter_params", filter_params)
                if not new_queries and not thing_ids_to_fetch:
                    break
                prev_count = len(relevant_things)
                if new_queries:
                    all_queries.extend(new_queries)
                    with db() as conn:
                        new_things = _fetch_relevant_things(conn, new_queries, refinement_filter, user_id=user_id)
                        for t in new_things:
                            if t["id"] not in seen_thing_ids:
                                seen_thing_ids.add(t["id"])
                                relevant_things.append(t)
                if thing_ids_to_fetch:
                    with db() as conn:
                        new_from_ids = _fetch_with_family(conn, [
                            tid for tid in thing_ids_to_fetch if tid not in seen_thing_ids
                        ])
                        for t in new_from_ids:
                            if t["id"] not in seen_thing_ids:
                                seen_thing_ids.add(t["id"])
                                relevant_things.append(t)
                if len(relevant_things) - prev_count == 0:
                    break

            # Update last_referenced
            if relevant_things:
                with db() as conn:
                    from datetime import timezone
                    now = datetime.now(timezone.utc).isoformat()
                    ids = [t["id"] for t in relevant_things]
                    placeholders = ",".join("?" for _ in ids)
                    conn.execute(
                        f"UPDATE things SET last_referenced = ? WHERE id IN ({placeholders})",
                        [now] + ids,
                    )

            yield _sse("stage", {"stage": "context", "status": "complete"})

            # Web search
            web_results: list[dict] | None = None
            if context_result.get("needs_web_search") and is_search_configured():
                web_query = context_result.get("web_search_query") or message
                results = await google_search(web_query)
                if results:
                    web_results = [r.to_dict() for r in results]

            gmail_context = _fetch_gmail_context(gmail_query, user_id=user_id) if gmail_query else []

            calendar_events: list[dict] | None = None
            if context_result.get("include_calendar") and gcal_connected(user_id=user_id):
                try:
                    calendar_events = fetch_upcoming_events(max_results=15, days_ahead=7, user_id=user_id)
                except Exception:
                    calendar_events = None

            # Stage 2: Reasoning Agent
            yield _sse("stage", {"stage": "reasoning", "status": "started"})

            reasoning_result = await run_reasoning_agent(
                message, history, relevant_things, web_results, gmail_context, calendar_events,
                usage_stats=usage, context_window=context_window,
                api_key=user_api_key, model=user_models["reasoning"],
            )
            storage_changes = reasoning_result.get("storage_changes", {})
            questions_for_user = reasoning_result.get("questions_for_user", [])
            reasoning_summary = reasoning_result.get("reasoning_summary", "")

            # Stage 3: Validator
            with db() as conn:
                applied_changes = apply_storage_changes(storage_changes, conn, user_id=user_id)

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

            yield _sse("stage", {"stage": "reasoning", "status": "complete"})

            # Stage 4: Response Agent (streaming)
            yield _sse("stage", {"stage": "response", "status": "started"})

            reply_parts: list[str] = []
            async for token in run_response_agent_stream(
                message, reasoning_summary, questions_for_user, applied_changes,
                web_results, usage_stats=usage,
                open_questions_by_thing=open_questions_by_thing or None,
                api_key=user_api_key, model=user_models["response"],
            ):
                reply_parts.append(token)
                yield _sse("token", {"text": token})

            reply = "".join(reply_parts)

            yield _sse("stage", {"stage": "response", "status": "complete"})

            # Persist to DB (same as non-streaming endpoint)
            context_things = [
                {"id": t["id"], "title": t.get("title", ""), "type_hint": t.get("type_hint")}
                for t in relevant_things
            ]
            applied_with_sources = applied_changes.copy()
            applied_with_sources["context_things"] = context_things
            if web_results:
                applied_with_sources["web_results"] = web_results
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
                        session_id, "assistant", reply, changes_json,
                        usage.prompt_tokens, usage.completion_tokens,
                        usage.cost_usd, usage.api_calls, usage.model, user_id or None,
                    ),
                )
                assistant_msg_id = cursor.lastrowid

                num_calls = len(usage.calls)
                stage_labels: list[str | None] = []
                if num_calls >= 1:
                    stage_labels.append("context")
                for _ in range(max(0, num_calls - 3)):
                    stage_labels.append("context_refinement")
                if num_calls >= 2:
                    stage_labels.append("reasoning")
                if num_calls >= 3:
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

                for call in usage.calls:
                    conn.execute(
                        "INSERT INTO usage_log (session_id, model, prompt_tokens, completion_tokens, cost_usd, user_id)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (session_id, call.model, call.prompt_tokens, call.completion_tokens, call.cost_usd, user_id or None),
                    )

            daily_usage = _compute_daily_usage(user_id)

            complete_data = ChatResponse(
                session_id=session_id,
                reply=reply,
                applied_changes=applied_with_sources,
                questions_for_user=questions_for_user,
                usage=UsageInfo(**usage.to_dict()),
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
