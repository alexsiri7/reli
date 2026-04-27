"""Connection suggestions API — auto-connect related Things."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

import backend.db_engine as _engine_mod

from ..auth import require_user
from ..db_engine import user_filter_clause
from ..db_models import ConnectionSuggestionRecord, ThingRecord, ThingRelationshipRecord
from ..models import ConnectionSuggestion, ConnectionSuggestionAccept, ConnectionSuggestionThing

router = APIRouter(prefix="/connections", tags=["connections"])


def _record_to_suggestion(
    record: ConnectionSuggestionRecord,
    from_thing: ThingRecord,
    to_thing: ThingRecord,
) -> ConnectionSuggestion:
    return ConnectionSuggestion(
        id=record.id,
        from_thing=ConnectionSuggestionThing(
            id=from_thing.id,
            title=from_thing.title,
            type_hint=from_thing.type_hint,
        ),
        to_thing=ConnectionSuggestionThing(
            id=to_thing.id,
            title=to_thing.title,
            type_hint=to_thing.type_hint,
        ),
        suggested_relationship_type=record.suggested_relationship_type,
        reason=record.reason,
        confidence=record.confidence,
        status=record.status,
        created_at=record.created_at,
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
    with Session(_engine_mod.engine) as session:
        records = session.exec(
            select(ConnectionSuggestionRecord)
            .where(
                ConnectionSuggestionRecord.status == status,
                user_filter_clause(ConnectionSuggestionRecord.user_id, user_id),
            )
            .order_by(
                ConnectionSuggestionRecord.confidence.desc(),  # type: ignore[union-attr]
                ConnectionSuggestionRecord.created_at.desc(),  # type: ignore[union-attr]
            )
            .limit(limit)
        ).all()

        suggestions: list[ConnectionSuggestion] = []
        for rec in records:
            from_thing = session.get(ThingRecord, rec.from_thing_id)
            to_thing = session.get(ThingRecord, rec.to_thing_id)

            if not from_thing or not to_thing:
                # One of the Things was deleted, clean up
                session.delete(rec)
                continue

            suggestions.append(_record_to_suggestion(rec, from_thing, to_thing))

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
    with Session(_engine_mod.engine) as session:
        rec = session.exec(
            select(ConnectionSuggestionRecord).where(
                ConnectionSuggestionRecord.id == suggestion_id,
                user_filter_clause(ConnectionSuggestionRecord.user_id, user_id),
            )
        ).first()
        if not rec:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        if rec.status != "pending" and rec.status != "deferred":
            raise HTTPException(status_code=400, detail=f"Suggestion is already {rec.status}")

        from_thing = session.get(ThingRecord, rec.from_thing_id)
        to_thing = session.get(ThingRecord, rec.to_thing_id)
        if not from_thing or not to_thing:
            raise HTTPException(status_code=404, detail="One of the Things no longer exists")

        # Determine relationship type
        rel_type = body.relationship_type if body and body.relationship_type else rec.suggested_relationship_type

        # Create the actual relationship
        now = datetime.now(timezone.utc)
        rel_record = ThingRelationshipRecord(
            id=f"rel-{uuid.uuid4().hex[:8]}",
            from_thing_id=rec.from_thing_id,
            to_thing_id=rec.to_thing_id,
            relationship_type=rel_type,
            metadata_=None,
            created_at=now,
        )
        session.add(rel_record)

        # Mark suggestion as accepted
        rec.status = "accepted"
        rec.resolved_at = now
        session.add(rec)
        session.commit()
        session.refresh(rec)

    return _record_to_suggestion(rec, from_thing, to_thing)


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
    with Session(_engine_mod.engine) as session:
        rec = session.exec(
            select(ConnectionSuggestionRecord).where(
                ConnectionSuggestionRecord.id == suggestion_id,
                user_filter_clause(ConnectionSuggestionRecord.user_id, user_id),
            )
        ).first()
        if not rec:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        now = datetime.now(timezone.utc)
        rec.status = "dismissed"
        rec.resolved_at = now
        session.add(rec)

        from_thing = session.get(ThingRecord, rec.from_thing_id)
        to_thing = session.get(ThingRecord, rec.to_thing_id)

        session.commit()
        session.refresh(rec)

    if not from_thing or not to_thing:
        raise HTTPException(status_code=404, detail="Thing not found")

    return _record_to_suggestion(rec, from_thing, to_thing)


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
    with Session(_engine_mod.engine) as session:
        rec = session.exec(
            select(ConnectionSuggestionRecord).where(
                ConnectionSuggestionRecord.id == suggestion_id,
                user_filter_clause(ConnectionSuggestionRecord.user_id, user_id),
            )
        ).first()
        if not rec:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        rec.status = "deferred"
        session.add(rec)

        from_thing = session.get(ThingRecord, rec.from_thing_id)
        to_thing = session.get(ThingRecord, rec.to_thing_id)

        session.commit()
        session.refresh(rec)

    if not from_thing or not to_thing:
        raise HTTPException(status_code=404, detail="Thing not found")

    return _record_to_suggestion(rec, from_thing, to_thing)
