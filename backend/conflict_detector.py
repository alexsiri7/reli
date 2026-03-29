"""Real-time blocker and conflict detection for Things.

Detects:
  - blocking_chain: Thing A blocks Thing B which has an approaching deadline
  - schedule_overlap: Two related Things have overlapping date ranges
  - deadline_conflict: A dependency's deadline is after its dependent's deadline
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlmodel import Session

import backend.db_engine as _engine_mod

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

# Date keys that represent deadlines/due dates
_DEADLINE_KEYS = {"deadline", "due_date", "due", "end_date", "ends_at"}
# Date keys that represent start dates
_START_KEYS = {"start_date", "starts_at", "event_date", "date"}


def _parse_date(value: object) -> date | None:
    if isinstance(value, str):
        m = _DATE_RE.search(value)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def _extract_dates(thing: dict) -> dict[str, date]:
    """Extract recognized date fields from a Thing's data JSON and checkin_date."""
    dates: dict[str, date] = {}

    # checkin_date column
    if thing.get("checkin_date"):
        parsed = _parse_date(thing["checkin_date"])
        if parsed:
            dates["checkin_date"] = parsed

    # data JSON fields
    raw_data = thing.get("data")
    if raw_data:
        try:
            data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
        except (json.JSONDecodeError, TypeError):
            data = {}
        if isinstance(data, dict):
            for key, value in data.items():
                parsed = _parse_date(value)
                if parsed:
                    dates[key.lower().replace(" ", "_")] = parsed

    return dates


def _get_deadline(dates: dict[str, date]) -> date | None:
    """Get the earliest deadline-like date from extracted dates."""
    deadlines = [d for k, d in dates.items() if k in _DEADLINE_KEYS or k == "checkin_date"]
    return min(deadlines) if deadlines else None


def _get_date_range(dates: dict[str, date]) -> tuple[date | None, date | None]:
    """Extract start/end date range from extracted dates."""
    start = None
    end = None
    for key, d in dates.items():
        if key in _START_KEYS:
            if start is None or d < start:
                start = d
        if key in _DEADLINE_KEYS:
            if end is None or d > end:
                end = d
    return start, end


# ---------------------------------------------------------------------------
# Detection types
# ---------------------------------------------------------------------------


@dataclass
class ConflictAlert:
    alert_type: str  # blocking_chain, schedule_overlap, deadline_conflict
    severity: str  # critical, warning, info
    message: str
    thing_ids: list[str]
    thing_titles: list[str]


