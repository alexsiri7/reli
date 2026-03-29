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

from .auth import user_filter
from .database import db
from .models import (
    WeeklyBriefing,
    WeeklyBriefingConnection,
    WeeklyBriefingContent,
    WeeklyBriefingItem,
)

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_ALL_DATE_KEYS = {
    "birthday", "anniversary", "born", "date_of_birth", "dob",
    "deadline", "due_date", "due", "event_date",
    "starts_at", "start_date", "ends_at", "end_date", "date",
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

    # Forward window: upcoming dates in the next 7 days
    upcoming_cutoff = today + timedelta(days=7)

    uf_sql, uf_params = user_filter(user_id)

    completed: list[WeeklyBriefingItem] = []
    upcoming: list[WeeklyBriefingItem] = []
    new_connections: list[WeeklyBriefingConnection] = []
    preferences_learned: list[str] = []
    open_questions: list[WeeklyBriefingItem] = []

    with db() as conn:
        # Completed items: active=0, updated in lookback window
        completed_rows = conn.execute(
            f"""SELECT id, title, type_hint, updated_at
               FROM things
               WHERE active = 0
                 AND updated_at >= ?
                 AND updated_at < ?{uf_sql}
               ORDER BY updated_at DESC
               LIMIT 20""",
            [lookback_start, lookback_end, *uf_params],
        ).fetchall()

        # All active things (for upcoming deadlines and open questions)
        active_rows = conn.execute(
            f"""SELECT id, title, type_hint, data, open_questions, checkin_date
               FROM things
               WHERE active = 1{uf_sql}""",
            uf_params,
        ).fetchall()

        # New connections created in lookback window
        conn_rows = conn.execute(
            f"""SELECT tr.from_thing_id, tr.to_thing_id, tr.relationship_type,
                      tf.title AS from_title, tt.title AS to_title
               FROM thing_relationships tr
               JOIN things tf ON tr.from_thing_id = tf.id
               JOIN things tt ON tr.to_thing_id = tt.id
               WHERE tr.created_at >= ?
                 AND tr.created_at < ?
               LIMIT 10""",
            [lookback_start, lookback_end],
        ).fetchall()

        # Preferences learned: preference Things updated/created in lookback window
        pref_rows = conn.execute(
            f"""SELECT id, title, data
               FROM things
               WHERE type_hint = 'preference'
                 AND (updated_at >= ? OR created_at >= ?){uf_sql}
               ORDER BY updated_at DESC
               LIMIT 10""",
            [lookback_start, lookback_start, *uf_params],
        ).fetchall()

    # Build completed list
    for row in completed_rows:
        updated = row["updated_at"] or ""
        detail = None
        d = _parse_date(str(updated))
        if d:
            detail = f"Completed {d.strftime('%a')}"
        completed.append(WeeklyBriefingItem(
            thing_id=row["id"],
            title=row["title"],
            type_hint=row["type_hint"],
            detail=detail,
        ))

    # Build upcoming deadlines
    for row in active_rows:
        data_raw = row["data"]
        data: dict | None = None
        if data_raw:
            try:
                data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
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
                upcoming.append(WeeklyBriefingItem(
                    thing_id=row["id"],
                    title=row["title"],
                    type_hint=row["type_hint"],
                    detail=detail,
                ))
                break  # one deadline per thing

        # Also check checkin_date as upcoming
        checkin_str = row["checkin_date"]
        if checkin_str:
            checkin = _parse_date(str(checkin_str))
            if checkin and 0 <= (checkin - today).days <= 7:
                # Avoid duplicates
                if not any(u.thing_id == row["id"] for u in upcoming):
                    days = (checkin - today).days
                    if days == 0:
                        detail = "Check-in due today"
                    elif days == 1:
                        detail = "Check-in tomorrow"
                    else:
                        detail = f"Check-in in {days}d"
                    upcoming.append(WeeklyBriefingItem(
                        thing_id=row["id"],
                        title=row["title"],
                        type_hint=row["type_hint"],
                        detail=detail,
                    ))

        # Open questions
        oq_raw = row["open_questions"]
        if oq_raw:
            try:
                oq = json.loads(oq_raw) if isinstance(oq_raw, str) else oq_raw
                if isinstance(oq, list) and len(oq) > 0:
                    open_questions.append(WeeklyBriefingItem(
                        thing_id=row["id"],
                        title=row["title"],
                        type_hint=row["type_hint"],
                        detail=oq[0] if oq else None,
                    ))
            except (json.JSONDecodeError, TypeError):
                pass

    # Build new connections list (de-duplicate by pair)
    seen_pairs: set[frozenset[str]] = set()
    for row in conn_rows:
        pair = frozenset([row["from_thing_id"], row["to_thing_id"]])
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        new_connections.append(WeeklyBriefingConnection(
            from_title=row["from_title"],
            to_title=row["to_title"],
            relationship_type=row["relationship_type"],
        ))

    # Build preferences learned
    for row in pref_rows:
        preferences_learned.append(row["title"])

    # Sort upcoming by urgency
    upcoming.sort(key=lambda x: int(x.detail.split("in ")[1].rstrip("d")) if x.detail and "in " in x.detail else (0 if x.detail and "today" in x.detail else 1))

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

    with db() as conn:
        conn.execute(
            """INSERT INTO weekly_briefings (id, user_id, week_start, content, generated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id, week_start) DO UPDATE SET
                 id = excluded.id,
                 content = excluded.content,
                 generated_at = excluded.generated_at""",
            (briefing_id, user_id or None, content.week_start, content.model_dump_json(), now),
        )

    logger.info("Weekly briefing stored: %s for user %s week %s", briefing_id, user_id[:8] if user_id else "legacy", content.week_start)
    return briefing_id


def get_latest_weekly_briefing(user_id: str, week_start: date | None = None) -> dict | None:
    """Retrieve the most recent weekly briefing for a user."""
    uf_sql, uf_params = user_filter(user_id)

    with db() as conn:
        if week_start:
            row = conn.execute(
                f"""SELECT * FROM weekly_briefings
                   WHERE week_start = ?{uf_sql}""",
                [week_start.isoformat(), *uf_params],
            ).fetchone()
        else:
            row = conn.execute(
                f"""SELECT * FROM weekly_briefings
                   WHERE 1=1{uf_sql}
                   ORDER BY week_start DESC
                   LIMIT 1""",
                uf_params,
            ).fetchone()

    if not row:
        return None

    try:
        content = json.loads(row["content"])
    except (json.JSONDecodeError, TypeError):
        content = {}

    return {
        "id": row["id"],
        "week_start": row["week_start"],
        "content": content,
        "generated_at": row["generated_at"],
    }
