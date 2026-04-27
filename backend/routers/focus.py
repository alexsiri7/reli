"""Focus recommendations -- prioritized list of Things the user should focus on."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

import backend.db_engine as _engine_mod

from ..auth import require_user
from ..db_engine import user_filter_clause
from ..db_models import ThingRecord, ThingRelationshipRecord
from ..google_calendar import fetch_upcoming_events
from ..google_calendar import is_connected as calendar_connected
from ..models import FocusRecommendation, FocusResponse, Thing
from .things import _record_to_thing

router = APIRouter(prefix="/focus", tags=["focus"])

# Date parsing
_RECURRING_KEYS = {"birthday", "anniversary", "born", "date_of_birth", "dob"}
_ONESHOT_KEYS = {
    "deadline",
    "due_date",
    "due",
    "event_date",
    "starts_at",
    "start_date",
    "ends_at",
    "end_date",
    "date",
}
_ALL_DATE_KEYS = _RECURRING_KEYS | _ONESHOT_KEYS
_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _parse_date(value: object) -> date | None:
    if isinstance(value, str):
        m = _DATE_RE.search(value)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def _earliest_deadline(data: dict | None) -> date | None:
    if not data:
        return None
    earliest: date | None = None
    for key, value in data.items():
        key_lower = key.lower().replace(" ", "_")
        if key_lower not in _ONESHOT_KEYS:
            continue
        parsed = _parse_date(value)
        if parsed and (earliest is None or parsed < earliest):
            earliest = parsed
    return earliest


def _days_stale(updated_at: str | None, today: date) -> int:
    if not updated_at:
        return 0
    parsed = _parse_date(updated_at)
    if not parsed:
        return 0
    return max(0, (today - parsed).days)


def _compute_recommendations(
    user_id: str,
    limit: int,
    today: date | None = None,
) -> FocusResponse:
    """Analyze the thing graph and produce a scored, prioritized focus list."""
    today = today or date.today()

    with Session(_engine_mod.engine) as session:
        thing_stmt = (
            select(ThingRecord)
            .where(
                ThingRecord.active == True,
                user_filter_clause(ThingRecord.user_id, user_id),
            )
            .order_by(ThingRecord.importance.asc(), ThingRecord.updated_at.desc())
        )  # type: ignore[union-attr, attr-defined]
        thing_records = session.exec(thing_stmt).all()

        rel_records = session.exec(select(ThingRelationshipRecord)).all()

    things = [_record_to_thing(r) for r in thing_records]
    thing_map: dict[str, Thing] = {t.id: t for t in things}
    active_ids = set(thing_map.keys())

    # Build blocking graph
    blocked_by: dict[str, set[str]] = {}
    blocks: dict[str, set[str]] = {}
    for r in rel_records:
        rtype = r.relationship_type
        from_id = r.from_thing_id
        to_id = r.to_thing_id
        if rtype == "depends-on":
            if from_id in active_ids and to_id in active_ids:
                blocked_by.setdefault(from_id, set()).add(to_id)
                blocks.setdefault(to_id, set()).add(from_id)
        elif rtype == "blocks":
            if from_id in active_ids and to_id in active_ids:
                blocked_by.setdefault(to_id, set()).add(from_id)
                blocks.setdefault(from_id, set()).add(to_id)

    # Calendar awareness
    calendar_events: list[dict[str, Any]] = []
    has_calendar = False
    try:
        if calendar_connected(user_id=user_id):
            has_calendar = True
            calendar_events = fetch_upcoming_events(max_results=50, days_ahead=7, user_id=user_id)
    except Exception:
        pass

    busy_today_summaries: set[str] = set()
    for evt in calendar_events:
        start_str = evt.get("start", "")
        start_date = _parse_date(start_str)
        if start_date and start_date == today:
            summary = (evt.get("summary") or "").lower()
            if summary:
                busy_today_summaries.add(summary)

    scored: list[tuple[float, Thing, list[str]]] = []

    for thing in things:
        if thing.type_hint in ("person", "place", "concept", "reference", "preference"):
            continue

        score = 0.0
        reasons: list[str] = []
        is_blocked = thing.id in blocked_by

        importance_boost = (4 - thing.importance) * 25
        score += importance_boost
        if thing.importance <= 1:
            reasons.append(f"High importance ({thing.importance})")

        deadline = _earliest_deadline(thing.data)
        if deadline:
            days_until = (deadline - today).days
            if days_until < 0:
                score += 150
                reasons.append(f"Overdue by {abs(days_until)}d")
            elif days_until == 0:
                score += 130
                reasons.append("Due today")
            elif days_until == 1:
                score += 110
                reasons.append("Due tomorrow")
            elif days_until <= 3:
                score += 80
                reasons.append(f"Due in {days_until}d")
            elif days_until <= 7:
                score += 40
                reasons.append(f"Due in {days_until}d")

        if thing.checkin_date:
            checkin = _parse_date(str(thing.checkin_date))
            if checkin:
                days_until_checkin = (checkin - today).days
                if days_until_checkin <= 0:
                    score += 90
                    if days_until_checkin < 0:
                        reasons.append(f"Check-in overdue by {abs(days_until_checkin)}d")
                    else:
                        reasons.append("Check-in due today")
                elif days_until_checkin == 1:
                    score += 50
                    reasons.append("Check-in tomorrow")
                elif days_until_checkin <= 3:
                    score += 25
                    reasons.append(f"Check-in in {days_until_checkin}d")

        if is_blocked:
            score -= 80
            blocker_titles = [thing_map[bid].title for bid in blocked_by[thing.id] if bid in thing_map]
            if blocker_titles:
                reasons.append(f"Blocked by: {', '.join(blocker_titles[:2])}")
            else:
                reasons.append("Blocked by dependencies")
        elif thing.id in blocks:
            unblocks_count = len(blocks[thing.id])
            score += unblocks_count * 30
            reasons.append(f"Unblocks {unblocks_count} other item{'s' if unblocks_count != 1 else ''}")

        stale_days = _days_stale(
            thing.updated_at.isoformat() if isinstance(thing.updated_at, datetime) else str(thing.updated_at),
            today,
        )
        if stale_days >= 30:
            score += 25
            reasons.append(f"Untouched for {stale_days}d")
        elif stale_days >= 14:
            score += 15
            reasons.append(f"Untouched for {stale_days}d")

        if thing.last_referenced:
            ref_date = _parse_date(str(thing.last_referenced))
            if ref_date:
                days_since_ref = (today - ref_date).days
                if days_since_ref <= 1:
                    score += 15
                    reasons.append("Recently discussed")
                elif days_since_ref <= 3:
                    score += 8

        if thing.open_questions and len(thing.open_questions) > 0:
            score += 10
            reasons.append(f"{len(thing.open_questions)} open question{'s' if len(thing.open_questions) != 1 else ''}")

        if has_calendar and busy_today_summaries:
            title_lower = thing.title.lower()
            for summary in busy_today_summaries:
                if (
                    summary in title_lower
                    or title_lower in summary
                    or any(w in title_lower for w in summary.split() if len(w) > 3)
                ):
                    score += 35
                    reasons.append("Related to today's calendar")
                    break

        if thing.type_hint == "task":
            score += 5
        elif thing.type_hint == "goal":
            score += 3

        if score > 0 or reasons:
            if not reasons:
                reasons.append("Active item")
            scored.append((score, thing, reasons))

    scored.sort(key=lambda x: -x[0])

    recommendations: list[FocusRecommendation] = []
    for score, thing, reasons in scored[:limit]:
        recommendations.append(
            FocusRecommendation(
                thing=thing,
                score=round(score, 1),
                reasons=reasons,
                is_blocked=thing.id in blocked_by,
            )
        )

    return FocusResponse(
        recommendations=recommendations,
        total=len(scored),
        calendar_active=has_calendar,
    )


@router.get("", response_model=FocusResponse, summary="Focus Recommendations")
def get_focus_recommendations(
    limit: int = Query(10, ge=1, le=50, description="Max recommendations to return"),
    user_id: str = Depends(require_user),
) -> FocusResponse:
    """Analyze the thing graph and return a prioritized focus list."""
    return _compute_recommendations(user_id=user_id, limit=limit)