def detect_blocking_chains(
    session: Session,
    user_id: str = "",
    window_days: int = 14,
) -> list[ConflictAlert]:
    """Find active Things that are blocked by other active Things,
    especially when the blocked Thing has an approaching deadline."""
    today = date.today()
    alerts: list[ConflictAlert] = []

    # Find all blocks/depends-on relationships between active Things
    # TODO: convert to SQLModel query
    rows = session.execute(
        text(
            """SELECT r.from_thing_id, r.to_thing_id, r.relationship_type,
                  bf.id as blocker_id, bf.title as blocker_title, bf.active as blocker_active,
                  bf.data as blocker_data, bf.checkin_date as blocker_checkin,
                  bt.id as blocked_id, bt.title as blocked_title, bt.active as blocked_active,
                  bt.data as blocked_data, bt.checkin_date as blocked_checkin
           FROM thing_relationships r
           JOIN things bf ON bf.id = r.from_thing_id
           JOIN things bt ON bt.id = r.to_thing_id
           WHERE r.relationship_type IN ('blocks', 'depends-on')
             AND bf.active = 1
             AND bt.active = 1"""
        )
    ).fetchall()

    for row in rows:
        rel_type = row.relationship_type
        # For "blocks": from blocks to. For "depends-on": from depends on to (to is blocker).
        if rel_type == "blocks":
            blocker = {
                "id": row.blocker_id,
                "title": row.blocker_title,
                "data": row.blocker_data,
                "checkin_date": row.blocker_checkin,
            }
            blocked = {
                "id": row.blocked_id,
                "title": row.blocked_title,
                "data": row.blocked_data,
                "checkin_date": row.blocked_checkin,
            }
        else:  # depends-on: from depends on to
            blocked = {
                "id": row.blocker_id,
                "title": row.blocker_title,
                "data": row.blocker_data,
                "checkin_date": row.blocker_checkin,
            }
            blocker = {
                "id": row.blocked_id,
                "title": row.blocked_title,
                "data": row.blocked_data,
                "checkin_date": row.blocked_checkin,
            }

        blocked_dates = _extract_dates(blocked)
        deadline = _get_deadline(blocked_dates)

        if deadline and (deadline - today).days <= window_days:
            days_left = (deadline - today).days
            if days_left <= 0:
                severity = "critical"
                time_msg = "is overdue"
            elif days_left <= 3:
                severity = "critical"
                time_msg = f"is due in {days_left}d"
            elif days_left <= 7:
                severity = "warning"
                time_msg = f"is due in {days_left}d"
            else:
                severity = "info"
                time_msg = f"is due in {days_left}d"

            alerts.append(
                ConflictAlert(
                    alert_type="blocking_chain",
                    severity=severity,
                    message=f'"{blocked["title"]}" {time_msg} but is blocked by "{blocker["title"]}"',
                    thing_ids=[blocked["id"], blocker["id"]],
                    thing_titles=[blocked["title"], blocker["title"]],
                )
            )
        elif not deadline:
            # Still flag active blockers even without deadline
            alerts.append(
                ConflictAlert(
                    alert_type="blocking_chain",
                    severity="info",
                    message=f'"{blocked["title"]}" is blocked by "{blocker["title"]}"',
                    thing_ids=[blocked["id"], blocker["id"]],
                    thing_titles=[blocked["title"], blocker["title"]],
                )
            )

    return alerts


