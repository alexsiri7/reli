"""Data export endpoints — Things, chat history, and full ZIP archive."""

import io
import json
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from ..auth import require_user, user_filter
from ..database import db

router = APIRouter(prefix="/export", tags=["export"])


def _parse_json_field(val: str | None) -> object:
    """Unwrap a possibly double-encoded JSON string into a Python object."""
    if val is None:
        return None
    while isinstance(val, str) and val:
        try:
            val = json.loads(val)
        except (json.JSONDecodeError, ValueError):
            break
    if isinstance(val, str):
        return None
    return val


def _export_things(user_id: str) -> list[dict]:
    """Fetch all things for the user with type info."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        rows = conn.execute(
            "SELECT t.*, tt.icon AS type_icon, tt.color AS type_color"
            " FROM things t"
            " LEFT JOIN thing_types tt ON t.type_hint = tt.name"
            f" WHERE 1=1{uf_sql}"
            " ORDER BY t.created_at ASC",
            uf_params,
        ).fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "type_hint": r["type_hint"],
            "type_icon": r["type_icon"],
            "type_color": r["type_color"],
            "parent_id": r["parent_id"],
            "checkin_date": r["checkin_date"],
            "priority": r["priority"],
            "active": bool(r["active"]),
            "surface": bool(r["surface"]) if r["surface"] is not None else True,
            "data": _parse_json_field(r["data"]),
            "open_questions": _parse_json_field(r["open_questions"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "last_referenced": r["last_referenced"],
        }
        for r in rows
    ]


def _export_relationships(user_id: str) -> list[dict]:
    """Fetch all relationships for things owned by the user."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        rows = conn.execute(
            "SELECT r.* FROM thing_relationships r"
            " JOIN things t ON r.from_thing_id = t.id"
            f" WHERE 1=1{uf_sql}"
            " ORDER BY r.created_at ASC",
            uf_params,
        ).fetchall()
    return [
        {
            "id": r["id"],
            "from_thing_id": r["from_thing_id"],
            "to_thing_id": r["to_thing_id"],
            "relationship_type": r["relationship_type"],
            "metadata": _parse_json_field(r["metadata"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def _export_chat(user_id: str) -> list[dict]:
    """Fetch full chat history for the user."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        rows = conn.execute(
            f"SELECT * FROM chat_history WHERE 1=1{uf_sql} ORDER BY id ASC",
            uf_params,
        ).fetchall()
    return [
        {
            "id": r["id"],
            "session_id": r["session_id"],
            "role": r["role"],
            "content": r["content"],
            "applied_changes": _parse_json_field(r["applied_changes"]),
            "prompt_tokens": r["prompt_tokens"],
            "completion_tokens": r["completion_tokens"],
            "cost_usd": r["cost_usd"],
            "model": r["model"],
            "timestamp": r["timestamp"],
        }
        for r in rows
    ]


@router.get("/things", summary="Export all Things as JSON")
def export_things(user_id: str = Depends(require_user)) -> JSONResponse:
    """Export all Things with type info, metadata, and timestamps filtered by user_id."""
    things = _export_things(user_id)
    return JSONResponse(
        content={"exported_at": datetime.utcnow().isoformat() + "Z", "count": len(things), "things": things},
        headers={"Content-Disposition": 'attachment; filename="things.json"'},
    )


@router.get("/chat", summary="Export full chat history as JSON")
def export_chat(user_id: str = Depends(require_user)) -> JSONResponse:
    """Export complete conversation history filtered by user_id."""
    messages = _export_chat(user_id)
    return JSONResponse(
        content={
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "count": len(messages),
            "messages": messages,
        },
        headers={"Content-Disposition": 'attachment; filename="chat_history.json"'},
    )


@router.get("/all", summary="Export all user data as a ZIP archive")
def export_all(user_id: str = Depends(require_user)) -> StreamingResponse:
    """Export things.json, chat_history.json, and relationships.json bundled in a ZIP archive."""
    things = _export_things(user_id)
    relationships = _export_relationships(user_id)
    messages = _export_chat(user_id)

    exported_at = datetime.utcnow().isoformat() + "Z"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "things.json",
            json.dumps({"exported_at": exported_at, "count": len(things), "things": things}, indent=2),
        )
        zf.writestr(
            "relationships.json",
            json.dumps(
                {"exported_at": exported_at, "count": len(relationships), "relationships": relationships}, indent=2
            ),
        )
        zf.writestr(
            "chat_history.json",
            json.dumps({"exported_at": exported_at, "count": len(messages), "messages": messages}, indent=2),
        )
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="reli-export.zip"'},
    )
