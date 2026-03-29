from sqlmodel import Session

"""Connection suggestions API — auto-connect related Things."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_user, user_filter
import backend.db_engine as _engine_mod
from ..db_engine import _exec
from ..models import ConnectionSuggestion, ConnectionSuggestionAccept, ConnectionSuggestionThing

router = APIRouter(prefix="/connections", tags=["connections"])


def _row_to_suggestion(row: Any, from_thing: dict, to_thing: dict) -> ConnectionSuggestion:
    return ConnectionSuggestion(
        id=row.id,
        from_thing=ConnectionSuggestionThing(
            id=from_thing["id"],
            title=from_thing["title"],
            type_hint=from_thing.get("type_hint"),
        ),
        to_thing=ConnectionSuggestionThing(
            id=to_thing["id"],
            title=to_thing["title"],
            type_hint=to_thing.get("type_hint"),
        ),
        suggested_relationship_type=row.suggested_relationship_type,
        reason=row.reason,
        confidence=row.confidence,
        status=row.status,
        created_at=row.created_at,
    )


@router.get(
    "/suggestions",
    response_model=list[ConnectionSuggestion],
    summary="List pending connection suggestions",
)
def list_suggestions(
    status: str = "pending",
    limit: int = 20,
    user_id: str = Depends(require_user),
) -> list[ConnectionSuggestion]:
    """List connection suggestions, optionally filtered by status."""
    uf_sql, uf_params = user_filter(user_id, "cs")

    with Session(_engine_mod.engine) as session:
        rows = _exec(session, 
            f"""SELECT cs.* FROM connection_suggestions cs
               WHERE cs.status = ?{uf_sql}
               ORDER BY cs.confidence DESC, cs.created_at DESC
               LIMIT ?""",
            [status, *uf_params, limit],
        ).fetchall()

        suggestions: list[ConnectionSuggestion] = []
        for row in rows:
            from_thing = _exec(session, 
                "SELECT id, title, type_hint FROM things WHERE id = ?",
                (row.from_thing_id,),
            ).fetchone()
            to_thing = _exec(session, 
                "SELECT id, title, type_hint FROM things WHERE id = ?",
                (row.to_thing_id,),
            ).fetchone()

            if not from_thing or not to_thing:
                # One of the Things was deleted, clean up
                _exec(session, "DELETE FROM connection_suggestions WHERE id = ?", (row.id,))
                continue

            suggestions.append(_row_to_suggestion(row, dict(from_thing), dict(to_thing)))

        session.commit()
    return suggestions


@router.post(
    "/suggestions/{suggestion_id}/accept",
    response_model=ConnectionSuggestion,
    summary="Accept a connection suggestion",
)
def accept_suggestion(
    suggestion_id: str,
    body: ConnectionSuggestionAccept | None = None,
    user_id: str = Depends(require_user),
) -> ConnectionSuggestion:
    """Accept a connection suggestion — creates the relationship between the Things."""
    uf_sql, uf_params = user_filter(user_id, "cs")

    with Session(_engine_mod.engine) as session:
        row = _exec(session, 
            f"SELECT cs.* FROM connection_suggestions cs WHERE cs.id = ?{uf_sql}",
            [suggestion_id, *uf_params],
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        if row.status != "pending" and row.status != "deferred":
            raise HTTPException(status_code=400, detail=f"Suggestion is already {row['status']}")

        from_thing = _exec(session, 
            "SELECT id, title, type_hint FROM things WHERE id = ?",
            (row.from_thing_id,),
        ).fetchone()
        to_thing = _exec(session, 
            "SELECT id, title, type_hint FROM things WHERE id = ?",
            (row.to_thing_id,),
        ).fetchone()
        if not from_thing or not to_thing:
            raise HTTPException(status_code=404, detail="One of the Things no longer exists")

        # Determine relationship type
        rel_type = body.relationship_type if body and body.relationship_type else row.suggested_relationship_type

        # Create the actual relationship
        rel_id = f"rel-{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow().isoformat()
        _exec(session, 
            """INSERT INTO thing_relationships
               (id, from_thing_id, to_thing_id, relationship_type, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                rel_id,
                row.from_thing_id,
                row.to_thing_id,
                rel_type,
                None,
                now,
            ),
        )

        # Mark suggestion as accepted
        _exec(session, 
            "UPDATE connection_suggestions SET status = 'accepted', resolved_at = ? WHERE id = ?",
            (now, suggestion_id),
        )

        row = _exec(session, 
            "SELECT * FROM connection_suggestions WHERE id = ?",
            (suggestion_id,),
        ).fetchone()

        session.commit()
    return _row_to_suggestion(row, dict(from_thing), dict(to_thing))


@router.post(
    "/suggestions/{suggestion_id}/dismiss",
    response_model=ConnectionSuggestion,
    summary="Dismiss a connection suggestion",
)
def dismiss_suggestion(
    suggestion_id: str,
    user_id: str = Depends(require_user),
) -> ConnectionSuggestion:
    """Dismiss a connection suggestion — it won't be shown again."""
    uf_sql, uf_params = user_filter(user_id, "cs")

    with Session(_engine_mod.engine) as session:
        row = _exec(session, 
            f"SELECT cs.* FROM connection_suggestions cs WHERE cs.id = ?{uf_sql}",
            [suggestion_id, *uf_params],
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        now = datetime.utcnow().isoformat()
        _exec(session, 
            "UPDATE connection_suggestions SET status = 'dismissed', resolved_at = ? WHERE id = ?",
            (now, suggestion_id),
        )

        row = _exec(session, 
            "SELECT * FROM connection_suggestions WHERE id = ?",
            (suggestion_id,),
        ).fetchone()

        from_thing = _exec(session, 
            "SELECT id, title, type_hint FROM things WHERE id = ?",
            (row.from_thing_id,),
        ).fetchone()
        to_thing = _exec(session, 
            "SELECT id, title, type_hint FROM things WHERE id = ?",
            (row.to_thing_id,),
        ).fetchone()

        session.commit()
    if not from_thing or not to_thing:
        raise HTTPException(status_code=404, detail="Thing not found")

    return _row_to_suggestion(row, dict(from_thing), dict(to_thing))


@router.post(
    "/suggestions/{suggestion_id}/defer",
    response_model=ConnectionSuggestion,
    summary="Defer a connection suggestion",
)
def defer_suggestion(
    suggestion_id: str,
    user_id: str = Depends(require_user),
) -> ConnectionSuggestion:
    """Defer a connection suggestion — it can be reviewed later."""
    uf_sql, uf_params = user_filter(user_id, "cs")

    with Session(_engine_mod.engine) as session:
        row = _exec(session, 
            f"SELECT cs.* FROM connection_suggestions cs WHERE cs.id = ?{uf_sql}",
            [suggestion_id, *uf_params],
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        _exec(session, 
            "UPDATE connection_suggestions SET status = 'deferred' WHERE id = ?",
            (suggestion_id,),
        )

        row = _exec(session, 
            "SELECT * FROM connection_suggestions WHERE id = ?",
            (suggestion_id,),
        ).fetchone()

        from_thing = _exec(session, 
            "SELECT id, title, type_hint FROM things WHERE id = ?",
            (row.from_thing_id,),
        ).fetchone()
        to_thing = _exec(session, 
            "SELECT id, title, type_hint FROM things WHERE id = ?",
            (row.to_thing_id,),
        ).fetchone()

        session.commit()
    if not from_thing or not to_thing:
        raise HTTPException(status_code=404, detail="Thing not found")

    return _row_to_suggestion(row, dict(from_thing), dict(to_thing))
