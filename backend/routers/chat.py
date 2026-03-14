"""Chat history endpoints."""

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status

from ..database import db
from ..models import ChatMessage, ChatMessageCreate

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
    offset: int = Query(0, ge=0),
):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_history WHERE session_id = ? ORDER BY timestamp ASC LIMIT ? OFFSET ?",
            (session_id, limit, offset),
        ).fetchall()
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
