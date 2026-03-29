"""Proactive nudge delivery — surfaces time-sensitive insights with daily limits.

GET  /nudges         → today's active nudges (max 3, respects dismissals/suppressions)
POST /nudges/{id}/dismiss → mark nudge as dismissed for today
POST /nudges/{id}/stop    → suppress this nudge type permanently (preference signal)
"""

import re
import sqlite3
from datetime import date

from fastapi import APIRouter, Depends

from ..auth import require_user, user_filter
from ..database import db
from ..models import Nudge
from .things import _row_to_thing

router = APIRouter(prefix="/nudges", tags=["nudges"])

DAILY_NUDGE_LIMIT = 3

# Keys in the data JSON that hold date values (mirrors proactive.py).
_RECURRING_KEYS = {"birthday", "anniversary", "born", "date_of_birth", "dob"}
_ONESHOT_KEYS = {
    "deadline", "due_date", "due", "event_date",
    "starts_at", "start_date", "ends_at", "end_date", "date",
}
_ALL_DATE_KEYS = _RECURRING_KEYS | _ONESHOT_KEYS

_KEY_LABELS: dict[str, str] = {
    "birthday": "Birthday",
    "anniversary": "Anniversary",
    "born": "Birthday",
    "date_of_birth": "Birthday",
    "dob": "Birthday",
    "deadline": "Deadline",
    "due_date": "Due",
    "due": "Due",
    "event_date": "Event",
    "starts_at": "Starts",
    "start_date": "Starts",
    "ends_at": "Ends",
    "end_date": "Ends",
    "date": "Date",
}

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


def _days_until_recurring(target: date, today: date) -> int:
    this_year = today.replace(month=target.month, day=target.day)
    if this_year >= today:
        return (this_year - today).days
    return (today.replace(year=today.year + 1, month=target.month, day=target.day) - today).days


def _build_nudge_from_surface(thing_row: sqlite3.Row, date_key: str, reason: str, days: int) -> Nudge:
    thing = _row_to_thing(thing_row)
    nudge_id = f"proactive_{thing.id}_{date_key}"
    action = None
    if thing.type_hint in ("person", "contact"):
        action = "Open contact"
    elif days <= 1:
        action = "View details"
    return Nudge(
        id=nudge_id,
        nudge_type="approaching_date",
        message=f"{thing.title}: {reason}",
        thing_id=thing.id,
        thing_title=thing.title,
        thing_type_hint=thing.type_hint,
        days_away=days,
        primary_action_label=action,
    )


@router.get("", response_model=list[Nudge], summary="Active nudges for today")
def get_nudges(user_id: str = Depends(require_user)) -> list[Nudge]:
    """Return today's proactive nudges (max 3), respecting dismissals and suppressions."""
    today = date.today()
    today_str = today.isoformat()
    uf_sql, uf_params = user_filter(user_id)

    with db() as conn:
        # Dismissed nudge IDs for today
        dismissed_rows = conn.execute(
            "SELECT nudge_id FROM nudge_dismissals WHERE user_id = ? AND dismissed_date = ?",
            (user_id, today_str),
        ).fetchall()
        dismissed_ids = {r["nudge_id"] for r in dismissed_rows}

        # Suppressed nudge types
        suppressed_rows = conn.execute(
            "SELECT nudge_type FROM nudge_suppressions WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        suppressed_types = {r["nudge_type"] for r in suppressed_rows}

        # Fetch things with upcoming dates (window: 7 days)
        rows = conn.execute(
            f"SELECT * FROM things WHERE data IS NOT NULL AND data != '{{}}' AND data != 'null' AND active = 1{uf_sql}",
            uf_params,
        ).fetchall()

    nudges: list[Nudge] = []
    for row in rows:
        if "approaching_date" in suppressed_types:
            break
        import json
        try:
            data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
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
            label = _KEY_LABELS.get(key_lower, key.replace("_", " ").title())
            if days == 0:
                reason = f"{label} today"
            elif days == 1:
                reason = f"{label} tomorrow"
            else:
                reason = f"{label} in {days}d"
            nudge = _build_nudge_from_surface(row, key_lower, reason, days)
            if nudge.id not in dismissed_ids:
                nudges.append(nudge)

    # Sort: soonest first
    nudges.sort(key=lambda n: (n.days_away if n.days_away is not None else 999, n.thing_title or ""))

    return nudges[:DAILY_NUDGE_LIMIT]


@router.post("/{nudge_id}/dismiss", summary="Dismiss a nudge for today")
def dismiss_nudge(nudge_id: str, user_id: str = Depends(require_user)) -> dict:
    """Dismiss a nudge — it won't reappear today."""
    today_str = date.today().isoformat()
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO nudge_dismissals (user_id, nudge_id, dismissed_date) VALUES (?, ?, ?)",
            (user_id, nudge_id, today_str),
        )
        conn.commit()
    return {"ok": True}


@router.post("/{nudge_id}/stop", summary="Stop nudges of this type (preference signal)")
def stop_nudge_type(nudge_id: str, user_id: str = Depends(require_user)) -> dict:
    """Suppress all nudges of this type and record a negative preference signal."""
    # Extract nudge_type from nudge_id (format: "{type}_{thing_id}_{key}")
    nudge_type = nudge_id.split("_")[0] if "_" in nudge_id else nudge_id

    with db() as conn:
        # Record suppression
        conn.execute(
            "INSERT OR IGNORE INTO nudge_suppressions (user_id, nudge_type) VALUES (?, ?)",
            (user_id, nudge_type),
        )
        # Also dismiss for today
        today_str = date.today().isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO nudge_dismissals (user_id, nudge_id, dismissed_date) VALUES (?, ?, ?)",
            (user_id, nudge_id, today_str),
        )
        conn.commit()
    return {"ok": True, "suppressed_type": nudge_type}
