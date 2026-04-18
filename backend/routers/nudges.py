"""Proactive nudge delivery — surfaces time-sensitive insights with daily limits.

GET  /nudges         → today's active nudges (max 3, respects dismissals/suppressions)
POST /nudges/{id}/dismiss → mark nudge as dismissed for today
POST /nudges/{id}/stop    → suppress this nudge type permanently (preference signal)
"""

import json
import logging
import re
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import String, cast
from sqlmodel import Session, select

from ..auth import require_user
import backend.db_engine as _engine_mod
from ..db_engine import user_filter_clause
from ..db_models import NudgeDismissalRecord, NudgeSuppressionRecord, ThingRecord
from ..models import Nudge
from .things import _record_to_thing

router = APIRouter(prefix="/nudges", tags=["nudges"])
logger = logging.getLogger(__name__)

DAILY_NUDGE_LIMIT = 3

# Keys in the data JSON that hold date values (mirrors proactive.py).
# recurring=True means the date repeats yearly (e.g. birthday).
_DATE_KEY_CONFIG: dict[str, tuple[bool, str]] = {
    "birthday":     (True,  "Birthday"),
    "anniversary":  (True,  "Anniversary"),
    "born":         (True,  "Birthday"),
    "date_of_birth":(True,  "Birthday"),
    "dob":          (True,  "Birthday"),
    "deadline":     (False, "Deadline"),
    "due_date":     (False, "Due"),
    "due":          (False, "Due"),
    "event_date":   (False, "Event"),
    "starts_at":    (False, "Starts"),
    "start_date":   (False, "Starts"),
    "ends_at":      (False, "Ends"),
    "end_date":     (False, "Ends"),
    "date":         (False, "Date"),
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


def _build_nudge_from_surface(record: ThingRecord, date_key: str, reason: str, days: int) -> Nudge:
    thing = _record_to_thing(record)
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

    with Session(_engine_mod.engine) as session:
        # Dismissed nudge IDs for today
        dismissed_records = session.exec(
            select(NudgeDismissalRecord).where(
                NudgeDismissalRecord.user_id == user_id,
                NudgeDismissalRecord.dismissed_date == today_str,
            )
        ).all()
        dismissed_ids = {r.nudge_id for r in dismissed_records}

        # Suppressed nudge types
        suppressed_records = session.exec(
            select(NudgeSuppressionRecord).where(
                NudgeSuppressionRecord.user_id == user_id,
            )
        ).all()
        suppressed_types = {r.nudge_type for r in suppressed_records}

        # Fetch things with non-empty data
        thing_stmt = (
            select(ThingRecord)
            .where(
                ThingRecord.data.is_not(None),  # type: ignore[union-attr]
                cast(ThingRecord.data, String) != '{}',
                cast(ThingRecord.data, String) != 'null',
                ThingRecord.active == True,
                user_filter_clause(ThingRecord.user_id, user_id),
            )
        )
        thing_records = session.exec(thing_stmt).all()

    nudges: list[Nudge] = []
    for record in thing_records:
        if "approaching_date" in suppressed_types:
            break
        data = record.data
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (ValueError, TypeError):
                continue
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            key_lower = key.lower().replace(" ", "_")
            key_config = _DATE_KEY_CONFIG.get(key_lower)
            if key_config is None:
                continue
            parsed = _parse_date(value)
            if parsed is None:
                continue
            is_recurring, label = key_config
            if is_recurring:
                days = _days_until_recurring(parsed, today)
            else:
                days = (parsed - today).days
                if days < 0:
                    continue
            if days > 7:
                continue
            if days == 0:
                reason = f"{label} today"
            elif days == 1:
                reason = f"{label} tomorrow"
            else:
                reason = f"{label} in {days}d"
            nudge = _build_nudge_from_surface(record, key_lower, reason, days)
            if nudge.id not in dismissed_ids:
                nudges.append(nudge)

    # Sort: soonest first
    nudges.sort(key=lambda n: (n.days_away if n.days_away is not None else 999, n.thing_title or ""))

    return nudges[:DAILY_NUDGE_LIMIT]


@router.post("/{nudge_id}/dismiss", summary="Dismiss a nudge for today")
def dismiss_nudge(nudge_id: str, user_id: str = Depends(require_user)) -> dict:
    """Dismiss a nudge — it won't reappear today."""
    today_str = date.today().isoformat()
    with Session(_engine_mod.engine) as session:
        # Check if already dismissed (equivalent to INSERT OR IGNORE)
        existing = session.exec(
            select(NudgeDismissalRecord).where(
                NudgeDismissalRecord.user_id == user_id,
                NudgeDismissalRecord.nudge_id == nudge_id,
                NudgeDismissalRecord.dismissed_date == today_str,
            )
        ).first()
        if not existing:
            session.add(NudgeDismissalRecord(
                user_id=user_id,
                nudge_id=nudge_id,
                dismissed_date=today_str,
            ))
            session.commit()
    return {"ok": True}


_PREFIX_TO_NUDGE_TYPE: dict[str, str] = {
    "proactive": "approaching_date",
}

_NUDGE_TYPE_TO_PREF_TITLE: dict[str, str] = {
    "approaching_date": "Prefers fewer date-based reminders",
}


def _conf_label(conf: float) -> str:
    """Map a confidence float (0–1) to a display label.

    >=0.7 → "strong", >=0.5 → "moderate", <0.5 → "emerging".
    """
    if conf >= 0.7:
        return "strong"
    if conf >= 0.5:
        return "moderate"
    return "emerging"



@router.post("/{nudge_id}/stop", summary="Stop nudges of this type (preference signal)")
def stop_nudge_type(nudge_id: str, user_id: str = Depends(require_user)) -> dict:
    """Suppress all nudges of this type and record a negative preference signal."""
    # Extract nudge_type from nudge_id (format: "{type}_{thing_id}_{key}")
    prefix = nudge_id.split("_")[0] if "_" in nudge_id else nudge_id
    nudge_type = "approaching_date" if prefix == "proactive" else prefix

    today_str = date.today().isoformat()
    with Session(_engine_mod.engine) as session:
        # Record suppression (equivalent to INSERT OR IGNORE)
        existing_suppression = session.exec(
            select(NudgeSuppressionRecord).where(
                NudgeSuppressionRecord.user_id == user_id,
                NudgeSuppressionRecord.nudge_type == nudge_type,
            )
        ).first()
        if not existing_suppression:
            session.add(NudgeSuppressionRecord(
                user_id=user_id,
                nudge_type=nudge_type,
            ))

        # Also dismiss for today
        existing_dismissal = session.exec(
            select(NudgeDismissalRecord).where(
                NudgeDismissalRecord.user_id == user_id,
                NudgeDismissalRecord.nudge_id == nudge_id,
                NudgeDismissalRecord.dismissed_date == today_str,
            )
        ).first()
        if not existing_dismissal:
            session.add(NudgeDismissalRecord(
                user_id=user_id,
                nudge_id=nudge_id,
                dismissed_date=today_str,
            ))

        session.commit()

        # Create or update a preference Thing for this nudge type
        pref_title = _NUDGE_TYPE_TO_PREF_TITLE.get(nudge_type)
        preference_data = None
        if pref_title:
            try:
                existing_pref = session.exec(
                    select(ThingRecord).where(
                        ThingRecord.type_hint == "preference",
                        ThingRecord.title == pref_title,
                        user_filter_clause(ThingRecord.user_id, user_id),
                    )
                ).first()

                now_dt = datetime.now(timezone.utc)
                now_str = now_dt.isoformat()

                if existing_pref:
                    # Update existing preference
                    data = existing_pref.data
                    if isinstance(data, str):
                        try:
                            data = json.loads(data)
                        except (ValueError, TypeError):
                            data = {}
                    if not isinstance(data, dict):
                        data = {}
                    evidence = data.get("evidence") if isinstance(data.get("evidence"), list) else []
                    evidence.append(f"User stopped '{nudge_type}' nudge type ({today_str})")
                    evidence = evidence[-10:]  # cap at 10
                    new_conf = min(data.get("confidence", 0.5) + 0.1, 0.95)
                    data["confidence"] = new_conf
                    data["evidence"] = evidence
                    data["sweep_count"] = data.get("sweep_count", 0) + 1
                    data["last_sweep"] = now_str
                    existing_pref.data = data  # type: ignore[assignment]
                    existing_pref.updated_at = now_dt
                    session.commit()
                    preference_data = {
                        "id": existing_pref.id,
                        "title": existing_pref.title,
                        "confidence_label": _conf_label(new_conf),
                        "action": "updated",
                    }
                else:
                    # Create new preference
                    thing_id = f"pref-{uuid.uuid4().hex[:8]}"
                    confidence = 0.6
                    pref_thing_data = {
                        "confidence": confidence,
                        "evidence": [f"User stopped '{nudge_type}' nudge type ({today_str})"],
                        "category": "productivity",
                        "last_sweep": now_str,
                        "sweep_count": 1,
                    }
                    new_thing = ThingRecord(
                        id=thing_id,
                        title=pref_title,
                        type_hint="preference",
                        importance=2,
                        active=True,
                        surface=False,
                        data=pref_thing_data,
                        created_at=now_dt,
                        updated_at=now_dt,
                        user_id=user_id or None,
                    )
                    session.add(new_thing)
                    session.commit()
                    preference_data = {
                        "id": thing_id,
                        "title": pref_title,
                        "confidence_label": _conf_label(confidence),
                        "action": "created",
                    }
            except Exception:
                logger.exception(
                    "Failed to upsert preference Thing for nudge_type=%s user=%s",
                    nudge_type, user_id,
                )

    result: dict = {"ok": True, "suppressed_type": nudge_type}
    if preference_data:
        result["preference"] = preference_data
    return result
