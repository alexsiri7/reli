"""Staleness & neglect detection endpoint -- batch summary for notifications."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlmodel import Session, select

import backend.db_engine as _engine_mod

from ..auth import require_user
from ..db_engine import user_filter_clause
from ..db_models import ThingRecord, ThingRelationshipRecord
from ..models import (
    OverdueCheckin,
    StaleItem,
    StalenessCategory,
    StalenessReport,
)
from ..sweep import _parse_date_value
from .settings import get_user_stale_threshold
from .things import _record_to_thing

router = APIRouter(prefix="/staleness", tags=["staleness"])


@router.get("", response_model=StalenessReport, summary="Staleness & neglect report")
def get_staleness_report(
    stale_days: int | None = Query(
        default=None,
        ge=1,
        le=365,
        description="Override staleness threshold (days).",
    ),
    user_id: str = Depends(require_user),
) -> StalenessReport:
    """Return a batch summary of stale and neglected Things."""
    today = date.today()
    threshold = stale_days if stale_days is not None else get_user_stale_threshold(user_id)
    cutoff = today.isoformat()
    stale_cutoff = (today - timedelta(days=threshold)).isoformat()

    with Session(_engine_mod.engine) as session:
        # Subquery: count active children per thing via parent-of relationships
        _child = ThingRecord.__table__.alias("child")
        child_count_sq = (
            sa_select(
                ThingRelationshipRecord.from_thing_id.label("parent_id"),
                func.count().label("active_children"),
            )
            .join(_child, _child.c.id == ThingRelationshipRecord.to_thing_id)
            .where(
                ThingRelationshipRecord.relationship_type == "parent-of",
                _child.c.active,
            )
            .group_by(ThingRelationshipRecord.from_thing_id)
            .subquery()
        )

        # Stale things with active_children count
        stale_stmt = (
            select(ThingRecord, child_count_sq.c.active_children)
            .outerjoin(child_count_sq, ThingRecord.id == child_count_sq.c.parent_id)
            .where(
                ThingRecord.active,
                ThingRecord.updated_at < stale_cutoff,
                user_filter_clause(ThingRecord.user_id, user_id),
            )
            .order_by(ThingRecord.updated_at.asc())  # type: ignore[union-attr]
        )
        stale_results = session.exec(stale_stmt).all()

        # Overdue checkins
        overdue_stmt = (
            select(ThingRecord)
            .where(
                ThingRecord.active,
                ThingRecord.checkin_date.is_not(None),  # type: ignore[union-attr]
                ThingRecord.checkin_date < cutoff,  # type: ignore[operator]
                user_filter_clause(ThingRecord.user_id, user_id),
            )
            .order_by(ThingRecord.checkin_date.asc())  # type: ignore[union-attr]
        )
        overdue_records = session.exec(overdue_stmt).all()

    stale_items: list[StaleItem] = []
    neglected_count = 0
    plain_stale_count = 0

    for record, active_children_val in stale_results:
        active_children = active_children_val or 0

        thing = _record_to_thing(record)
        updated = record.updated_at or ""
        parsed = _parse_date_value(str(updated) if updated else "")
        days_stale = (today - parsed).days if parsed else threshold

        importance = record.importance if record.importance is not None else 2
        is_neglected = importance <= 1 or active_children > 0

        if is_neglected:
            neglected_count += 1
        else:
            plain_stale_count += 1

        stale_items.append(
            StaleItem(
                thing=thing,
                days_stale=days_stale,
                is_neglected=is_neglected,
                active_children=active_children,
            )
        )

    overdue_list: list[OverdueCheckin] = []
    for record in overdue_records:
        thing = _record_to_thing(record)
        parsed = _parse_date_value(str(record.checkin_date) if record.checkin_date else "")
        days_overdue = (today - parsed).days if parsed else 1
        overdue_list.append(OverdueCheckin(thing=thing, days_overdue=days_overdue))

    total = len(stale_items) + len(overdue_list)

    return StalenessReport(
        as_of=today.isoformat(),
        stale_threshold_days=threshold,
        stale_items=stale_items,
        overdue_checkins=overdue_list,
        counts=StalenessCategory(
            stale=plain_stale_count,
            neglected=neglected_count,
            overdue_checkins=len(overdue_list),
        ),
        total=total,
    )
