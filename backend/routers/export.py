"""Data export endpoints: things, chat history, and full ZIP bundle."""

import io
import json
import zipfile
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..auth import require_user, user_filter
from ..database import db

router = APIRouter(prefix="/export", tags=["export"])


def _export_things(user_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Export all things and relationships for the given user."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        rows = conn.execute(
            f"SELECT * FROM things WHERE 1=1{uf_sql} ORDER BY created_at",
            uf_params,
        ).fetchall()
        things = [dict(r) for r in rows]

        rels = conn.execute(
            f"""
            SELECT r.* FROM thing_relationships r
            JOIN things t ON r.from_thing_id = t.id
            WHERE 1=1{uf_sql}
            ORDER BY r.created_at
            """,
            uf_params,
        ).fetchall()
        relationships = [dict(r) for r in rels]

    return things, relationships


def _export_chat(user_id: str) -> list[dict[str, Any]]:
    """Export all chat history for the given user."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        rows = conn.execute(
            f"SELECT * FROM chat_history WHERE 1=1{uf_sql} ORDER BY timestamp",
            uf_params,
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/things", summary="Export things as JSON")
def export_things(user_id: str = Depends(require_user)) -> dict[str, Any]:
    """Export all things and relationships as JSON."""
    things, relationships = _export_things(user_id)
    return {"things": things, "relationships": relationships}


@router.get("/chat", summary="Export chat history as JSON")
def export_chat(user_id: str = Depends(require_user)) -> dict[str, Any]:
    """Export all chat history as JSON."""
    messages = _export_chat(user_id)
    return {"chat_history": messages}


@router.get("/all", summary="Export all data as ZIP")
def export_all(user_id: str = Depends(require_user)) -> StreamingResponse:
    """Export things, relationships, and chat history as a ZIP archive."""
    things, relationships = _export_things(user_id)
    chat = _export_chat(user_id)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "things.json",
            json.dumps({"things": things}, indent=2, default=str),
        )
        zf.writestr(
            "relationships.json",
            json.dumps({"relationships": relationships}, indent=2, default=str),
        )
        zf.writestr(
            "chat_history.json",
            json.dumps({"chat_history": chat}, indent=2, default=str),
        )
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=reli-export.zip"},
    )
