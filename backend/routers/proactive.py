"""Proactive surfaces — surface time-relevant entities in the sidebar."""

import json
import re
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..auth import require_user, user_filter
from ..database import db
from ..models import ProactiveSurface
from .things import _row_to_thing

router = APIRouter(prefix="/proactive", tags=["proactive"])

# Keys in the data JSON that hold date values.
# Recurring: the year is ignored; we match on month/day each year.
_RECURRING_KEYS = {"birthday", "anniversary", "born", "date_of_birth", "dob"}
# One-shot: matched exactly (must be in the future or within window).
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

# Human-friendly labels for date keys.
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

# Regex to extract a date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS...) from a string.
_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _parse_date_value(value: object) -> date | None:
    """Try to extract a calendar date from a JSON value."""
    if isinstance(value, str):
        m = _DATE_RE.search(value)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def _days_until_next_occurrence(target: date, today: date) -> int:
    """Days until the next month/day occurrence (recurring, ignores year)."""
    this_year = today.replace(year=today.year, month=target.month, day=target.day)
    if this_year >= today:
        return (this_year - today).days
    next_year = today.replace(year=today.year + 1, month=target.month, day=target.day)
    return (next_year - today).days


def _format_reason(label: str, days: int) -> str:
    if days == 0:
        return f"{label} today"
    if days == 1:
        return f"{label} tomorrow"
    return f"{label} in {days}d"


def _scan_data(data: dict, today: date, window: int) -> list[tuple[str, str, int]]:
    """Scan a Thing's data dict for upcoming dates.

    Returns list of (date_key, reason, days_away) tuples.
    """
    hits: list[tuple[str, str, int]] = []
    for key, value in data.items():
        key_lower = key.lower().replace(" ", "_")
        if key_lower not in _ALL_DATE_KEYS:
            continue
        parsed = _parse_date_value(value)
        if parsed is None:
            continue
        label = _KEY_LABELS.get(key_lower, key.replace("_", " ").title())
        if key_lower in _RECURRING_KEYS:
            days = _days_until_next_occurrence(parsed, today)
        else:
            days = (parsed - today).days
            if days < 0:
                continue  # past one-shot dates aren't surfaced
        if days <= window:
            hits.append((key, _format_reason(label, days), days))
    return hits


@router.get("", response_model=list[ProactiveSurface], summary="Proactive Surfaces")
def get_proactive_surfaces(
    days: int = Query(7, ge=0, le=90, description="Look-ahead window in days"),
    user_id: str = Depends(require_user),
) -> list[ProactiveSurface]:
    """Return Things with time-relevant dates approaching within *days*."""
    today = date.today()
    uf_sql, uf_params = user_filter(user_id)

    with db() as conn:
        # Fetch all Things that have a non-null data field (entities live here).
        rows = conn.execute(
            f"SELECT * FROM things WHERE data IS NOT NULL AND data != '{{}}'  AND data != 'null'{uf_sql}",
            uf_params,
        ).fetchall()

    surfaces: list[ProactiveSurface] = []
    for row in rows:
        thing = _row_to_thing(row)
        if thing.data is None:
            continue
        hits = _scan_data(thing.data, today, days)
        for date_key, reason, days_away in hits:
            surfaces.append(
                ProactiveSurface(
                    thing=thing,
                    reason=reason,
                    date_key=date_key,
                    days_away=days_away,
                )
            )

    # Sort: soonest first, then alphabetically by title.
    surfaces.sort(key=lambda s: (s.days_away, s.thing.title))
    return surfaces


class NudgeDismissRequest(BaseModel):
    thing_id: str
    nudge_type: str = "general"


@router.post("/stop", summary="Stop nudges for a thing")
def stop_nudge(
    body: NudgeDismissRequest,
    user_id: str = Depends(require_user),
) -> dict:
    """Create a negative preference signal to stop nudges for a thing."""
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        # Check if there's already a "stop nudge" preference for this thing
        existing = conn.execute(
            "SELECT id, data FROM things WHERE type_hint = 'preference' AND user_id = ? AND title LIKE ?",
            (user_id, f"%nudge%{body.thing_id}%"),
        ).fetchone()

        if existing:
            # Strengthen the negative signal
            try:
                data = json.loads(existing["data"]) if isinstance(existing["data"], str) else existing["data"] or {}
            except Exception:
                data = {}
            data["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0.7)) + 0.1))
            data["updated_at"] = now
            conn.execute(
                "UPDATE things SET data = ?, updated_at = ? WHERE id = ?",
                (json.dumps(data), now, existing["id"]),
            )
        else:
            # Create a new negative preference
            pref_id = str(uuid.uuid4())
            data = {
                "category": "notifications",
                "confidence": 0.7,
                "negative": True,
                "thing_id": body.thing_id,
                "nudge_type": body.nudge_type,
                "evidence": [{"note": "user dismissed nudge", "at": now}],
            }
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface, data, created_at, updated_at, user_id) "
                "VALUES (?, ?, 'preference', 3, 1, 0, ?, ?, ?, ?)",
                (pref_id, f"Prefers no nudges about this item ({body.nudge_type})", json.dumps(data), now, now, user_id),
            )
    return {"ok": True}
