"""Weekly digest generation — summarises the past week for re-engagement.

Generated on Sunday evening (configurable via WEEKLY_DIGEST_DOW/HOUR env vars).
Stored per (user_id, week_start) so each week's digest is retained.

Content:
- Things completed (deactivated) this week
- Preferences learned or strengthened this week
- Upcoming items with deadlines in the next two weeks
- Open questions (active sweep findings)
- Stats summary
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from .auth import user_filter
from .database import db
from .models import WeeklyDigestContent, WeeklyDigestItem

logger = logging.getLogger(__name__)


def _week_bounds(ref: date | None = None) -> tuple[date, date]:
    """Return (monday, sunday) for the week containing *ref* (defaults to today)."""
    today = ref or date.today()
    monday = today - timedelta(days=today.weekday())  # 0=Mon
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _previous_week_bounds(ref: date | None = None) -> tuple[date, date]:
    """Return (monday, sunday) for the week before the one containing *ref*."""
    today = ref or date.today()
    monday_this = today - timedelta(days=today.weekday())
    monday_prev = monday_this - timedelta(weeks=1)
    sunday_prev = monday_prev + timedelta(days=6)
    return monday_prev, sunday_prev


def generate_weekly_digest(
    user_id: str,
    week_start: date | None = None,
) -> WeeklyDigestContent:
    """Generate a weekly digest for the given user.

    If *week_start* is omitted, summarises the most recently completed week
    (Monday–Sunday ending yesterday-or-earlier).
    """
    if week_start is None:
        monday, sunday = _previous_week_bounds()
    else:
        monday = week_start
        sunday = monday + timedelta(days=6)

    week_start_str = monday.isoformat()
    week_end_str = sunday.isoformat()

    # Window strings for SQL comparisons
    window_start = f"{week_start_str}T00:00:00"
    window_end = f"{week_end_str}T23:59:59"
    upcoming_cutoff = (date.today() + timedelta(days=14)).isoformat()

    uf_sql, uf_params = user_filter(user_id)

    completed_items: list[WeeklyDigestItem] = []
    preferences_learned: list[WeeklyDigestItem] = []
    upcoming_items: list[WeeklyDigestItem] = []
    open_questions: list[str] = []

    with db() as conn:
        # Things deactivated (completed) during the week
        completed_rows = conn.execute(
            f"""SELECT id, title, type_hint, updated_at FROM things
               WHERE active = 0
                 AND updated_at >= ?
                 AND updated_at <= ?{uf_sql}
               ORDER BY updated_at DESC
               LIMIT 20""",
            [window_start, window_end, *uf_params],
        ).fetchall()

        # Preference Things created or updated this week
        pref_rows = conn.execute(
            f"""SELECT id, title, updated_at FROM things
               WHERE type_hint = 'preference'
                 AND active = 1
                 AND updated_at >= ?
                 AND updated_at <= ?{uf_sql}
               ORDER BY updated_at DESC
               LIMIT 10""",
            [window_start, window_end, *uf_params],
        ).fetchall()

        # Upcoming items: active things with a deadline in the next 14 days
        upcoming_rows = conn.execute(
            f"""SELECT id, title, type_hint, checkin_date, data FROM things
               WHERE active = 1
                 AND checkin_date IS NOT NULL
                 AND checkin_date >= ?
                 AND checkin_date <= ?{uf_sql}
               ORDER BY checkin_date ASC
               LIMIT 10""",
            [date.today().isoformat(), upcoming_cutoff, *uf_params],
        ).fetchall()

        # Open questions: non-dismissed sweep findings
        now = datetime.now(timezone.utc).isoformat()
        sf_uf_sql, sf_uf_params = user_filter(user_id, "sf")
        question_rows = conn.execute(
            f"""SELECT sf.message FROM sweep_findings sf
               WHERE sf.dismissed = 0
                 AND (sf.expires_at IS NULL OR sf.expires_at > ?)
                 AND (sf.snoozed_until IS NULL OR sf.snoozed_until <= ?){sf_uf_sql}
               ORDER BY sf.priority ASC, sf.created_at DESC
               LIMIT 5""",
            [now, now, *sf_uf_params],
        ).fetchall()

    for r in completed_rows:
        completed_items.append(WeeklyDigestItem(thing_id=r["id"], title=r["title"]))

    for r in pref_rows:
        # Try to extract a short note from the data field
        preferences_learned.append(WeeklyDigestItem(thing_id=r["id"], title=r["title"]))

    for r in upcoming_rows:
        checkin = r["checkin_date"]
        note = None
        if checkin:
            try:
                d = date.fromisoformat(str(checkin)[:10])
                days_away = (d - date.today()).days
                note = f"due in {days_away}d" if days_away > 0 else "due today"
            except (ValueError, TypeError):
                pass
        upcoming_items.append(WeeklyDigestItem(thing_id=r["id"], title=r["title"], note=note))

    for r in question_rows:
        open_questions.append(r["message"])

    # Build summary
    parts: list[str] = []
    if completed_items:
        n = len(completed_items)
        parts.append(f"{n} item{'s' if n != 1 else ''} completed")
    if preferences_learned:
        n = len(preferences_learned)
        parts.append(f"{n} preference{'s' if n != 1 else ''} learned")
    if upcoming_items:
        n = len(upcoming_items)
        parts.append(f"{n} upcoming deadline{'s' if n != 1 else ''}")
    if open_questions:
        n = len(open_questions)
        parts.append(f"{n} open question{'s' if n != 1 else ''}")

    if parts:
        summary = f"Week of {monday.strftime('%b %d')}: {', '.join(parts)}."
    else:
        summary = f"Week of {monday.strftime('%b %d')}: quiet week — nothing notable to report."

    stats = {
        "completed_count": len(completed_items),
        "preferences_count": len(preferences_learned),
        "upcoming_count": len(upcoming_items),
        "open_questions_count": len(open_questions),
    }

    return WeeklyDigestContent(
        summary=summary,
        week_start=week_start_str,
        week_end=week_end_str,
        completed=completed_items,
        preferences_learned=preferences_learned,
        upcoming=upcoming_items,
        open_questions=open_questions,
        stats=stats,
    )


def store_weekly_digest(user_id: str, content: WeeklyDigestContent) -> str:
    """Store a weekly digest. Returns the digest ID."""
    digest_id = f"wd-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    with db() as conn:
        conn.execute(
            """INSERT INTO weekly_digests (id, user_id, week_start, content, generated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id, week_start) DO UPDATE SET
                 id = excluded.id,
                 content = excluded.content,
                 generated_at = excluded.generated_at""",
            (digest_id, user_id or None, content.week_start, content.model_dump_json(), now),
        )

    logger.info("Weekly digest stored: %s for user %s week %s", digest_id, user_id[:8] if user_id else "legacy", content.week_start)
    return digest_id


def get_latest_weekly_digest(user_id: str, week_start: date | None = None) -> dict | None:
    """Retrieve a weekly digest.

    If *week_start* is provided, returns the digest for that specific week.
    Otherwise returns the most recent digest.
    """
    uf_sql, uf_params = user_filter(user_id)

    with db() as conn:
        if week_start:
            row = conn.execute(
                f"""SELECT * FROM weekly_digests
                   WHERE week_start = ?{uf_sql}""",
                [week_start.isoformat(), *uf_params],
            ).fetchone()
        else:
            row = conn.execute(
                f"""SELECT * FROM weekly_digests
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
