"""Priority & focus recommendations — analyze the thing graph to suggest what to work on."""

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..auth import require_user, user_filter
from ..database import db
from ..google_calendar import fetch_upcoming_events, is_connected
from ..models import FocusRecommendation, FocusRecommendationsResponse, Thing
from .things import _row_to_thing

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

# Date keys in data dict that represent deadlines
_DEADLINE_KEYS = {"deadline", "due_date", "due", "end_date", "ends_at"}


def _parse_date(value: object) -> date | None:
    """Extract a date from a JSON string value."""
    if not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value[:19], fmt[:min(len(fmt), 19)]).date()
        except ValueError:
            continue
    # Try just date portion
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, IndexError):
        return None


def _get_deadline(data: dict[str, Any] | None) -> date | None:
    """Extract the earliest deadline from a thing's data dict."""
    if not data:
        return None
    earliest: date | None = None
    for key, value in data.items():
        if key.lower().replace(" ", "_") in _DEADLINE_KEYS:
            d = _parse_date(value)
            if d and (earliest is None or d < earliest):
                earliest = d
    return earliest


def _score_thing(
    thing: Thing,
    today: date,
    relationship_counts: dict[str, int],
    blocked_by: dict[str, list[str]],
    blocks_others: set[str],
    calendar_thing_ids: set[str],
) -> tuple[float, list[str]]:
    """Score a thing for focus priority. Higher score = more urgent/important.

    Returns (score, list_of_reasons).
    """
    score = 0.0
    reasons: list[str] = []

    # 1. Priority (1=highest → score boost of 40, 5=lowest → 0)
    priority_score = max(0, (6 - thing.priority)) * 10
    score += priority_score
    if thing.priority <= 2:
        reasons.append(f"High priority (P{thing.priority})")

    # 2. Checkin date urgency
    if thing.checkin_date:
        checkin_d = thing.checkin_date.date() if isinstance(thing.checkin_date, datetime) else thing.checkin_date
        days_until = (checkin_d - today).days
        if days_until < 0:
            score += 30 + min(abs(days_until), 30)
            reasons.append(f"Check-in overdue by {abs(days_until)}d")
        elif days_until == 0:
            score += 25
            reasons.append("Check-in due today")
        elif days_until <= 3:
            score += 15
            reasons.append(f"Check-in in {days_until}d")

    # 3. Deadline urgency (from data dict)
    deadline = _get_deadline(thing.data)
    if deadline:
        days_until_deadline = (deadline - today).days
        if days_until_deadline < 0:
            score += 35 + min(abs(days_until_deadline), 30)
            reasons.append(f"Deadline overdue by {abs(days_until_deadline)}d")
        elif days_until_deadline == 0:
            score += 30
            reasons.append("Deadline today")
        elif days_until_deadline <= 3:
            score += 20
            reasons.append(f"Deadline in {days_until_deadline}d")
        elif days_until_deadline <= 7:
            score += 10
            reasons.append(f"Deadline in {days_until_deadline}d")

    # 4. Staleness — active but not referenced recently
    if thing.last_referenced:
        ref_dt = thing.last_referenced if isinstance(thing.last_referenced, datetime) else datetime.fromisoformat(str(thing.last_referenced))
        days_stale = (datetime.utcnow() - ref_dt).days
        if days_stale >= 14:
            stale_score = min(days_stale // 7, 4) * 5
            score += stale_score
            reasons.append(f"Not reviewed in {days_stale}d")
    elif thing.updated_at:
        updated_dt = thing.updated_at if isinstance(thing.updated_at, datetime) else datetime.fromisoformat(str(thing.updated_at))
        days_since_update = (datetime.utcnow() - updated_dt).days
        if days_since_update >= 14:
            score += min(days_since_update // 7, 4) * 3
            reasons.append(f"Untouched for {days_since_update}d")

    # 5. Open questions — things with unanswered questions need attention
    if thing.open_questions and len(thing.open_questions) > 0:
        oq_count = len(thing.open_questions)
        score += min(oq_count, 3) * 5
        reasons.append(f"{oq_count} open question{'s' if oq_count != 1 else ''}")

    # 6. Blocks others — if this thing blocks other things, prioritize it
    if thing.id in blocks_others:
        score += 20
        reasons.append("Blocks other items")

    # 7. Is blocked — deprioritize things that are blocked
    if thing.id in blocked_by:
        blockers = blocked_by[thing.id]
        score -= 15
        reasons.append(f"Blocked by {len(blockers)} item{'s' if len(blockers) != 1 else ''}")

    # 8. Relationship density — well-connected things are often more important
    rel_count = relationship_counts.get(thing.id, 0)
    if rel_count >= 3:
        score += min(rel_count, 8) * 2
        reasons.append(f"Connected to {rel_count} items")

    # 9. Calendar awareness — things linked to upcoming calendar events
    if thing.id in calendar_thing_ids:
        score += 15
        reasons.append("Related to upcoming calendar event")

    # 10. Type boost — tasks and projects are more actionable
    if thing.type_hint in ("task", "project", "goal"):
        score += 5

    # Ensure at least one reason
    if not reasons:
        reasons.append("Active item")

    return score, reasons


def _match_calendar_events_to_things(
    events: list[dict[str, Any]], things: list[Thing]
) -> set[str]:
    """Match calendar event summaries to thing titles (fuzzy text match)."""
    matched_ids: set[str] = set()
    for event in events:
        summary = (event.get("summary") or "").lower()
        if not summary:
            continue
        for thing in things:
            title_lower = thing.title.lower()
            # Simple substring match in either direction
            if title_lower in summary or summary in title_lower:
                matched_ids.add(thing.id)
            # Also check individual words (3+ chars) for partial matching
            elif any(
                word in summary
                for word in title_lower.split()
                if len(word) >= 4
            ):
                matched_ids.add(thing.id)
    return matched_ids


@router.get("", response_model=FocusRecommendationsResponse, summary="Focus Recommendations")
def get_recommendations(
    limit: int = Query(10, ge=1, le=50, description="Max recommendations to return"),
    user_id: str = Depends(require_user),
) -> FocusRecommendationsResponse:
    """Analyze the thing graph and return a prioritized focus list with reasoning."""
    today = date.today()
    uf_sql, uf_params = user_filter(user_id)

    with db() as conn:
        # Fetch active things
        thing_rows = conn.execute(
            f"SELECT * FROM things WHERE active = 1{uf_sql}",
            uf_params,
        ).fetchall()

        # Fetch relationship counts per thing
        rel_rows = conn.execute(
            """SELECT thing_id, COUNT(*) as cnt FROM (
                SELECT from_thing_id as thing_id FROM thing_relationships
                UNION ALL
                SELECT to_thing_id as thing_id FROM thing_relationships
            ) GROUP BY thing_id"""
        ).fetchall()

        # Fetch blocking relationships
        block_rows = conn.execute(
            """SELECT from_thing_id, to_thing_id, relationship_type
               FROM thing_relationships
               WHERE relationship_type IN ('blocks', 'depends-on')"""
        ).fetchall()

    things = [_row_to_thing(r) for r in thing_rows]

    # Build relationship maps
    relationship_counts: dict[str, int] = {r["thing_id"]: r["cnt"] for r in rel_rows}

    # blocked_by: thing_id -> list of thing_ids that block it
    # blocks_others: set of thing_ids that block something
    blocked_by: dict[str, list[str]] = {}
    blocks_others: set[str] = set()
    for r in block_rows:
        from_id = r["from_thing_id"]
        to_id = r["to_thing_id"]
        rel_type = r["relationship_type"]
        if rel_type == "blocks":
            # from blocks to → to is blocked by from
            blocked_by.setdefault(to_id, []).append(from_id)
            blocks_others.add(from_id)
        elif rel_type == "depends-on":
            # from depends on to → from is blocked by to
            blocked_by.setdefault(from_id, []).append(to_id)
            blocks_others.add(to_id)

    # Calendar awareness
    calendar_thing_ids: set[str] = set()
    if is_connected(user_id=user_id):
        try:
            events = fetch_upcoming_events(max_results=20, days_ahead=7, user_id=user_id)
            calendar_thing_ids = _match_calendar_events_to_things(events, things)
        except Exception:
            pass  # Calendar is best-effort

    # Score all active, surfaceable things
    scored: list[tuple[Thing, float, list[str]]] = []
    for thing in things:
        if not thing.surface:
            continue
        score, reasons = _score_thing(
            thing, today, relationship_counts, blocked_by, blocks_others, calendar_thing_ids
        )
        if score > 0:
            scored.append((thing, score, reasons))

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Build response
    recommendations = [
        FocusRecommendation(
            thing=thing,
            score=round(score, 1),
            reasons=reasons,
        )
        for thing, score, reasons in scored[:limit]
    ]

    return FocusRecommendationsResponse(
        recommendations=recommendations,
        total=len(scored),
        generated_at=datetime.utcnow().isoformat(),
    )
