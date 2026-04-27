"""Morning briefing generation — pre-generates a structured briefing during nightly sweep.

Aggregates priorities (from focus scoring), overdue items, blockers, and sweep
findings into a single stored briefing for the user's next session.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime, timezone

from sqlmodel import Session, or_, select

import backend.db_engine as _engine_mod

from .db_engine import user_filter_clause
from .db_models import (
    MorningBriefingRecord,
    SweepFindingRecord,
    ThingRecord,
    ThingRelationshipRecord,
    UserSettingRecord,
)
from .models import (
    BriefingPreferences,
    MorningBriefingContent,
    MorningBriefingFinding,
    MorningBriefingItem,
)

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
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


def get_briefing_preferences(user_id: str) -> BriefingPreferences:
    """Load briefing preferences from user_settings, or return defaults."""
    if not user_id:
        return BriefingPreferences()

    with Session(_engine_mod.engine) as session:
        stmt = select(UserSettingRecord).where(
            UserSettingRecord.user_id == user_id,
            UserSettingRecord.key == "briefing_preferences",
        )
        row = session.exec(stmt).first()

    if not row or not row.value:
        return BriefingPreferences()

    try:
        data = json.loads(row.value)
        return BriefingPreferences(**data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return BriefingPreferences()


def save_briefing_preferences(user_id: str, prefs: BriefingPreferences) -> None:
    """Save briefing preferences to user_settings."""
    if not user_id:
        return  # No user to save for (legacy single-user mode)
    now = datetime.now(timezone.utc)
    with Session(_engine_mod.engine) as session:
        existing = session.exec(
            select(UserSettingRecord).where(
                UserSettingRecord.user_id == user_id,
                UserSettingRecord.key == "briefing_preferences",
            )
        ).first()
        if existing:
            existing.value = prefs.model_dump_json()
            existing.updated_at = now
            session.add(existing)
        else:
            record = UserSettingRecord(
                user_id=user_id,
                key="briefing_preferences",
                value=prefs.model_dump_json(),
                updated_at=now,
            )
            session.add(record)
        session.commit()


def generate_morning_briefing(
    user_id: str,
    target_date: date | None = None,
) -> MorningBriefingContent:
    """Generate a morning briefing for the given user and date.

    Aggregates:
    - Top priorities (scored like the focus endpoint)
    - Overdue items (past deadline or checkin date)
    - Blockers (things blocked by dependencies)
    - Active sweep findings
    """
    today = target_date or date.today()
    prefs = get_briefing_preferences(user_id)

    priorities: list[MorningBriefingItem] = []
    overdue: list[MorningBriefingItem] = []
    blockers: list[MorningBriefingItem] = []
    findings_list: list[MorningBriefingFinding] = []

    with Session(_engine_mod.engine) as session:
        # Fetch active things
        thing_stmt = (
            select(ThingRecord)
            .where(
                ThingRecord.active == True,
                user_filter_clause(ThingRecord.user_id, user_id),
            )
            .order_by(ThingRecord.importance.asc(), ThingRecord.updated_at.desc())
        )  # type: ignore[union-attr]
        thing_rows = session.exec(thing_stmt).all()

        # Fetch relationships for blocking analysis
        rel_rows = session.exec(select(ThingRelationshipRecord)).all()

        # Fetch active sweep findings (with thing title via join)
        now_dt = datetime.now(timezone.utc)
        finding_stmt = (
            select(
                SweepFindingRecord.id,
                SweepFindingRecord.message,
                SweepFindingRecord.priority,
                SweepFindingRecord.thing_id,
                ThingRecord.title.label("thing_title"),  # type: ignore[union-attr]
            )
            .outerjoin(ThingRecord, SweepFindingRecord.thing_id == ThingRecord.id)
            .where(
                SweepFindingRecord.dismissed == False,
                or_(SweepFindingRecord.expires_at.is_(None), SweepFindingRecord.expires_at > now_dt),  # type: ignore[union-attr]
                or_(SweepFindingRecord.snoozed_until.is_(None), SweepFindingRecord.snoozed_until <= now_dt),  # type: ignore[union-attr]
                user_filter_clause(SweepFindingRecord.user_id, user_id),
                or_(SweepFindingRecord.thing_id.is_(None), ThingRecord.active == True),  # type: ignore[union-attr]
            )
            .order_by(SweepFindingRecord.priority.asc(), SweepFindingRecord.created_at.desc())  # type: ignore[union-attr]
        )
        finding_rows = session.execute(finding_stmt).fetchall()

    # Build thing map
    thing_map: dict[str, dict] = {}
    for r in thing_rows:
        thing_map[r.id] = r.model_dump()

    active_ids = set(thing_map.keys())

    # Build blocking graph
    blocked_by: dict[str, set[str]] = {}
    blocks: dict[str, set[str]] = {}
    for rel in rel_rows:
        rtype = rel.relationship_type
        from_id = rel.from_thing_id
        to_id = rel.to_thing_id
        if rtype == "depends-on":
            if from_id in active_ids and to_id in active_ids:
                blocked_by.setdefault(from_id, set()).add(to_id)
                blocks.setdefault(to_id, set()).add(from_id)
        elif rtype == "blocks":
            if from_id in active_ids and to_id in active_ids:
                blocked_by.setdefault(to_id, set()).add(from_id)
                blocks.setdefault(from_id, set()).add(to_id)

    # Non-actionable types
    skip_types = {"person", "place", "concept", "reference"}

    # Score things and find overdue/blockers
    scored: list[tuple[float, str, str, list[str]]] = []

    for tid, t in thing_map.items():
        type_hint = t.get("type_hint")
        if type_hint in skip_types:
            continue

        title = t["title"]
        importance = t.get("importance", 2)
        score = 0.0
        reasons: list[str] = []

        # Importance boost
        importance_boost = (4 - importance) * 25
        score += importance_boost
        if importance <= 1:
            reasons.append(f"High importance ({importance})")

        # Deadline urgency
        data_raw = t.get("data")
        data = None
        if data_raw:
            try:
                data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
            except (json.JSONDecodeError, TypeError):
                pass

        deadline = _earliest_deadline(data if isinstance(data, dict) else None)
        if deadline:
            days_until = (deadline - today).days
            if days_until < 0:
                score += 150
                reasons.append(f"Overdue by {abs(days_until)}d")
                if prefs.include_overdue:
                    overdue.append(
                        MorningBriefingItem(
                            thing_id=tid,
                            title=title,
                            days_overdue=abs(days_until),
                            reasons=[f"Deadline overdue by {abs(days_until)}d"],
                        )
                    )
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

        # Checkin date urgency
        checkin_str = t.get("checkin_date")
        if checkin_str:
            checkin = _parse_date(str(checkin_str))
            if checkin:
                days_until_checkin = (checkin - today).days
                if days_until_checkin < 0:
                    score += 90
                    reasons.append(f"Check-in overdue by {abs(days_until_checkin)}d")
                    if prefs.include_overdue and not any(o.thing_id == tid for o in overdue):
                        overdue.append(
                            MorningBriefingItem(
                                thing_id=tid,
                                title=title,
                                days_overdue=abs(days_until_checkin),
                                reasons=[f"Check-in overdue by {abs(days_until_checkin)}d"],
                            )
                        )
                elif days_until_checkin == 0:
                    score += 90
                    reasons.append("Check-in due today")

        # Unblocks others
        if tid in blocks:
            unblocks_count = len(blocks[tid])
            score += unblocks_count * 30
            reasons.append(f"Unblocks {unblocks_count} item{'s' if unblocks_count != 1 else ''}")

        # Blocked
        is_blocked = tid in blocked_by
        if is_blocked:
            score -= 80
            blocker_titles = [thing_map[bid]["title"] for bid in blocked_by[tid] if bid in thing_map]
            if prefs.include_blockers:
                blockers.append(
                    MorningBriefingItem(
                        thing_id=tid,
                        title=title,
                        blocked_by=blocker_titles[:3],
                        reasons=["Blocked by dependencies"],
                    )
                )

        # Staleness
        updated_at = t.get("updated_at")
        if updated_at:
            up_date = _parse_date(str(updated_at))
            if up_date:
                stale_days = (today - up_date).days
                if stale_days >= 30:
                    score += 25
                    reasons.append(f"Untouched for {stale_days}d")
                elif stale_days >= 14:
                    score += 15
                    reasons.append(f"Untouched for {stale_days}d")

        # Type adjustments
        if type_hint == "task":
            score += 5
        elif type_hint == "goal":
            score += 3

        if score > 0 and reasons:
            scored.append((score, tid, title, reasons))

    # Sort by score descending and take top N priorities
    scored.sort(key=lambda x: -x[0])
    if prefs.include_priorities:
        for score_val, tid, title, reasons in scored[: prefs.max_priorities]:
            priorities.append(
                MorningBriefingItem(
                    thing_id=tid,
                    title=title,
                    score=round(score_val, 1),
                    reasons=reasons,
                )
            )

    # Collect findings
    if prefs.include_findings:
        for r in finding_rows[: prefs.max_findings]:
            findings_list.append(
                MorningBriefingFinding(
                    id=r.id,
                    message=r.message,
                    priority=r.priority,
                    thing_id=r.thing_id,
                    thing_title=r.thing_title,
                )
            )

    # Build summary
    parts = []
    if priorities:
        parts.append(f"{len(priorities)} top priorit{'y' if len(priorities) == 1 else 'ies'}")
    if overdue:
        parts.append(f"{len(overdue)} overdue item{'s' if len(overdue) != 1 else ''}")
    if blockers:
        parts.append(f"{len(blockers)} blocked item{'s' if len(blockers) != 1 else ''}")
    if findings_list:
        parts.append(f"{len(findings_list)} sweep finding{'s' if len(findings_list) != 1 else ''}")

    if parts:
        summary = f"Good morning! You have {', '.join(parts)}."
    else:
        summary = "Good morning! Everything looks clear today."

    stats = {
        "total_active": len([t for t in thing_map.values() if t.get("type_hint") not in skip_types]),
        "priorities_count": len(priorities),
        "overdue_count": len(overdue),
        "blockers_count": len(blockers),
        "findings_count": len(findings_list),
    }

    return MorningBriefingContent(
        summary=summary,
        priorities=priorities,
        overdue=overdue,
        blockers=blockers,
        findings=findings_list,
        stats=stats,
    )


def store_morning_briefing(user_id: str, content: MorningBriefingContent, briefing_date: date | None = None) -> str:
    """Store a generated morning briefing in the database. Returns the briefing ID."""
    today = briefing_date or date.today()
    briefing_id = f"mb-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    with Session(_engine_mod.engine) as session:
        # Upsert: check if briefing for this user+date exists
        uid = user_id or None
        stmt = select(MorningBriefingRecord).where(
            MorningBriefingRecord.briefing_date == today.isoformat(),
        )
        if uid is None:
            stmt = stmt.where(MorningBriefingRecord.user_id.is_(None))  # type: ignore[union-attr]
        else:
            stmt = stmt.where(MorningBriefingRecord.user_id == uid)
        existing = session.exec(stmt).first()

        if existing:
            existing.id = briefing_id
            existing.content = json.loads(content.model_dump_json())
            existing.generated_at = datetime.fromisoformat(now)
            session.add(existing)
        else:
            record = MorningBriefingRecord(
                id=briefing_id,
                user_id=uid,
                briefing_date=today.isoformat(),
                content=json.loads(content.model_dump_json()),
                generated_at=datetime.fromisoformat(now),
            )
            session.add(record)
        session.commit()

    logger.info(
        "Morning briefing stored: %s for user %s on %s", briefing_id, user_id[:8] if user_id else "legacy", today
    )
    return briefing_id


def get_latest_morning_briefing(user_id: str, as_of: date | None = None) -> dict | None:
    """Retrieve the most recent morning briefing for a user.

    If as_of is specified, returns the briefing for that specific date.
    Otherwise, returns the most recent briefing.
    """
    with Session(_engine_mod.engine) as session:
        stmt = select(MorningBriefingRecord).where(
            user_filter_clause(MorningBriefingRecord.user_id, user_id),
        )
        if as_of:
            stmt = stmt.where(MorningBriefingRecord.briefing_date == as_of.isoformat())
        else:
            stmt = stmt.order_by(MorningBriefingRecord.briefing_date.desc()).limit(1)  # type: ignore[union-attr]
        row = session.exec(stmt).first()

    if not row:
        return None

    content = row.content if isinstance(row.content, dict) else {}

    # If stored content is missing required fields, discard it so the caller
    # regenerates a fresh briefing instead of raising a ValidationError.
    if "summary" not in content:
        return None

    return {
        "id": row.id,
        "briefing_date": row.briefing_date,
        "content": content,
        "generated_at": row.generated_at,
    }