def detect_schedule_overlaps(
    session: Session,
    user_id: str = "",
) -> list[ConflictAlert]:
    """Find Things with overlapping date ranges that are related to each other."""
    today = date.today()
    alerts: list[ConflictAlert] = []

    # Get all active Things with date data
    # TODO: convert to SQLModel query
    rows = session.execute(
        text(
            """SELECT id, title, data, checkin_date FROM things
           WHERE active = 1
             AND (data IS NOT NULL AND data != '{}' AND data != 'null')"""
        )
    ).fetchall()

    # Build map of things with date ranges
    things_with_ranges: list[tuple[dict, date, date]] = []
    for row in rows:
        thing = row._asdict()
        dates = _extract_dates(thing)
        start, end = _get_date_range(dates)
        if start and end and start <= end:
            # Only consider future or current events
            if end >= today:
                things_with_ranges.append((thing, start, end))

    # Check for overlaps between related Things
    if len(things_with_ranges) < 2:
        return alerts

    # Get all relationships for efficiency
    thing_ids = [t[0]["id"] for t in things_with_ranges]
    if not thing_ids:
        return alerts

    ph = ",".join(f":id{i}" for i in range(len(thing_ids)))
    params = {f"id{i}": tid for i, tid in enumerate(thing_ids)}
    rels = session.execute(
        text(
            f"""SELECT from_thing_id, to_thing_id FROM thing_relationships
            WHERE from_thing_id IN ({ph}) OR to_thing_id IN ({ph})"""
        ),
        params,
    ).fetchall()

    related_pairs: set[tuple[str, str]] = set()
    for rel in rels:
        pair = tuple(sorted([rel.from_thing_id, rel.to_thing_id]))
        related_pairs.add(pair)  # type: ignore[arg-type]

    # Check overlaps between related Things
    seen_pairs: set[tuple[str, str]] = set()
    for i, (thing_a, start_a, end_a) in enumerate(things_with_ranges):
        for j, (thing_b, start_b, end_b) in enumerate(things_with_ranges):
            if i >= j:
                continue
            pair = tuple(sorted([thing_a["id"], thing_b["id"]]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)  # type: ignore[arg-type]

            # Only flag overlaps between related Things
            if pair not in related_pairs:
                continue

            # Check overlap
            if start_a <= end_b and start_b <= end_a:
                alerts.append(
                    ConflictAlert(
                        alert_type="schedule_overlap",
                        severity="warning",
                        message=(
                            f'Schedule conflict: "{thing_a["title"]}" '
                            f"({start_a} – {end_a}) overlaps with "
                            f'"{thing_b["title"]}" ({start_b} – {end_b})'
                        ),
                        thing_ids=[thing_a["id"], thing_b["id"]],
                        thing_titles=[thing_a["title"], thing_b["title"]],
                    )
                )

    return alerts


def detect_deadline_conflicts(
    session: Session,
    user_id: str = "",
) -> list[ConflictAlert]:
    """Find dependency chains where a dependency's deadline is after
    its dependent's deadline (the thing you depend on is due after you)."""
    alerts: list[ConflictAlert] = []

    # Get depends-on relationships between active Things
    # TODO: convert to SQLModel query
    rows = session.execute(
        text(
            """SELECT r.from_thing_id, r.to_thing_id, r.relationship_type,
                  df.id as dep_id, df.title as dep_title,
                  df.data as dep_data, df.checkin_date as dep_checkin,
                  dt.id as depn_id, dt.title as depn_title,
                  dt.data as depn_data, dt.checkin_date as depn_checkin
           FROM thing_relationships r
           JOIN things df ON df.id = r.from_thing_id
           JOIN things dt ON dt.id = r.to_thing_id
           WHERE r.relationship_type IN ('depends-on', 'blocks')
             AND df.active = 1
             AND dt.active = 1"""
        )
    ).fetchall()

    for row in rows:
        rel_type = row.relationship_type
        if rel_type == "depends-on":
            # from depends on to: "from" needs "to" to be done first
            dependent = {
                "id": row.dep_id,
                "title": row.dep_title,
                "data": row.dep_data,
                "checkin_date": row.dep_checkin,
            }
            dependency = {
                "id": row.depn_id,
                "title": row.depn_title,
                "data": row.depn_data,
                "checkin_date": row.depn_checkin,
            }
        else:  # blocks: from blocks to — "to" depends on "from"
            dependency = {
                "id": row.dep_id,
                "title": row.dep_title,
                "data": row.dep_data,
                "checkin_date": row.dep_checkin,
            }
            dependent = {
                "id": row.depn_id,
                "title": row.depn_title,
                "data": row.depn_data,
                "checkin_date": row.depn_checkin,
            }

        dependent_dates = _extract_dates(dependent)
        dependency_dates = _extract_dates(dependency)

        dependent_deadline = _get_deadline(dependent_dates)
        dependency_deadline = _get_deadline(dependency_dates)

        if dependent_deadline and dependency_deadline and dependency_deadline > dependent_deadline:
            gap = (dependency_deadline - dependent_deadline).days
            alerts.append(
                ConflictAlert(
                    alert_type="deadline_conflict",
                    severity="critical" if gap > 3 else "warning",
                    message=(
                        f'Deadline conflict: "{dependent["title"]}" is due '
                        f'{dependent_deadline} but depends on "{dependency["title"]}" '
                        f"which is due {dependency_deadline} ({gap}d later)"
                    ),
                    thing_ids=[dependent["id"], dependency["id"]],
                    thing_titles=[dependent["title"], dependency["title"]],
                )
            )

    return alerts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_all_conflicts(
    user_id: str = "",
    window_days: int = 14,
) -> list[ConflictAlert]:
    """Run all conflict detectors and return combined, deduplicated results."""
    with Session(_engine_mod.engine) as session:
        alerts = (
            detect_blocking_chains(session, user_id, window_days)
            + detect_schedule_overlaps(session, user_id)
            + detect_deadline_conflicts(session, user_id)
        )

    # Deduplicate by (alert_type, sorted thing_ids)
    seen: set[tuple[str, tuple[str, ...]]] = set()
    unique: list[ConflictAlert] = []
    for alert in alerts:
        key = (alert.alert_type, tuple(sorted(alert.thing_ids)))
        if key not in seen:
            seen.add(key)
            unique.append(alert)

    # Sort: critical first, then warning, then info
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    unique.sort(key=lambda a: (severity_order.get(a.severity, 3), a.message))
    return unique
