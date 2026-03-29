"""Staleness & neglect detection endpoint -- batch summary for notifications."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from ..db_engine import get_session, user_filter_clause
from ..db_models import ThingRecord

from ..auth import require_user
from ..database import db
from ..auth import user_filter
from ..models import (
    OverdueCheckin,
    StaleItem,
    StalenessCategory,
    StalenessReport,
)
from ..sweep import _parse_date_value
from .settings import get_user_stale_threshold
from .things import _record_to_thing, _row_to_thing

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

    # Use raw SQL for the subquery (active_children count)
    # TODO: convert to SQLModel query
    uf_sql, uf_params = user_filter(user_id)

    with db() as conn:
        stale_rows = conn.execute(
            f"""SELECT t.*,
                       (SELECT COUNT(*) FROM things c
                        WHERE c.parent_id = t.id AND c.active = 1) AS active_children
                FROM things t
                WHERE t.active = 1
                  AND t.updated_at < ?{uf_sql}
                ORDER BY t.updated_at ASC""",
            [stale_cutoff, *uf_params],
        ).fetchall()

        overdue_rows = conn.execute(
            f"""SELECT * FROM things
                WHERE active = 1
                  AND checkin_date IS NOT NULL
                  AND DATE(checkin_date) < ?{uf_sql}
                ORDER BY checkin_date ASC""",
            [cutoff, *uf_params],
        ).fetchall()

    stale_items: list[StaleItem] = []
    neglected_count = 0
    plain_stale_count = 0

    for row in stale_rows:
        thing = _row_to_thing(row)
        updated = row["updated_at"] or ""
        parsed = _parse_date_value(updated)
        days_stale = (today - parsed).days if parsed else threshold

        active_children = row["active_children"] or 0
        importance = row["importance"] if row["importance"] is not None else 2
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
    for row in overdue_rows:
        thing = _row_to_thing(row)
        parsed = _parse_date_value(row["checkin_date"])
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
