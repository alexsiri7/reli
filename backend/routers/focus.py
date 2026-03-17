"""Focus recommendations — prioritized focus list based on graph analysis."""

import re
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..auth import require_user, user_filter
from ..database import db
from ..models import FocusRecommendation, FocusResponse, Thing
from .things import _row_to_thing

router = APIRouter(prefix="/focus", tags=["focus"])

# Date keys in thing.data that represent deadlines
_DEADLINE_KEYS = {"deadline", "due_date", "due", "event_date", "starts_at", "start_date", "date"}
_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

# Relationship types that indicate blocking
_BLOCKING_REL_TYPES = {"depends-on", "blocked-by", "waiting-on"}


def _parse_date_value(value: object) -> date | None:
    if isinstance(value, str):
        m = _DATE_RE.search(value)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def _extract_deadline(data: dict[str, Any] | None) -> date | None:
    """Extract the earliest deadline from a thing's data dict."""
    if not data:
        return None
    earliest: date | None = None
    for key, value in data.items():
        if key.lower().replace(" ", "_") in _DEADLINE_KEYS:
            parsed = _parse_date_value(value)
            if parsed and (earliest is None or parsed < earliest):
                earliest = parsed
    return earliest


def _staleness_days(thing: Thing, today: date) -> int:
    """Number of days since the thing was last updated."""
    updated = thing.updated_at
    if isinstance(updated, str):
        updated = datetime.fromisoformat(updated)
    return (today - updated.date()).days


def _score_thing(
    thing: Thing,
    today: date,
    blocked_ids: set[str],
    blocking_ids: set[str],
    calendar_thing_ids: set[str],
) -> tuple[float, list[str]]:
    """Score a thing for focus priority. Returns (score, list of reasons)."""
    score = 0.0
    reasons: list[str] = []

    # 1. Priority (1=highest, 5=lowest) — strong signal
    priority_scores = {1: 50, 2: 40, 3: 25, 4: 15, 5: 5}
    pscore = priority_scores.get(thing.priority, 25)
    score += pscore
    if thing.priority <= 2:
        reasons.append(f"High priority (P{thing.priority})")

    # 2. Deadline urgency
    deadline = _extract_deadline(thing.data)
    if deadline:
        days_until = (deadline - today).days
        if days_until < 0:
            score += 60
            reasons.append(f"Overdue by {abs(days_until)}d")
        elif days_until == 0:
            score += 55
            reasons.append("Due today")
        elif days_until == 1:
            score += 45
            reasons.append("Due tomorrow")
        elif days_until <= 3:
            score += 35
            reasons.append(f"Due in {days_until}d")
        elif days_until <= 7:
            score += 20
            reasons.append(f"Due in {days_until}d")
        elif days_until <= 14:
            score += 10
            reasons.append(f"Due in {days_until}d")

    # 3. Checkin date urgency
    if thing.checkin_date:
        checkin = thing.checkin_date
        if isinstance(checkin, str):
            checkin = datetime.fromisoformat(checkin)
        checkin_date = checkin.date()
        days_until_checkin = (checkin_date - today).days
        if days_until_checkin <= 0:
            score += 30
            if days_until_checkin < 0:
                reasons.append(f"Check-in overdue by {abs(days_until_checkin)}d")
            else:
                reasons.append("Check-in due today")
        elif days_until_checkin <= 3:
            score += 15
            reasons.append(f"Check-in in {days_until_checkin}d")

    # 4. Blocked/unblocked status
    if thing.id in blocked_ids:
        score -= 30
        reasons.append("Blocked by dependencies")
    elif thing.id in blocking_ids:
        score += 20
        reasons.append("Unblocks other items")

    # 5. Staleness — active but neglected things need attention
    stale_days = _staleness_days(thing, today)
    if stale_days >= 30:
        score += 15
        reasons.append(f"Stale ({stale_days}d since update)")
    elif stale_days >= 14:
        score += 8
        reasons.append(f"Not updated in {stale_days}d")

    # 6. Calendar awareness
    if thing.id in calendar_thing_ids:
        score += 15
        reasons.append("Related calendar event upcoming")

    # 7. Open questions — things with unresolved questions need attention
    if thing.open_questions and len(thing.open_questions) > 0:
        score += 5
        reasons.append(f"{len(thing.open_questions)} open question(s)")

    # 8. Project progress — projects with partial completion get a boost
    if thing.type_hint == "project" and thing.children_count and thing.children_count > 0:
        completed = thing.completed_count or 0
        if completed > 0 and completed < thing.children_count:
            pct = completed / thing.children_count
            if pct >= 0.5:
                score += 10
                reasons.append(f"Project {int(pct * 100)}% complete — close to finish")

    # Default reason if none
    if not reasons:
        reasons.append("Active item")

    return score, reasons


