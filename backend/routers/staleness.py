"""Staleness & neglect detection endpoint — batch summary for notifications."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query

from ..auth import require_user, user_filter
from ..database import db
from ..models import (
    OverdueCheckin,
    StaleItem,
    StalenessCategory,
    StalenessReport,
)
from ..sweep import _parse_date_value
from .settings import get_user_stale_threshold
from .things import _row_to_thing

router = APIRouter(prefix="/staleness", tags=["staleness"])


@router.get("", response_model=StalenessReport, summary="Staleness & neglect report")
def get_staleness_report(
    stale_days: int | None = Query(
        default=None,
        ge=1,
        le=365,
        description="Override staleness threshold (days). Uses per-user setting if omitted.",
    ),
    user_id: str = Depends(require_user),
) -> StalenessReport:
    """Return a batch summary of stale and neglected Things.

    Stale: active Things not updated within *stale_days*.
    Neglected: stale Things that also have high priority or pending children.
    Overdue check-ins: active Things whose checkin_date is in the past.
    """
    today = date.today()
    threshold = stale_days if stale_days is not None else get_user_stale_threshold(user_id)
    cutoff = today.isoformat()
    stale_cutoff = (today - timedelta(days=threshold)).isoformat()

    uf_sql, uf_params = user_filter(user_id)

    with db() as conn:
        # Stale / neglected items
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

        # Overdue check-ins
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
        priority = row["priority"] or 3
        is_neglected = priority <= 2 or active_children > 0

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
