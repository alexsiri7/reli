"""CRUD endpoints for Thing Types."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..auth import require_user
from ..db_engine import get_session, user_filter_clause
from ..db_models import ThingTypeRecord
from ..models import ThingType, ThingTypeCreate, ThingTypeUpdate

router = APIRouter(prefix="/thing-types", tags=["thing-types"])


def _record_to_thing_type(record: ThingTypeRecord) -> ThingType:
    return ThingType(
        id=record.id,
        name=record.name,
        icon=record.icon,
        color=record.color,
        created_at=record.created_at or datetime.min,
    )


@router.get("", response_model=list[ThingType], summary="List all Thing Types")
def list_thing_types(
    limit: int = Query(100, ge=1, le=500, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> list[ThingType]:
    """List Thing Types owned by the current user plus system types (user_id=NULL)."""
    records = session.exec(
        select(ThingTypeRecord)
        .where(user_filter_clause(ThingTypeRecord.user_id, user_id))
        .order_by(ThingTypeRecord.name.asc())  # type: ignore[attr-defined]
        .limit(limit)
        .offset(offset)
    ).all()
    return [_record_to_thing_type(r) for r in records]


@router.get("/{type_id}", response_model=ThingType, summary="Get a Thing Type")
def get_thing_type(
    type_id: str,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> ThingType:
    """Retrieve a single Thing Type by ID (must belong to current user or be a system type)."""
    record = session.exec(
        select(ThingTypeRecord).where(
            ThingTypeRecord.id == type_id,
            user_filter_clause(ThingTypeRecord.user_id, user_id),
        )
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Thing type '{type_id}' not found")
    return _record_to_thing_type(record)


@router.post("", response_model=ThingType, status_code=status.HTTP_201_CREATED, summary="Create a Thing Type")
def create_thing_type(
    body: ThingTypeCreate,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> ThingType:
    """Create a new Thing Type scoped to the current user. Names must be unique per user."""
    existing = session.exec(
        select(ThingTypeRecord).where(
            ThingTypeRecord.name == body.name,
            ThingTypeRecord.user_id == user_id,
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Thing type with name '{body.name}' already exists",
        )

    record = ThingTypeRecord(
        id=str(uuid.uuid4()),
        name=body.name,
        icon=body.icon,
        color=body.color,
        created_at=datetime.now(timezone.utc),
        user_id=user_id,
    )
    session.add(record)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Thing type with name '{body.name}' already exists",
        )
    session.refresh(record)
    return _record_to_thing_type(record)


@router.patch("/{type_id}", response_model=ThingType, summary="Update a Thing Type")
def update_thing_type(
    type_id: str,
    body: ThingTypeUpdate,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> ThingType:
    """Partially update a Thing Type. Only the owning user may update.

    System types (built-in, user_id=NULL) are read-only and return 404.
    """
    record = session.exec(
        select(ThingTypeRecord).where(
            ThingTypeRecord.id == type_id,
            ThingTypeRecord.user_id == user_id,
        )
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Thing type '{type_id}' not found")

    if body.name is not None:
        existing = session.exec(
            select(ThingTypeRecord).where(
                ThingTypeRecord.name == body.name,
                ThingTypeRecord.user_id == user_id,
                ThingTypeRecord.id != type_id,
            )
        ).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Thing type with name '{body.name}' already exists",
            )
        record.name = body.name
    if body.icon is not None:
        record.icon = body.icon
    if body.color is not None:
        record.color = body.color

    session.add(record)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Thing type with name '{body.name}' already exists",
        )
    session.refresh(record)
    return _record_to_thing_type(record)


@router.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a Thing Type")
def delete_thing_type(
    type_id: str,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> None:
    """Delete a Thing Type by ID. Only the owning user may delete.

    System types (built-in, user_id=NULL) are read-only and return 404.
    """
    record = session.exec(
        select(ThingTypeRecord).where(
            ThingTypeRecord.id == type_id,
            ThingTypeRecord.user_id == user_id,
        )
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Thing type '{type_id}' not found")
    session.delete(record)
    session.commit()