def _match_calendar_events_to_things(
    things: list[Thing],
    calendar_events: list[dict[str, Any]],
) -> set[str]:
    """Find thing IDs that match upcoming calendar events by title similarity."""
    matched: set[str] = set()
    if not calendar_events:
        return matched

    event_titles_lower = [e.get("summary", "").lower() for e in calendar_events]

    for thing in things:
        title_lower = thing.title.lower()
        for event_title in event_titles_lower:
            if not event_title:
                continue
            # Simple substring match in either direction
            if title_lower in event_title or event_title in title_lower:
                matched.add(thing.id)
                break
            # Word overlap (at least 2 meaningful words in common)
            thing_words = {w for w in title_lower.split() if len(w) > 2}
            event_words = {w for w in event_title.split() if len(w) > 2}
            if len(thing_words & event_words) >= 2:
                matched.add(thing.id)
                break

    return matched


@router.get("", response_model=FocusResponse, summary="Focus Recommendations")
def get_focus_recommendations(
    limit: int = Query(10, ge=1, le=50, description="Maximum number of recommendations"),
    user_id: str = Depends(require_user),
) -> FocusResponse:
    """Analyze the thing graph to generate a prioritized focus list with reasoning."""
    today = date.today()
    uf_sql, uf_params = user_filter(user_id)

    with db() as conn:
        # Fetch all active, surfaced things
        thing_rows = conn.execute(
            f"""SELECT * FROM things
               WHERE active = 1 AND surface = 1{uf_sql}
               ORDER BY priority ASC""",
            uf_params,
        ).fetchall()

        # Fetch all relationships to determine blocked/blocking status
        rel_rows = conn.execute(
            f"""SELECT tr.from_thing_id, tr.to_thing_id, tr.relationship_type
               FROM thing_relationships tr
               JOIN things t1 ON tr.from_thing_id = t1.id AND t1.active = 1
               JOIN things t2 ON tr.to_thing_id = t2.id AND t2.active = 1{uf_sql}""",
            uf_params,
        ).fetchall()

    things = [_row_to_thing(r) for r in thing_rows]
    active_ids = {t.id for t in things}

    # Determine blocked things: a thing is blocked if it depends on another active thing
    blocked_ids: set[str] = set()
    blocking_ids: set[str] = set()
    for rel in rel_rows:
        rel_type = rel["relationship_type"].lower().replace(" ", "-")
        if rel_type in _BLOCKING_REL_TYPES:
            from_id = rel["from_thing_id"]
            to_id = rel["to_thing_id"]
            if from_id in active_ids and to_id in active_ids:
                # from_thing depends on to_thing → from_thing is blocked
                blocked_ids.add(from_id)
                # to_thing is a blocker (unblocks from_thing when done)
                blocking_ids.add(to_id)

    # Calendar awareness — try to fetch events if calendar is connected
    calendar_thing_ids: set[str] = set()
    try:
        from ..google_calendar import fetch_upcoming_events, is_connected

        if is_connected(user_id=user_id):
            events = fetch_upcoming_events(days_ahead=7, user_id=user_id)
            calendar_thing_ids = _match_calendar_events_to_things(
                things, [{"summary": e.get("summary", "")} for e in events]
            )
    except Exception:
        pass  # Calendar is optional

    # Score and rank things
    scored: list[tuple[Thing, float, list[str]]] = []
    for thing in things:
        score, reasons = _score_thing(thing, today, blocked_ids, blocking_ids, calendar_thing_ids)
        scored.append((thing, score, reasons))

    # Sort by score descending
    scored.sort(key=lambda x: -x[1])

    # Build response
    recommendations: list[FocusRecommendation] = []
    for rank, (thing, score, reasons) in enumerate(scored[:limit], start=1):
        dl = _extract_deadline(thing.data)
        recommendations.append(
            FocusRecommendation(
                thing=thing,
                score=round(score, 1),
                reasons=reasons,
                rank=rank,
                is_blocked=thing.id in blocked_ids,
                deadline=dl.isoformat() if dl else None,
            )
        )

    return FocusResponse(
        recommendations=recommendations,
        total_active=len(things),
        generated_at=datetime.now(tz=None).isoformat(),
    )
