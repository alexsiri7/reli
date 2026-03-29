"""Weekly digest endpoints."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_user
from ..models import WeeklyDigestContent, WeeklyDigestResponse
from ..weekly_digest import generate_weekly_digest, get_latest_weekly_digest, store_weekly_digest

router = APIRouter(prefix="/digest", tags=["digest"])


@router.get("/latest", response_model=WeeklyDigestResponse, summary="Get latest weekly digest")
def get_latest_digest(
    user_id: str = Depends(require_user),
) -> WeeklyDigestResponse:
    """Return the most recently stored weekly digest, or generate one if none exists."""
    row = get_latest_weekly_digest(user_id)
    if row is None:
        # Generate on-demand if no stored digest
        content = generate_weekly_digest(user_id)
        digest_id = store_weekly_digest(user_id, content)
        return WeeklyDigestResponse(
            id=digest_id,
            week_start=content.week_start,
            content=content,
            generated_at=date.today().isoformat(),
        )

    content = WeeklyDigestContent(**row["content"])
    return WeeklyDigestResponse(
        id=row["id"],
        week_start=row["week_start"],
        content=content,
        generated_at=row["generated_at"],
    )


@router.get("/week/{week_start}", response_model=WeeklyDigestResponse, summary="Get digest for a specific week")
def get_digest_for_week(
    week_start: str,
    user_id: str = Depends(require_user),
) -> WeeklyDigestResponse:
    """Return the digest for the specified week (YYYY-MM-DD format, Monday of the week)."""
    try:
        week_date = date.fromisoformat(week_start)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    row = get_latest_weekly_digest(user_id, week_start=week_date)
    if row is None:
        # Generate for this week if not found
        content = generate_weekly_digest(user_id, week_start=week_date)
        digest_id = store_weekly_digest(user_id, content)
        return WeeklyDigestResponse(
            id=digest_id,
            week_start=content.week_start,
            content=content,
            generated_at=date.today().isoformat(),
        )

    content = WeeklyDigestContent(**row["content"])
    return WeeklyDigestResponse(
        id=row["id"],
        week_start=row["week_start"],
        content=content,
        generated_at=row["generated_at"],
    )


@router.post("/generate", response_model=WeeklyDigestResponse, summary="Force-generate weekly digest")
def generate_digest(
    week_start: str | None = Query(default=None, description="Week start (YYYY-MM-DD). Defaults to most recent completed week."),
    user_id: str = Depends(require_user),
) -> WeeklyDigestResponse:
    """Generate (or regenerate) a weekly digest and store it."""
    week_date: date | None = None
    if week_start:
        try:
            week_date = date.fromisoformat(week_start)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    content = generate_weekly_digest(user_id, week_start=week_date)
    digest_id = store_weekly_digest(user_id, content)
    return WeeklyDigestResponse(
        id=digest_id,
        week_start=content.week_start,
        content=content,
        generated_at=date.today().isoformat(),
    )
