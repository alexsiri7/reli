"""Weekly digest generation — summarises the past 7 days for the user.

Content:
- Items completed (active=0, updated in the past week)
- New connections discovered (thing_relationships created in the past week)
- Preferences learned/strengthened (preference Things updated in the past week)
- Upcoming deadlines (date fields falling in the next 7 days)
- Open questions (Things with non-empty open_questions)
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import aliased
from sqlmodel import Session, or_, select

import backend.db_engine as _engine_mod

from .db_engine import user_filter_clause
from .db_models import ThingRecord, ThingRelationshipRecord, WeeklyBriefingRecord
from .models import (
    WeeklyBriefingConnection,
    WeeklyBriefingContent,
    WeeklyBriefingItem,
)

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_ALL_DATE_KEYS = {
    "birthday",
    "anniversary",
    "born",
    "date_of_birth",
    "dob",
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
_RECURRING_KEYS = {"birthday", "anniversary", "born", "date_of_birth", "dob"}


def _parse_date(value: object) -> date | None:
    if isinstance(value, str):
        m = _DATE_RE.search(value)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def _days_until_recurring(target: date, today: date) -> int:
    this_year = today.replace(month=target.month, day=target.day)
    if this_year >= today:
        return (this_year - today).days
    return (today.replace(year=today.year + 1, month=target.month, day=target.day) - today).days


def _week_bounds(ref: date | None = None) -> tuple[date, date]:
    """Return (week_start, week_end) for the current ISO week (Mon–Sun)."""
    today = ref or date.today()
    week_start = today - timedelta(days=today.weekday())  # Monday
    week_end = week_start + timedelta(days=6)  # Sunday
    return week_start, week_end


def generate_weekly_briefing(
    user_id: str,
    week_start: date | None = None,
) -> WeeklyBriefingContent:
    """Generate a weekly digest for the given user and week."""
    ws, we = _week_bounds(week_start)
    today = date.today()
    week_start_str = ws.isoformat()
    week_end_str = we.isoformat()

    # Lookback window: things updated between week_start and now
    lookback_start = ws.isoformat()
    lookback_end = (today + timedelta(days=1)).isoformat()  # inclusive of today

    completed: list[WeeklyBriefingItem] = []
    upcoming: list[WeeklyBriefingItem] = []
    new_connections: list[WeeklyBriefingConnection] = []
    preferences_learned: list[str] = []
    open_questions: list[WeeklyBriefingItem] = []

    with Session(_engine_mod.engine) as session:
        # Completed items: active=false, updated in lookback window
        completed_stmt = (
            select(ThingRecord)
            .where(
                ~ThingRecord.active,
                ThingRecord.updated_at >= lookback_start,
                ThingRecord.updated_at < lookback_end,
                user_filter_clause(ThingRecord.user_id, user_id),
            )
            .order_by(ThingRecord.updated_at.desc())  # type: ignore[union-attr]
            .limit(20)
        )
        completed_rows = session.exec(completed_stmt).all()

        # All active things (for upcoming deadlines and open questions)
        active_stmt = select(ThingRecord).where(
            ThingRecord.active,
            user_filter_clause(ThingRecord.user_id, user_id),
        )
        active_rows = session.exec(active_stmt).all()

        # New connections created in lookback window
        FromThing = aliased(ThingRecord)
        ToThing = aliased(ThingRecord)
        conn_stmt = (
            select(
                ThingRelationshipRecord.from_thing_id,
                ThingRelationshipRecord.to_thing_id,
                ThingRelationshipRecord.relationship_type,
                FromThing.title.label("from_title"),  # type: ignore[union-attr]
                ToThing.title.label("to_title"),  # type: ignore[union-attr]
            )
            .join(FromThing, ThingRelationshipRecord.from_thing_id == FromThing.id)  # type: ignore[union-attr]
            .join(ToThing, ThingRelationshipRecord.to_thing_id == ToThing.id)  # type: ignore[union-attr]
            .where(
                ThingRelationshipRecord.created_at >= lookback_start,
                ThingRelationshipRecord.created_at < lookback_end,
            )
            .limit(10)
        )
        conn_rows = session.execute(conn_stmt).all()

        # Preferences learned: preference Things updated/created in lookback window
        pref_stmt = (
            select(ThingRecord)
            .where(
                ThingRecord.type_hint == "preference",
                or_(
                    ThingRecord.updated_at >= lookback_start,
                    ThingRecord.created_at >= lookback_start,
                ),
                user_filter_clause(ThingRecord.user_id, user_id),
            )
            .order_by(ThingRecord.updated_at.desc())  # type: ignore[union-attr]
            .limit(10)
        )
        pref_rows = session.exec(pref_stmt).all()

    # Build completed list
    for rec in completed_rows:
        updated = rec.updated_at or ""
        detail = None
        d = _parse_date(str(updated))
        if d:
            detail = f"Completed {d.strftime('%a')}"
        completed.append(
            WeeklyBriefingItem(
                thing_id=rec.id,
                title=rec.title,
                type_hint=rec.type_hint,
                detail=detail,
            )
        )

    # Build upcoming deadlines
    for rec in active_rows:
        data: dict | None = None
        if rec.data:
            try:
                data = json.loads(rec.data) if isinstance(rec.data, str) else rec.data
            except (json.JSONDecodeError, TypeError):
                pass

        if isinstance(data, dict):
            for key, value in data.items():
                key_lower = key.lower().replace(" ", "_")
                if key_lower not in _ALL_DATE_KEYS:
                    continue
                parsed = _parse_date(value)
                if parsed is None:
                    continue
                if key_lower in _RECURRING_KEYS:
                    days = _days_until_recurring(parsed, today)
                else:
                    days = (parsed - today).days
                    if days < 0:
                        continue
                if days > 7:
                    continue
                label = key_lower.replace("_", " ").title()
                if days == 0:
                    detail = f"{label} today"
                elif days == 1:
                    detail = f"{label} tomorrow"
                else:
                    detail = f"{label} in {days}d"
                upcoming.append(
                    WeeklyBriefingItem(
                        thing_id=rec.id,
                        title=rec.title,
                        type_hint=rec.type_hint,
                        detail=detail,
                    )
                )
                break  # one deadline per thing

        # Also check checkin_date as upcoming
        checkin_str = rec.checkin_date
        if checkin_str:
            checkin = _parse_date(str(checkin_str))
            if checkin and 0 <= (checkin - today).days <= 7:
                # Avoid duplicates
                if not any(u.thing_id == rec.id for u in upcoming):
                    days = (checkin - today).days
                    if days == 0:
                        detail = "Check-in due today"
                    elif days == 1:
                        detail = "Check-in tomorrow"
                    else:
                        detail = f"Check-in in {days}d"
                    upcoming.append(
                        WeeklyBriefingItem(
                            thing_id=rec.id,
                            title=rec.title,
                            type_hint=rec.type_hint,
                            detail=detail,
                        )
                    )

        # Open questions
        oq_raw = rec.open_questions
        if oq_raw:
            try:
                oq = json.loads(oq_raw) if isinstance(oq_raw, str) else oq_raw
                if isinstance(oq, list) and len(oq) > 0:
                    open_questions.append(
                        WeeklyBriefingItem(
                            thing_id=rec.id,
                            title=rec.title,
                            type_hint=rec.type_hint,
                            detail=oq[0] if oq else None,
                        )
                    )
            except (json.JSONDecodeError, TypeError):
                pass

    # Build new connections list (de-duplicate by pair)
    seen_pairs: set[frozenset[str]] = set()
    for row in conn_rows:
        pair = frozenset([row.from_thing_id, row.to_thing_id])
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        new_connections.append(
            WeeklyBriefingConnection(
                from_title=row.from_title,
                to_title=row.to_title,
                relationship_type=row.relationship_type,
            )
        )

    # Build preferences learned
    for rec in pref_rows:
        preferences_learned.append(rec.title)

    # Sort upcoming by urgency
    upcoming.sort(
        key=lambda x: (
            int(x.detail.split("in ")[1].rstrip("d"))
            if x.detail and "in " in x.detail
            else (0 if x.detail and "today" in x.detail else 1)
        )
    )

    # Limit open questions
    open_questions = open_questions[:5]

    # Build summary
    parts: list[str] = []
    if completed:
        parts.append(f"{len(completed)} item{'s' if len(completed) != 1 else ''} completed")
    if upcoming:
        parts.append(f"{len(upcoming)} upcoming deadline{'s' if len(upcoming) != 1 else ''}")
    if new_connections:
        parts.append(f"{len(new_connections)} new connection{'s' if len(new_connections) != 1 else ''} discovered")
    if preferences_learned:
        parts.append(f"{len(preferences_learned)} preference{'s' if len(preferences_learned) != 1 else ''} reinforced")

    if parts:
        summary = f"This week: {', '.join(parts)}."
    else:
        summary = "A quiet week — everything is on track."

    stats = {
        "completed_count": len(completed),
        "upcoming_count": len(upcoming),
        "new_connections_count": len(new_connections),
        "preferences_count": len(preferences_learned),
        "open_questions_count": len(open_questions),
    }

    return WeeklyBriefingContent(
        summary=summary,
        week_start=week_start_str,
        week_end=week_end_str,
        completed=completed,
        upcoming=upcoming,
        new_connections=new_connections,
        preferences_learned=preferences_learned,
        open_questions=open_questions,
        stats=stats,
    )


def store_weekly_briefing(user_id: str, content: WeeklyBriefingContent) -> str:
    """Store a generated weekly briefing. Returns the briefing ID."""
    briefing_id = f"wb-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    with Session(_engine_mod.engine) as session:
        # Check for existing briefing for this user/week
        existing_stmt = select(WeeklyBriefingRecord).where(
            WeeklyBriefingRecord.week_start == content.week_start,
        )
        if user_id:
            existing_stmt = existing_stmt.where(
                WeeklyBriefingRecord.user_id == user_id,
            )
        else:
            existing_stmt = existing_stmt.where(
                WeeklyBriefingRecord.user_id.is_(None),  # type: ignore[union-attr]
            )

        existing = session.exec(existing_stmt).first()

        if existing:
            existing.id = briefing_id
            existing.content = json.loads(content.model_dump_json())
            existing.generated_at = datetime.fromisoformat(now)
            session.add(existing)
        else:
            record = WeeklyBriefingRecord(
                id=briefing_id,
                user_id=user_id or None,
                week_start=content.week_start,
                content=json.loads(content.model_dump_json()),
                generated_at=datetime.fromisoformat(now),
            )
            session.add(record)
        session.commit()

    logger.info(
        "Weekly briefing stored: %s for user %s week %s",
        briefing_id,
        user_id[:8] if user_id else "legacy",
        content.week_start,
    )
    return briefing_id


def get_latest_weekly_briefing(user_id: str, week_start: date | None = None) -> dict | None:
    """Retrieve the most recent weekly briefing for a user."""
    with Session(_engine_mod.engine) as session:
        if week_start:
            stmt = select(WeeklyBriefingRecord).where(
                WeeklyBriefingRecord.week_start == week_start.isoformat(),
                user_filter_clause(WeeklyBriefingRecord.user_id, user_id),
            )
        else:
            stmt = (
                select(WeeklyBriefingRecord)
                .where(
                    user_filter_clause(WeeklyBriefingRecord.user_id, user_id),
                )
                .order_by(WeeklyBriefingRecord.week_start.desc())  # type: ignore[union-attr]
                .limit(1)
            )

        record = session.exec(stmt).first()

    if not record:
        return None

    raw_content = record.content
    try:
        content = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
    except (json.JSONDecodeError, TypeError):
        content = {}

    return {
        "id": record.id,
        "week_start": record.week_start,
        "content": content,
        "generated_at": record.generated_at,
    }
