"""Daily briefing endpoint."""

from datetime import date, datetime

from fastapi import APIRouter

from ..database import db
from ..models import BriefingResponse, Thing
from .things import _row_to_thing

router = APIRouter(prefix="/briefing", tags=["briefing"])


@router.get("", response_model=BriefingResponse, summary="Daily Briefing")
def get_briefing(as_of: date | None = None) -> BriefingResponse:
    """Return all active Things whose checkin_date is today or earlier.

    Pass `as_of` to query for a specific date (defaults to today UTC).
    """
    target = as_of or date.today()
    cutoff = datetime.combine(target, datetime.max.time()).isoformat()

    with db() as conn:
        rows = conn.execute(
            """SELECT * FROM things
               WHERE active = 1
                 AND checkin_date IS NOT NULL
                 AND checkin_date <= ?
               ORDER BY checkin_date ASC, priority ASC""",
            (cutoff,),
        ).fetchall()

    things: list[Thing] = [_row_to_thing(r) for r in rows]
    return BriefingResponse(
        date=target.isoformat(),
        things=things,
        total=len(things),
    )
