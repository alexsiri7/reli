"""Chat history endpoints and the multi-agent chat pipeline."""

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status

from ..agents import (
    apply_storage_changes,
    run_context_agent,
    run_reasoning_agent,
    run_response_agent,
)
from ..database import db
from ..models import ChatMessage, ChatMessageCreate, ChatRequest, ChatResponse
from ..vector_store import VECTOR_SEARCH_THRESHOLD, vector_count, vector_search
from ..web_search import google_search, is_search_configured

router = APIRouter(prefix="/chat", tags=["chat"])


def _parse_dt(val: str | None) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    return datetime.fromisoformat(val)


def _row_to_msg(row) -> ChatMessage:
    changes = row["applied_changes"]
    if isinstance(changes, str):
        changes = json.loads(changes) if changes else None
    return ChatMessage(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        applied_changes=changes,
        timestamp=_parse_dt(row["timestamp"]),
    )


@router.get("/history/{session_id}", response_model=list[ChatMessage], summary="Get chat history for a session")
def get_history(
    session_id: str,
    limit: int = Query(50, ge=1, le=500),
    before: int | None = Query(None, description="Return messages with id < before (for loading older messages)"),
):
    with db() as conn:
        if before is not None:
            rows = conn.execute(
                "SELECT * FROM chat_history WHERE session_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
                (session_id, before, limit),
            ).fetchall()
            rows = list(reversed(rows))
        else:
            rows = conn.execute(
                "SELECT * FROM chat_history WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            rows = list(reversed(rows))
    return [_row_to_msg(r) for r in rows]


@router.post("/history", response_model=ChatMessage, status_code=status.HTTP_201_CREATED, summary="Append a chat message")
def append_message(body: ChatMessageCreate):
    changes_json = json.dumps(body.applied_changes) if body.applied_changes is not None else None
    with db() as conn:
        cursor = conn.execute(
            "INSERT INTO chat_history (session_id, role, content, applied_changes) VALUES (?, ?, ?, ?)",
            (body.session_id, body.role, body.content, changes_json),
        )
        row = conn.execute("SELECT * FROM chat_history WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _row_to_msg(row)


@router.delete("/history/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a session's chat history")
def delete_history(session_id: str):
    with db() as conn:
        result = conn.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"No chat history found for session '{session_id}'")


# ---------------------------------------------------------------------------
# Multi-agent pipeline endpoint
# ---------------------------------------------------------------------------

def _sql_things_count(conn) -> int:
    """Return total number of Things in SQLite."""
    row = conn.execute("SELECT COUNT(*) as cnt FROM things").fetchone()
    return row["cnt"] if row else 0


def _fetch_with_family(conn, seed_ids: list[str]) -> list[dict]:
    """Given seed Thing IDs, return those Things plus their parents and children."""
    seen_ids: set[str] = set()
    results: list[dict] = []

    def _add_row(row) -> None:
        if row["id"] not in seen_ids:
            seen_ids.add(row["id"])
            results.append(dict(row))

    # Fetch seed Things
    for thing_id in seed_ids:
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
        if row:
            _add_row(row)
            # Fetch parent
            if row["parent_id"]:
                parent = conn.execute("SELECT * FROM things WHERE id = ?", (row["parent_id"],)).fetchone()
                if parent:
                    _add_row(parent)
            # Fetch children
            children = conn.execute(
                "SELECT * FROM things WHERE parent_id = ?", (thing_id,)
            ).fetchall()
            for child in children:
                _add_row(child)

    return results


def _fetch_relevant_things(conn, search_queries: list[str], filter_params: dict) -> list[dict]:
    """Retrieve relevant Things using vector search (≥500 Things) or SQL LIKE fallback (<500).

    Always augments results with parent and children of every matched Thing.
    """
    active_only = filter_params.get("active_only", True)
    type_hint = filter_params.get("type_hint")

    # Choose retrieval strategy based on indexed count
    use_vector = vector_count() >= VECTOR_SEARCH_THRESHOLD

    seed_ids: list[str] = []

    if use_vector:
        # --- Vector search path ---
        seed_ids = vector_search(
            queries=search_queries,
            n_results=20,
            active_only=active_only,
            type_hint=type_hint,
        )
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
            if active_only:
                sql += " AND active = 1"
            if type_hint:
                sql += " AND type_hint = ?"
                params.append(type_hint)
            sql += " ORDER BY updated_at DESC LIMIT 20"
            for row in conn.execute(sql, params).fetchall():
                if row["id"] not in seen_sql:
                    seen_sql.add(row["id"])
                    seed_ids.append(row["id"])

    # Hydrate seed IDs with parent/children expansion
    results = _fetch_with_family(conn, seed_ids)

    # Always include recent active things when there aren't enough results
    if len(results) < 5:
        seen_ids = {r["id"] for r in results}
        sql = "SELECT * FROM things WHERE active = 1 ORDER BY updated_at DESC LIMIT 10"
        for row in conn.execute(sql).fetchall():
            if row["id"] not in seen_ids:
                seen_ids.add(row["id"])
                results.append(dict(row))

    return results


def _fetch_gmail_context(query: str) -> list[dict]:
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
            messages.append({
                "id": parsed.id,
                "subject": parsed.subject,
                "from": parsed.sender,
                "date": parsed.date,
                "snippet": parsed.snippet,
            })
        return messages
    except Exception:
        return []


@router.post("", response_model=ChatResponse, summary="Send a message through the multi-agent pipeline")
async def chat(body: ChatRequest):
    """4-stage pipeline: Context → Retrieve → Reasoning → Validate → Respond."""
    session_id = body.session_id
    message = body.message

    # Fetch conversation history
    with db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM chat_history WHERE session_id = ? ORDER BY timestamp ASC LIMIT 20",
            (session_id,),
        ).fetchall()
    history = [{"role": r["role"], "content": r["content"]} for r in rows]

    # Stage 1: Context Agent
    context_result = await run_context_agent(message, history)
    search_queries = context_result.get("search_queries", [message])
    filter_params = context_result.get("filter_params", {})
    gmail_query = context_result.get("gmail_query")

    # Retrieve relevant Things
    with db() as conn:
        relevant_things = _fetch_relevant_things(conn, search_queries, filter_params)

    # Web search (if Context Agent requested it and API is configured)
    web_results: list[dict] | None = None
    if context_result.get("needs_web_search") and is_search_configured():
        web_query = context_result.get("web_search_query") or message
        results = await google_search(web_query)
        if results:
            web_results = [r.to_dict() for r in results]

    # Optionally fetch Gmail context
    gmail_context = _fetch_gmail_context(gmail_query) if gmail_query else []

    # Stage 2: Reasoning Agent
    reasoning_result = await run_reasoning_agent(message, history, relevant_things, web_results, gmail_context)
    storage_changes = reasoning_result.get("storage_changes", {})
    questions_for_user = reasoning_result.get("questions_for_user", [])
    reasoning_summary = reasoning_result.get("reasoning_summary", "")

    # Stage 3: Validator — apply changes
    with db() as conn:
        applied_changes = apply_storage_changes(storage_changes, conn)

    # Stage 4: Response Agent
    reply = await run_response_agent(
        message, reasoning_summary, questions_for_user, applied_changes, web_results
    )

    # Persist both sides of the exchange to chat history
    applied_with_sources = applied_changes.copy()
    if web_results:
        applied_with_sources["web_results"] = web_results
    changes_json = json.dumps(applied_with_sources)
    with db() as conn:
        conn.execute(
            "INSERT INTO chat_history (session_id, role, content, applied_changes) VALUES (?, ?, ?, ?)",
            (session_id, "user", message, None),
        )
        conn.execute(
            "INSERT INTO chat_history (session_id, role, content, applied_changes) VALUES (?, ?, ?, ?)",
            (session_id, "assistant", reply, changes_json),
        )

    return ChatResponse(
        session_id=session_id,
        reply=reply,
        applied_changes=applied_with_sources,
        questions_for_user=questions_for_user,
    )
