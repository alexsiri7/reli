"""CRUD endpoints for Thing Types."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from ..db_engine import get_session
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
    session: Session = Depends(get_session),
) -> list[ThingType]:
    """List all Thing Types, sorted alphabetically by name."""
    records = session.exec(
        select(ThingTypeRecord)
        .order_by(ThingTypeRecord.name.asc())  # type: ignore[attr-defined]
        .limit(limit)
        .offset(offset)
    ).all()
    return [_record_to_thing_type(r) for r in records]


@router.get("/{type_id}", response_model=ThingType, summary="Get a Thing Type")
def get_thing_type(
    type_id: str,
    session: Session = Depends(get_session),
) -> ThingType:
    """Retrieve a single Thing Type by ID."""
    record = session.get(ThingTypeRecord, type_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Thing type '{type_id}' not found")
    return _record_to_thing_type(record)


@router.post("", response_model=ThingType, status_code=status.HTTP_201_CREATED, summary="Create a Thing Type")
def create_thing_type(
    body: ThingTypeCreate,
    session: Session = Depends(get_session),
) -> ThingType:
    """Create a new Thing Type. Names must be unique."""
    existing = session.exec(select(ThingTypeRecord).where(ThingTypeRecord.name == body.name)).first()
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
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return _record_to_thing_type(record)


@router.patch("/{type_id}", response_model=ThingType, summary="Update a Thing Type")
def update_thing_type(
    type_id: str,
    body: ThingTypeUpdate,
    session: Session = Depends(get_session),
) -> ThingType:
    """Partially update a Thing Type. Names must remain unique."""
    record = session.get(ThingTypeRecord, type_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Thing type '{type_id}' not found")

    if body.name is not None:
        existing = session.exec(
            select(ThingTypeRecord).where(
                ThingTypeRecord.name == body.name,
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
    session.commit()
    session.refresh(record)
    return _record_to_thing_type(record)


@router.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a Thing Type")
def delete_thing_type(
    type_id: str,
    session: Session = Depends(get_session),
) -> None:
    """Delete a Thing Type by ID."""
    record = session.get(ThingTypeRecord, type_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Thing type '{type_id}' not found")
    session.delete(record)
    session.commit()
