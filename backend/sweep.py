"""Nightly sweep — SQL candidate queries, LLM reflection, and personality aggregation.

Phase 1 (SQL): Identifies Things that may need the user's attention using cheap
SQL queries.  Phase 2 (LLM): Sends the candidate list to an LLM for nuanced
reflection, producing sweep_findings with priority and expiry.  Phase 3
(Personality): Aggregates implicit behavioral signals from user interactions
into personality preference updates.

Finding types:
  - approaching_date: Thing with a date (checkin, birthday, deadline, etc.) within 7 days
  - stale: Active Thing not updated in the configured threshold (low priority, no pending work)
  - neglected: Active Thing not updated AND high-priority or has pending children
  - overdue_checkin: Active Thing whose checkin_date is in the past (beyond grace period)
  - orphan: Active Thing with no relationships (no parent, no children, no graph edges)
  - completed_project: Project where all children are inactive but project is still active
  - open_question: Active Thing with unanswered open_questions
  - incomplete: Active Thing with information gaps (no dates, minimal data, name-only person)
  - cross_project_shared_blocker: Thing that blocks tasks in multiple projects
  - cross_project_resource_conflict: Person/entity involved in multiple stale projects
  - cross_project_thematic_connection: Similar Things across different projects
  - cross_project_duplicate_effort: Tasks with near-identical titles in different projects
  - information_gap: Active Thing missing key information (no dates, minimal data, etc.)
  - broad_thing_no_subtasks: Active project/event/goal/trip with no child subtasks
  - llm_insight: LLM-generated finding from reflection phase

Preference aggregation (separate phase, see preference_sweep.py):
  - Analyzes chat interaction patterns to detect/update user preference Things

Behavioral signals (Phase 3):
  - title_shortening: User edits Reli-created titles to be shorter
  - finding_dismissal: User dismisses a high proportion of a finding type
  - finding_engagement: User keeps/reads a high proportion of a finding type
"""

from __future__ import annotations

import json
import logging
import re

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, cast, func, String
from sqlmodel import Session, or_, select

import backend.db_engine as _engine_mod
from .db_engine import user_filter_clause
from .db_models import (
    ChatHistoryRecord,
    SweepFindingRecord,
    ThingRecord,
    ThingRelationshipRecord,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Date parsing (shared with proactive.py)
# ---------------------------------------------------------------------------

_RECURRING_KEYS = {"birthday", "anniversary", "born", "date_of_birth", "dob"}
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

_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

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


def _parse_date_value(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        m = _DATE_RE.search(value)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def _days_until_next_occurrence(target: date, today: date) -> int:
    try:
        this_year = today.replace(month=target.month, day=target.day)
    except ValueError:
        return 999  # e.g. Feb 29 in a non-leap year
    if this_year >= today:
        return (this_year - today).days
    try:
        next_year = today.replace(year=today.year + 1, month=target.month, day=target.day)
    except ValueError:
        return 999
    return (next_year - today).days


# ---------------------------------------------------------------------------
# Candidate data structure
# ---------------------------------------------------------------------------


@dataclass
class SweepCandidate:
    """A Thing flagged by the SQL sweep for potential LLM review."""

    thing_id: str
    thing_title: str
    finding_type: str
    message: str
    priority: int = 2
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Individual candidate queries
# ---------------------------------------------------------------------------


def find_approaching_dates(
    session: Session,
    today: date | None = None,
    window_days: int = 7,
    user_id: str = "",
) -> list[SweepCandidate]:
    """Find Things with dates (checkin_date or data JSON dates) within *window_days*.

    Covers both the checkin_date column and date fields stored in the data JSON.
    """
    today = today or date.today()
    cutoff = today + timedelta(days=window_days)
    candidates: list[SweepCandidate] = []
    # 1. checkin_date column (already in ISO format)
    stmt = (
        select(ThingRecord.id, ThingRecord.title, ThingRecord.checkin_date)
        .where(
            ThingRecord.active == True,  # noqa: E712
            ThingRecord.checkin_date.is_not(None),  # type: ignore[union-attr]
            func.date(ThingRecord.checkin_date).between(today.isoformat(), cutoff.isoformat()),
            user_filter_clause(ThingRecord.user_id, user_id),
        )
    )
    rows = session.exec(stmt).all()  # type: ignore[arg-type]
    for row in rows:
        parsed = _parse_date_value(row.checkin_date)
        if parsed:
            days = (parsed - today).days
            if days == 0:
                label = "Check-in today"
            elif days == 1:
                label = "Check-in tomorrow"
            else:
                label = f"Check-in in {days}d"
            candidates.append(
                SweepCandidate(
                    thing_id=row.id,
                    thing_title=row.title,
                    finding_type="approaching_date",
                    message=f"{label}: {row.title}",
                    priority=1 if days <= 1 else 2,
                    extra={"date_key": "checkin_date", "days_away": days},
                )
            )

    # 2. Date fields in the data JSON
    stmt2 = (
        select(ThingRecord.id, ThingRecord.title, ThingRecord.data)
        .where(
            ThingRecord.active == True,  # noqa: E712
            ThingRecord.data.is_not(None),  # type: ignore[union-attr]
            cast(ThingRecord.data, String) != '{}',
            user_filter_clause(ThingRecord.user_id, user_id),
        )
    )
    data_rows = session.exec(stmt2).all()  # type: ignore[arg-type]
    for row in data_rows:
        try:
            data = json.loads(row.data) if isinstance(row.data, str) else row.data
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
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
                    continue
            if days <= window_days:
                if days == 0:
                    reason = f"{label} today"
                elif days == 1:
                    reason = f"{label} tomorrow"
                else:
                    reason = f"{label} in {days}d"
                candidates.append(
                    SweepCandidate(
                        thing_id=row.id,
                        thing_title=row.title,
                        finding_type="approaching_date",
                        message=f"{reason}: {row.title}",
                        priority=1 if days <= 1 else 2,
                        extra={"date_key": key, "days_away": days},
                    )
                )

    return candidates


def find_stale_things(
    session: Session,
    today: date | None = None,
    stale_days: int = 14,
    user_id: str = "",
) -> list[SweepCandidate]:
    """Find active Things not updated in *stale_days* or more.

    Includes neglect context: Things with higher priority or pending children
    are flagged as ``neglected`` instead of plain ``stale``.
    """
    today = today or date.today()
    cutoff = (today - timedelta(days=stale_days)).isoformat()
    # Build a correlated subquery for active_children via parent-of relationships
    _r = ThingRelationshipRecord.__table__.alias("r")
    _c = ThingRecord.__table__.alias("c")
    active_children_sq = (
        select(func.count(_c.c.id))
        .select_from(_r.join(_c, _c.c.id == _r.c.to_thing_id))
        .where(
            _r.c.from_thing_id == ThingRecord.id,
            _r.c.relationship_type == "parent-of",
            _c.c.active == True,  # noqa: E712
        )
        .correlate(ThingRecord.__table__)
        .scalar_subquery()
        .label("active_children")
    )
    stmt = (
        select(
            ThingRecord.id,
            ThingRecord.title,
            ThingRecord.type_hint,
            ThingRecord.updated_at,
            ThingRecord.importance,
            ThingRecord.checkin_date,
            active_children_sq,
        )
        .where(
            ThingRecord.active == True,  # noqa: E712
            ThingRecord.updated_at < cutoff,
            user_filter_clause(ThingRecord.user_id, user_id),
        )
        .order_by(ThingRecord.updated_at.asc())
    )
    rows = session.execute(stmt).all()

    candidates: list[SweepCandidate] = []
    for row in rows:
        parsed_dt = _parse_date_value(row.updated_at)
        days_stale = (today - parsed_dt).days if parsed_dt else stale_days
        type_label = row.type_hint or "Thing"
        importance_val = row.importance if row.importance is not None else 2
        active_children = row.active_children or 0

        # Distinguish neglected (high-importance or has pending work) from plain stale
        is_neglected = importance_val <= 1 or active_children > 0
        finding_type = "neglected" if is_neglected else "stale"

        if is_neglected:
            parts = []
            if importance_val <= 1:
                parts.append("high-importance")
            if active_children > 0:
                parts.append(f"{active_children} pending subtask{'s' if active_children != 1 else ''}")
            context = ", ".join(parts)
            message = f"Neglected for {days_stale}d ({context}): {row.title}"
            pri = 2  # higher urgency for neglected items
        else:
            message = f"Untouched for {days_stale}d: {row.title}"
            pri = 3

        candidates.append(
            SweepCandidate(
                thing_id=row.id,
                thing_title=row.title,
                finding_type=finding_type,
                message=message,
                priority=pri,
                extra={
                    "days_stale": days_stale,
                    "type_hint": type_label,
                    "is_neglected": is_neglected,
                    "active_children": active_children,
                },
            )
        )
    return candidates


def find_overdue_checkins(
    session: Session,
    today: date | None = None,
    grace_days: int = 1,
) -> list[SweepCandidate]:
    """Find active Things with overdue checkin_date (past the grace period).

    Things whose checkin_date is today or within *grace_days* are handled by
    ``find_approaching_dates``; this catches items that have been overdue longer.
    """
    today = today or date.today()
    cutoff = (today - timedelta(days=grace_days)).isoformat()
    stmt = (
        select(
            ThingRecord.id, ThingRecord.title, ThingRecord.type_hint,
            ThingRecord.checkin_date, ThingRecord.importance,
        )
        .where(
            ThingRecord.active == True,  # noqa: E712
            ThingRecord.checkin_date.is_not(None),  # type: ignore[union-attr]
            func.date(ThingRecord.checkin_date) < cutoff,
        )
        .order_by(ThingRecord.checkin_date)
    )
    rows = session.exec(stmt).all()  # type: ignore[arg-type]

    candidates: list[SweepCandidate] = []
    for row in rows:
        parsed = _parse_date_value(row.checkin_date)
        if not parsed:
            continue
        days_overdue = (today - parsed).days
        importance_val = row.importance if row.importance is not None else 2
        pri = 1 if days_overdue >= 7 or importance_val <= 1 else 2
        candidates.append(
            SweepCandidate(
                thing_id=row.id,
                thing_title=row.title,
                finding_type="overdue_checkin",
                message=f"Check-in overdue by {days_overdue}d: {row.title}",
                priority=pri,
                extra={
                    "days_overdue": days_overdue,
                    "type_hint": row.type_hint or "Thing",
                },
            )
        )
    return candidates


def find_orphan_things(session: Session, user_id: str = "") -> list[SweepCandidate]:
    """Find active Things with no relationships (no parent, no children, no graph edges)."""
    stmt = (
        select(ThingRecord.id, ThingRecord.title, ThingRecord.type_hint)
        .outerjoin(
            ThingRelationshipRecord,
            or_(
                ThingRecord.id == ThingRelationshipRecord.from_thing_id,
                ThingRecord.id == ThingRelationshipRecord.to_thing_id,
            ),
        )
        .where(
            ThingRecord.active == True,  # noqa: E712
            ThingRelationshipRecord.id.is_(None),  # type: ignore[union-attr]
            user_filter_clause(ThingRecord.user_id, user_id),
        )
        .order_by(ThingRecord.created_at.desc())
    )
    rows = session.execute(stmt).all()

    candidates: list[SweepCandidate] = []
    for row in rows:
        candidates.append(
            SweepCandidate(
                thing_id=row.id,
                thing_title=row.title,
                finding_type="orphan",
                message=f"No connections: {row.title}",
                priority=3,
                extra={"type_hint": row.type_hint or "Thing"},
            )
        )
    return candidates


def find_completed_projects(session: Session, user_id: str = "") -> list[SweepCandidate]:
    """Find active projects where all children are inactive (completed).

    A project qualifies if:
    - It's active with type_hint='project'
    - It has at least one child (via parent-of relationship)
    - ALL of its children are inactive
    """
    _p = ThingRecord.__table__.alias("p")
    _r = ThingRelationshipRecord.__table__.alias("r")
    _ch = ThingRecord.__table__.alias("c")
    stmt = (
        select(
            _p.c.id,
            _p.c.title,
            func.count(_ch.c.id).label("total_children"),
            func.sum(case((_ch.c.active == False, 1), else_=0)).label("inactive_children"),  # noqa: E712
        )
        .select_from(
            _p.join(_r, (_r.c.from_thing_id == _p.c.id) & (_r.c.relationship_type == "parent-of"))
            .join(_ch, _ch.c.id == _r.c.to_thing_id)
        )
        .where(
            _p.c.active == True,  # noqa: E712
            _p.c.type_hint == "project",
            user_filter_clause(_p.c.user_id, user_id),
        )
        .group_by(_p.c.id, _p.c.title)
        .having(
            func.count(_ch.c.id) > 0,
            func.count(_ch.c.id) == func.sum(case((_ch.c.active == False, 1), else_=0)),  # noqa: E712
        )
    )
    rows = session.execute(stmt).all()

    candidates: list[SweepCandidate] = []
    for row in rows:
        n = row.total_children
        candidates.append(
            SweepCandidate(
                thing_id=row.id,
                thing_title=row.title,
                finding_type="completed_project",
                message=f"All {n} tasks done — still active: {row.title}",
                priority=2,
                extra={"total_children": n},
            )
        )
    return candidates


def find_broad_things_without_subtasks(session: Session, user_id: str = "") -> list[SweepCandidate]:
    """Find active broad Things (project/event/goal/trip) with no active children.

    A Thing qualifies if:
    - It's active with type_hint in ('project', 'event', 'goal', 'trip')
    - importance <= 2 (skip explicitly low-priority Things; 2 is the default)
    - It has NO active children via 'parent-of' relationship
    """
    _p = ThingRecord.__table__.alias("p")
    _r = ThingRelationshipRecord.__table__.alias("r")
    _ch = ThingRecord.__table__.alias("c")
    stmt = (
        select(_p.c.id, _p.c.title, _p.c.type_hint, _p.c.importance)
        .select_from(_p)
        .outerjoin(
            _r,
            (_r.c.from_thing_id == _p.c.id) & (_r.c.relationship_type == "parent-of"),
        )
        .outerjoin(_ch, (_ch.c.id == _r.c.to_thing_id) & (_ch.c.active == True))  # noqa: E712
        .where(
            _p.c.active == True,  # noqa: E712
            _p.c.importance <= 2,
            _p.c.type_hint.in_(["project", "event", "goal", "trip"]),
            user_filter_clause(_p.c.user_id, user_id),
        )
        .group_by(_p.c.id, _p.c.title, _p.c.type_hint, _p.c.importance)
        .having(func.count(_ch.c.id) == 0)
    )
    rows = session.execute(stmt).all()

    return [
        SweepCandidate(
            thing_id=row.id,
            thing_title=row.title,
            finding_type="broad_thing_no_subtasks",
            message=f"Broad {row.type_hint} with no subtasks: {row.title}",
            priority=2,
            extra={"type_hint": row.type_hint or "unknown", "importance": row.importance},
        )
        for row in rows
    ]


def find_open_questions(session: Session, user_id: str = "") -> list[SweepCandidate]:
    """Find active Things that have unanswered open_questions."""
    stmt = (
        select(ThingRecord.id, ThingRecord.title, ThingRecord.open_questions)
        .where(
            ThingRecord.active == True,  # noqa: E712
            ThingRecord.open_questions.is_not(None),  # type: ignore[union-attr]
            cast(ThingRecord.open_questions, String).notin_(["[]", "null"]),
            user_filter_clause(ThingRecord.user_id, user_id),
        )
    )
    rows = session.exec(stmt).all()  # type: ignore[arg-type]

    candidates: list[SweepCandidate] = []
    for row in rows:
        try:
            raw = row.open_questions
            questions = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(questions, list) or not questions:
            continue
        n = len(questions)
        first_q = questions[0] if questions else ""
        preview = first_q[:80] + "…" if len(first_q) > 80 else first_q
        candidates.append(
            SweepCandidate(
                thing_id=row.id,
                thing_title=row.title,
                finding_type="open_question",
                message=f"{n} unanswered question{'s' if n != 1 else ''}: {row.title}",
                priority=2,
                extra={"question_count": n, "first_question": preview},
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Gap detection — incomplete Things
# ---------------------------------------------------------------------------


def find_incomplete_things(
    session: Session,
    user_id: str = "",
) -> list[SweepCandidate]:
    """Find active Things with information gaps that need filling.

    Detects:
    - No dates: no checkin_date and no date fields in data JSON
    - Minimal data: null or empty data dict
    - Name-only people: type_hint='person' with sparse data
    - No deadlines: tasks/projects with no deadline-type date
    """
    # Fetch active things that don't already have open_questions.
    # open_questions is a JSON column; legacy data may contain NULL, [], or
    # the literal JSON string "null".  Filter with ORM comparisons.
    stmt = (
        select(
            ThingRecord.id,
            ThingRecord.title,
            ThingRecord.type_hint,
            ThingRecord.data,
            ThingRecord.checkin_date,
        )
        .where(
            ThingRecord.active == True,  # noqa: E712
            or_(
                ThingRecord.open_questions.is_(None),  # type: ignore[union-attr]
                cast(ThingRecord.open_questions, String) == "[]",
                cast(ThingRecord.open_questions, String) == "null",
            ),
            user_filter_clause(ThingRecord.user_id, user_id),
        )
        .order_by(ThingRecord.updated_at.desc())
    )
    rows = session.execute(stmt).all()

    candidates: list[SweepCandidate] = []
    seen_ids: set[str] = set()

    for row in rows:
        thing_id = row.id
        title = row.title
        type_hint = row.type_hint or ""
        checkin_date = row.checkin_date

        # Parse data JSON
        raw_data = row.data
        try:
            data = json.loads(raw_data) if isinstance(raw_data, str) and raw_data else raw_data
        except (json.JSONDecodeError, TypeError):
            data = None
        if not isinstance(data, dict):
            data = {}

        gaps: list[str] = []

        # Check: name-only person (most specific — check first)
        if type_hint == "person":
            meaningful_keys = {k for k in data if k not in ("notes",) and data[k]}
            if len(meaningful_keys) < 2:
                gaps.append("name-only person")

        # Check: minimal data (empty or null data dict)
        if not data:
            gaps.append("no data")

        # Check: no dates at all
        has_checkin = bool(checkin_date)
        has_data_dates = any(k.lower().replace(" ", "_") in _ALL_DATE_KEYS for k in data)
        if not has_checkin and not has_data_dates:
            gaps.append("no dates")

        # Check: task/project without deadline
        if type_hint in ("task", "project", "goal"):
            has_deadline = any(k.lower().replace(" ", "_") in _ONESHOT_KEYS for k in data)
            if not has_checkin and not has_deadline:
                gaps.append("no deadline")

        if not gaps or thing_id in seen_ids:
            continue
        seen_ids.add(thing_id)

        gap_summary = ", ".join(gaps)
        type_label = type_hint.title() if type_hint else "Thing"
        candidates.append(
            SweepCandidate(
                thing_id=thing_id,
                thing_title=title,
                finding_type="incomplete",
                message=f"Incomplete {type_label} ({gap_summary}): {title}",
                priority=3,
                extra={
                    "type_hint": type_hint or "unknown",
                    "gaps": gaps,
                    "data_key_count": len(data),
                },
            )
        )

    return candidates


# ---------------------------------------------------------------------------
# Information gap detection (used by collect_candidates)
# ---------------------------------------------------------------------------

# Questions generated per gap type — keyed by (gap_type, type_hint or None).
_GAP_QUESTIONS: dict[str, dict[str | None, list[str]]] = {
    "no_dates": {
        "event": ["When is this event?"],
        "task": ["When does this need to be done?"],
        "project": ["When does this need to be done?"],
        "goal": ["What's your timeline for this goal?"],
        None: ["Are there any important dates for this?"],
    },
    "name_only_person": {
        None: ["How do you know {title}?", "What's {title}'s role or relationship to you?"],
    },
    "no_deadline_project": {
        None: ["When does this need to be done?", "What does 'done' look like for this project?"],
    },
    "minimal_data": {
        "person": ["How do you know {title}?"],
        "event": ["When and where is this?", "Who else is involved?"],
        "project": ["What's the goal of this project?", "What are the next steps?"],
        "task": ["What does 'done' look like for this?"],
        None: ['Want to flesh out "{title}" with more details?'],
    },
}


def _questions_for_gap(
    gap_type: str,
    type_hint: str | None,
    title: str,
) -> list[str]:
    """Return question templates for a gap type, formatted with Thing title."""
    type_map = _GAP_QUESTIONS.get(gap_type, {})
    templates = type_map.get(type_hint) or type_map.get(None, [])
    return [t.format(title=title) for t in templates]


def find_information_gaps(
    session: Session,
    today: date | None = None,
    min_age_days: int = 3,
    user_id: str = "",
) -> list[SweepCandidate]:
    """Find active Things with missing key information.

    Detects:
    - Things with no dates (no checkin_date, no date fields in data)
    - Person Things with name only (no or empty data)
    - Projects with active children but no deadline
    - Things older than *min_age_days* with null/empty data

    Only flags Things that do NOT already have open_questions (to avoid
    re-generating questions the user hasn't addressed yet).
    """
    today = today or date.today()
    age_cutoff = (today - timedelta(days=min_age_days)).isoformat()

    # ORM helpers for JSON columns that may be NULL, empty, or 'null'
    _no_data_clause = or_(
        ThingRecord.data.is_(None),  # type: ignore[union-attr]
        cast(ThingRecord.data, String) == "{}",
        cast(ThingRecord.data, String) == "null",
    )
    _no_oq_clause = or_(
        ThingRecord.open_questions.is_(None),  # type: ignore[union-attr]
        cast(ThingRecord.open_questions, String) == "[]",
        cast(ThingRecord.open_questions, String) == "null",
    )

    candidates: list[SweepCandidate] = []

    # --- Name-only persons: person type with null/empty data ---
    person_stmt = (
        select(ThingRecord.id, ThingRecord.title, ThingRecord.type_hint, ThingRecord.data, ThingRecord.created_at)
        .where(
            ThingRecord.active == True,  # noqa: E712
            ThingRecord.type_hint == "person",
            _no_data_clause,
            _no_oq_clause,
            ThingRecord.created_at < age_cutoff,
            user_filter_clause(ThingRecord.user_id, user_id),
        )
    )
    person_rows = session.execute(person_stmt).all()
    for row in person_rows:
        candidates.append(
            SweepCandidate(
                thing_id=row.id,
                thing_title=row.title,
                finding_type="information_gap",
                message=f"Name only — no context: {row.title}",
                priority=3,
                extra={"gap_type": "name_only_person", "type_hint": "person"},
            )
        )

    # --- Projects with children but no deadline ---
    _p = ThingRecord.__table__.alias("p")
    _r2 = ThingRelationshipRecord.__table__.alias("r2")
    _ch2 = ThingRecord.__table__.alias("c")
    _no_oq_p = or_(
        _p.c.open_questions.is_(None),
        cast(_p.c.open_questions, String) == "[]",
        cast(_p.c.open_questions, String) == "null",
    )
    proj_stmt = (
        select(
            _p.c.id,
            _p.c.title,
            _p.c.data,
            func.count(_ch2.c.id).label("child_count"),
        )
        .select_from(
            _p.join(_r2, (_r2.c.from_thing_id == _p.c.id) & (_r2.c.relationship_type == "parent-of"))
            .join(_ch2, (_ch2.c.id == _r2.c.to_thing_id) & (_ch2.c.active == True))  # noqa: E712
        )
        .where(
            _p.c.active == True,  # noqa: E712
            _p.c.type_hint == "project",
            _p.c.checkin_date.is_(None),
            _no_oq_p,
            user_filter_clause(_p.c.user_id, user_id),
        )
        .group_by(_p.c.id, _p.c.title, cast(_p.c.data, String))
        .having(func.count(_ch2.c.id) > 0)
    )
    proj_rows = session.execute(proj_stmt).all()
    for row in proj_rows:
        # Check data JSON for deadline/due_date fields
        has_deadline = False
        if row.data:
            try:
                data = json.loads(row.data) if isinstance(row.data, str) else row.data
                if isinstance(data, dict):
                    has_deadline = bool(set(data.keys()) & {"deadline", "due_date", "due", "end_date", "ends_at"})
            except (json.JSONDecodeError, TypeError):
                pass
        if not has_deadline:
            candidates.append(
                SweepCandidate(
                    thing_id=row.id,
                    thing_title=row.title,
                    finding_type="information_gap",
                    message=f"Project has {row.child_count} task(s) but no deadline: {row.title}",
                    priority=2,
                    extra={
                        "gap_type": "no_deadline_project",
                        "type_hint": "project",
                        "child_count": row.child_count,
                    },
                )
            )

    # --- Things with no dates at all ---
    no_date_stmt = (
        select(ThingRecord.id, ThingRecord.title, ThingRecord.type_hint, ThingRecord.data)
        .where(
            ThingRecord.active == True,  # noqa: E712
            ThingRecord.checkin_date.is_(None),  # type: ignore[union-attr]
            ThingRecord.type_hint.in_(["event", "task", "goal"]),  # type: ignore[union-attr]
            _no_oq_clause,
            ThingRecord.created_at < age_cutoff,
            user_filter_clause(ThingRecord.user_id, user_id),
        )
    )
    no_date_rows = session.execute(no_date_stmt).all()
    for row in no_date_rows:
        has_date = False
        if row.data:
            try:
                data = json.loads(row.data) if isinstance(row.data, str) else row.data
                if isinstance(data, dict):
                    has_date = bool(set(k.lower().replace(" ", "_") for k in data.keys()) & _ALL_DATE_KEYS)
            except (json.JSONDecodeError, TypeError):
                pass
        if not has_date:
            type_hint = row.type_hint or "Thing"
            candidates.append(
                SweepCandidate(
                    thing_id=row.id,
                    thing_title=row.title,
                    finding_type="information_gap",
                    message=f"{type_hint.title()} has no dates: {row.title}",
                    priority=3,
                    extra={"gap_type": "no_dates", "type_hint": row.type_hint},
                )
            )

    # --- Minimal data: old Things with null/empty data (exclude persons, already handled) ---
    minimal_stmt = (
        select(ThingRecord.id, ThingRecord.title, ThingRecord.type_hint, ThingRecord.created_at)
        .where(
            ThingRecord.active == True,  # noqa: E712
            _no_data_clause,
            or_(
                ThingRecord.type_hint.is_(None),  # type: ignore[union-attr]
                ThingRecord.type_hint.notin_(["person", "preference"]),  # type: ignore[union-attr]
            ),
            _no_oq_clause,
            ThingRecord.created_at < age_cutoff,
            user_filter_clause(ThingRecord.user_id, user_id),
        )
    )
    minimal_rows = session.execute(minimal_stmt).all()
    # Only flag if old enough to suggest fleshing out (use 14 days for minimal_data)
    minimal_cutoff_str = (today - timedelta(days=14)).isoformat()
    for row in minimal_rows:
        created = row.created_at
        # Normalize to string for safe comparison (works with both naive and aware)
        created_str = created.isoformat() if isinstance(created, datetime) else str(created) if created else None
        if created_str and created_str > minimal_cutoff_str:
            continue
        type_hint = row.type_hint or "Thing"
        candidates.append(
            SweepCandidate(
                thing_id=row.id,
                thing_title=row.title,
                finding_type="information_gap",
                message=f"Minimal data — created 14+ days ago: {row.title}",
                priority=3,
                extra={"gap_type": "minimal_data", "type_hint": row.type_hint},
            )
        )

    return candidates


def _generate_template_gap_questions(
    session: Session,
    gap_candidates: list[SweepCandidate],
) -> int:
    """Generate and store open_questions on Things based on detected gaps.

    Uses template-based question generation (no LLM). Only writes questions
    for Things that don't already have open_questions.
    Returns the number of Things updated.
    """
    updated = 0
    for candidate in gap_candidates:
        if candidate.finding_type != "information_gap":
            continue
        gap_type = candidate.extra.get("gap_type", "")
        type_hint = candidate.extra.get("type_hint")
        questions = _questions_for_gap(gap_type, type_hint, candidate.thing_title)
        if not questions:
            continue

        # Double-check the Thing still has no open_questions (race safety)
        thing = session.get(ThingRecord, candidate.thing_id)
        if not thing:
            continue
        existing = thing.open_questions
        if existing and existing not in ([], "null", ""):
            continue

        # Don't update updated_at — sweep-generated questions shouldn't make
        # a Thing appear "fresh" (which would hide it from stale detection).
        thing.open_questions = questions  # type: ignore[assignment]
        updated += 1
    return updated


# ---------------------------------------------------------------------------
# Cross-project pattern detection (#sweep-finding)
# ---------------------------------------------------------------------------


def find_cross_project_shared_blockers(session: Session) -> list[SweepCandidate]:
    """Find Things that block active tasks in multiple projects.

    A "shared blocker" is a Thing connected (via relationships) to active tasks
    in 2+ different projects. This means one Thing's resolution would unblock
    progress across multiple projects.
    """
    # Find Things that have "blocks" or similar relationships to tasks in
    # different projects.  We look for Things connected to children of
    # different projects via typed edges.
    _blocker = ThingRecord.__table__.alias("blocker")
    _r = ThingRelationshipRecord.__table__.alias("r")
    _task = ThingRecord.__table__.alias("task")
    _rp = ThingRelationshipRecord.__table__.alias("rp")
    _proj = ThingRecord.__table__.alias("p")

    # The "task" is the other side of the relationship from blocker
    _task_id_expr = case(
        (_blocker.c.id == _r.c.from_thing_id, _r.c.to_thing_id),
        else_=_r.c.from_thing_id,
    )

    # Fetch individual rows (blocker + project) and aggregate in Python to
    # avoid GROUP_CONCAT / string_agg which differ between SQLite and Postgres.
    stmt = (
        select(
            _blocker.c.id.label("blocker_id"),
            _blocker.c.title.label("blocker_title"),
            _proj.c.id.label("project_id"),
            _proj.c.title.label("project_title"),
        )
        .select_from(
            _blocker
            .join(_r, or_(_blocker.c.id == _r.c.from_thing_id, _blocker.c.id == _r.c.to_thing_id))
            .join(_task, _task.c.id == _task_id_expr)
            .join(_rp, (_rp.c.to_thing_id == _task.c.id) & (_rp.c.relationship_type == "parent-of"))
            .join(_proj, (_proj.c.id == _rp.c.from_thing_id) & (_proj.c.type_hint == "project") & (_proj.c.active == True))  # noqa: E712
        )
        .where(
            _blocker.c.active == True,  # noqa: E712
            _task.c.active == True,  # noqa: E712
            _r.c.relationship_type.in_(["blocks", "blocked_by", "depends_on", "dependency"]),
        )
    )
    raw_rows = session.execute(stmt).all()

    # Aggregate: group by blocker, collect distinct project titles
    from collections import defaultdict
    blocker_projects: dict[str, dict] = {}
    blocker_proj_titles: dict[str, set[str]] = defaultdict(set)
    for row in raw_rows:
        blocker_projects[row.blocker_id] = {"id": row.blocker_id, "title": row.blocker_title}
        blocker_proj_titles[row.blocker_id].add(row.project_title)

    candidates: list[SweepCandidate] = []
    for blocker_id, info in blocker_projects.items():
        proj_titles = blocker_proj_titles[blocker_id]
        if len(proj_titles) < 2:
            continue
        projects = ", ".join(sorted(proj_titles))
        project_count = len(proj_titles)
        candidates.append(
            SweepCandidate(
                thing_id=blocker_id,
                thing_title=info["title"],
                finding_type="cross_project_shared_blocker",
                message=(f"Blocks tasks in {project_count} projects ({projects}): {info['title']}"),
                priority=1,
                extra={
                    "project_count": project_count,
                    "project_titles": projects,
                },
            )
        )
    return candidates


def find_cross_project_resource_conflicts(
    session: Session,
    today: date | None = None,
    stale_days: int = 14,
) -> list[SweepCandidate]:
    """Find people/resources involved in multiple projects with stale tasks.

    A "resource conflict" is when a person (type_hint='person') is connected to
    active tasks in 2+ projects, and at least one of those tasks is stale. This
    suggests the person may be overcommitted.
    """
    today = today or date.today()
    stale_cutoff = (today - timedelta(days=stale_days)).isoformat()

    _person = ThingRecord.__table__.alias("person")
    _r = ThingRelationshipRecord.__table__.alias("r")
    _task = ThingRecord.__table__.alias("task")
    _rp = ThingRelationshipRecord.__table__.alias("rp")
    _proj = ThingRecord.__table__.alias("p")

    _task_id_expr = case(
        (_person.c.id == _r.c.from_thing_id, _r.c.to_thing_id),
        else_=_r.c.from_thing_id,
    )

    # Fetch individual rows and aggregate in Python (avoids GROUP_CONCAT / string_agg)
    stmt = (
        select(
            _person.c.id.label("person_id"),
            _person.c.title.label("person_title"),
            _proj.c.id.label("project_id"),
            _proj.c.title.label("project_title"),
            _task.c.updated_at.label("task_updated_at"),
        )
        .select_from(
            _person
            .join(_r, or_(_person.c.id == _r.c.from_thing_id, _person.c.id == _r.c.to_thing_id))
            .join(_task, _task.c.id == _task_id_expr)
            .join(_rp, (_rp.c.to_thing_id == _task.c.id) & (_rp.c.relationship_type == "parent-of"))
            .join(_proj, (_proj.c.id == _rp.c.from_thing_id) & (_proj.c.type_hint == "project") & (_proj.c.active == True))  # noqa: E712
        )
        .where(
            _person.c.active == True,  # noqa: E712
            _person.c.type_hint == "person",
            _task.c.active == True,  # noqa: E712
        )
    )
    raw_rows = session.execute(stmt).all()

    # Aggregate per person: distinct projects, count stale tasks
    from collections import defaultdict
    person_info: dict[str, str] = {}
    person_projects: dict[str, set[str]] = defaultdict(set)
    person_stale: dict[str, int] = defaultdict(int)
    for row in raw_rows:
        person_info[row.person_id] = row.person_title
        person_projects[row.person_id].add(row.project_title)
        task_updated = row.task_updated_at
        updated_str = task_updated.isoformat() if isinstance(task_updated, datetime) else str(task_updated) if task_updated else ""
        if updated_str and updated_str < stale_cutoff:
            person_stale[row.person_id] += 1

    candidates: list[SweepCandidate] = []
    for person_id, person_title in person_info.items():
        proj_titles = person_projects[person_id]
        stale_tasks = person_stale.get(person_id, 0)
        if len(proj_titles) < 2 or stale_tasks == 0:
            continue
        project_count = len(proj_titles)
        project_titles_str = ", ".join(sorted(proj_titles))
        candidates.append(
            SweepCandidate(
                thing_id=person_id,
                thing_title=person_title,
                finding_type="cross_project_resource_conflict",
                message=(
                    f"{person_title} is involved in {project_count} projects "
                    f"with {stale_tasks} stale task(s): {project_titles_str}"
                ),
                priority=2,
                extra={
                    "project_count": project_count,
                    "project_titles": project_titles_str,
                    "stale_tasks": stale_tasks,
                },
            )
        )
    return candidates


def find_cross_project_thematic_connections(
    session: Session,
) -> list[SweepCandidate]:
    """Find active Things with similar titles across different projects.

    Uses SQL LIKE matching to find tasks whose titles share significant words
    (3+ chars) across different project hierarchies. This helps identify
    thematic connections or potential collaboration opportunities.
    """
    # Get all active tasks that belong to a project (via parent-of relationship)
    _t = ThingRecord.__table__.alias("t")
    _rp = ThingRelationshipRecord.__table__.alias("rp")
    _p = ThingRecord.__table__.alias("p")
    stmt = (
        select(_t.c.id, _t.c.title, _rp.c.from_thing_id.label("parent_id"), _p.c.title.label("project_title"))
        .select_from(
            _t.join(_rp, (_rp.c.to_thing_id == _t.c.id) & (_rp.c.relationship_type == "parent-of"))
            .join(_p, (_p.c.id == _rp.c.from_thing_id) & (_p.c.type_hint == "project") & (_p.c.active == True))  # noqa: E712
        )
        .where(_t.c.active == True)  # noqa: E712
        .order_by(_t.c.title)
    )
    rows = session.execute(stmt).all()

    if len(rows) < 2:
        return []

    # Build a list of (id, title, project_id, project_title) for comparison
    items = [(row.id, row.title, row.parent_id, row.project_title) for row in rows]

    # Extract significant words (3+ chars, lowercased) from each title
    def _significant_words(title: str) -> set[str]:
        stop_words = {"the", "and", "for", "with", "from", "this", "that", "are", "was", "has"}
        return {w.lower() for w in re.findall(r"\b\w+\b", title) if len(w) >= 3 and w.lower() not in stop_words}

    # Compare pairs across different projects
    seen_pairs: set[tuple[str, str]] = set()
    candidates: list[SweepCandidate] = []

    for i, (id_a, title_a, proj_a, proj_title_a) in enumerate(items):
        words_a = _significant_words(title_a)
        if not words_a:
            continue
        for id_b, title_b, proj_b, proj_title_b in items[i + 1 :]:
            if proj_a == proj_b:
                continue  # same project
            pair_key = tuple(sorted([id_a, id_b]))
            if pair_key in seen_pairs:
                continue
            words_b = _significant_words(title_b)
            shared = words_a & words_b
            # Require at least 2 shared words, or 1 shared word that's 50%+ of the shorter title
            min_words = min(len(words_a), len(words_b))
            if len(shared) >= 2 or (len(shared) >= 1 and min_words <= 2):
                seen_pairs.add(pair_key)
                candidates.append(
                    SweepCandidate(
                        thing_id=id_a,
                        thing_title=title_a,
                        finding_type="cross_project_thematic_connection",
                        message=(
                            f'Thematic overlap between "{title_a}" ({proj_title_a}) '
                            f'and "{title_b}" ({proj_title_b}) — '
                            f"shared terms: {', '.join(sorted(shared))}"
                        ),
                        priority=3,
                        extra={
                            "related_thing_id": id_b,
                            "related_title": title_b,
                            "project_a": proj_title_a,
                            "project_b": proj_title_b,
                            "shared_words": sorted(shared),
                        },
                    )
                )

    return candidates


def find_cross_project_duplicate_effort(
    session: Session,
) -> list[SweepCandidate]:
    """Find tasks with near-identical titles across different projects.

    Unlike thematic connections (which find related work), this specifically
    targets cases where the same work appears to be duplicated in multiple
    projects — suggesting consolidation.
    """
    _t1 = ThingRecord.__table__.alias("t1")
    _t2 = ThingRecord.__table__.alias("t2")
    _rp1 = ThingRelationshipRecord.__table__.alias("rp1")
    _rp2 = ThingRelationshipRecord.__table__.alias("rp2")
    _p1 = ThingRecord.__table__.alias("p1")
    _p2 = ThingRecord.__table__.alias("p2")
    stmt = (
        select(
            _t1.c.id.label("id_a"),
            _t1.c.title.label("title_a"),
            _rp1.c.from_thing_id.label("proj_id_a"),
            _p1.c.title.label("proj_title_a"),
            _t2.c.id.label("id_b"),
            _t2.c.title.label("title_b"),
            _rp2.c.from_thing_id.label("proj_id_b"),
            _p2.c.title.label("proj_title_b"),
        )
        .select_from(
            _t1
            .join(_t2, (_t1.c.id < _t2.c.id) & (func.lower(func.trim(_t1.c.title)) == func.lower(func.trim(_t2.c.title))))
            .join(_rp1, (_rp1.c.to_thing_id == _t1.c.id) & (_rp1.c.relationship_type == "parent-of"))
            .join(_p1, (_p1.c.id == _rp1.c.from_thing_id) & (_p1.c.type_hint == "project") & (_p1.c.active == True))  # noqa: E712
            .join(_rp2, (_rp2.c.to_thing_id == _t2.c.id) & (_rp2.c.relationship_type == "parent-of"))
            .join(_p2, (_p2.c.id == _rp2.c.from_thing_id) & (_p2.c.type_hint == "project") & (_p2.c.active == True))  # noqa: E712
        )
        .where(
            _t1.c.active == True,  # noqa: E712
            _t2.c.active == True,  # noqa: E712
            _rp1.c.from_thing_id != _rp2.c.from_thing_id,
        )
    )
    rows = session.execute(stmt).all()

    candidates: list[SweepCandidate] = []
    for row in rows:
        candidates.append(
            SweepCandidate(
                thing_id=row.id_a,
                thing_title=row.title_a,
                finding_type="cross_project_duplicate_effort",
                message=(
                    f'Possible duplicate: "{row.title_a}" exists in both '
                    f"{row.proj_title_a} and {row.proj_title_b}"
                ),
                priority=2,
                extra={
                    "duplicate_thing_id": row.id_b,
                    "project_a": row.proj_title_a,
                    "project_b": row.proj_title_b,
                },
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Main sweep entry point
# ---------------------------------------------------------------------------


def collect_candidates(
    today: date | None = None,
    window_days: int = 7,
    stale_days: int = 14,
    user_id: str = "",
) -> list[SweepCandidate]:
    """Run all SQL candidate queries and return a combined, deduplicated list.

    This is Phase 1 of the nightly sweep. The returned candidates are intended
    to be passed to the LLM reflection phase (Phase 2).
    """
    today = today or date.today()

    with Session(_engine_mod.engine) as session:
        gap_candidates = find_information_gaps(session, today, user_id=user_id)
        # Generate and store questions on Things with gaps before collecting
        # open_questions — so newly generated questions show up in the same sweep.
        if gap_candidates:
            _generate_template_gap_questions(session, gap_candidates)
            session.commit()

        candidates = (
            find_approaching_dates(session, today, window_days, user_id=user_id)
            + find_stale_things(session, today, stale_days, user_id=user_id)
            + find_overdue_checkins(session, today)
            + find_orphan_things(session, user_id=user_id)
            + find_incomplete_things(session)
            + find_completed_projects(session, user_id=user_id)
            + find_open_questions(session, user_id=user_id)
            + gap_candidates
            + find_cross_project_shared_blockers(session)
            + find_cross_project_resource_conflicts(session, today, stale_days)
            + find_cross_project_thematic_connections(session)
            + find_cross_project_duplicate_effort(session)
        )

    # Deduplicate: keep the highest-priority (lowest number) candidate per (thing_id, finding_type)
    seen: dict[tuple[str, str], SweepCandidate] = {}
    for c in candidates:
        key = (c.thing_id, c.finding_type)
        if key not in seen or c.priority < seen[key].priority:
            seen[key] = c

    result = list(seen.values())
    result.sort(key=lambda c: (c.priority, c.thing_title))
    return result


# ---------------------------------------------------------------------------
# Phase 1.5: Dismiss stale findings before reflection
# ---------------------------------------------------------------------------


def dismiss_stale_findings(user_id: str = "") -> int:
    """Dismiss findings whose linked Thing is inactive or that have expired.

    Returns count of findings dismissed.
    """
    now = datetime.now(timezone.utc).isoformat()
    total = 0

    with Session(_engine_mod.engine) as session:
        # Dismiss findings linked to inactive Things
        inactive_thing_ids = session.exec(
            select(ThingRecord.id).where(ThingRecord.active == False)  # noqa: E712
        ).all()
        if inactive_thing_ids:
            stmt_inactive = (
                select(SweepFindingRecord)
                .where(
                    SweepFindingRecord.dismissed == False,  # noqa: E712
                    SweepFindingRecord.thing_id.is_not(None),  # type: ignore[union-attr]
                    SweepFindingRecord.thing_id.in_(inactive_thing_ids),  # type: ignore[union-attr]
                    user_filter_clause(SweepFindingRecord.user_id, user_id),
                )
            )
            for finding in session.exec(stmt_inactive).all():
                finding.dismissed = True
                total += 1

        # Dismiss expired findings
        stmt_expired = (
            select(SweepFindingRecord)
            .where(
                SweepFindingRecord.dismissed == False,  # noqa: E712
                SweepFindingRecord.expires_at.is_not(None),  # type: ignore[union-attr]
                SweepFindingRecord.expires_at < now,  # type: ignore[operator]
                user_filter_clause(SweepFindingRecord.user_id, user_id),
            )
        )
        for finding in session.exec(stmt_expired).all():
            finding.dismissed = True
            total += 1

        session.commit()

    return int(total)


def _fetch_active_findings(user_id: str = "") -> list[dict]:
    """Fetch active (non-dismissed, non-expired) findings for a user."""
    now = datetime.now(timezone.utc)
    with Session(_engine_mod.engine) as session:
        stmt = (
            select(
                SweepFindingRecord.id,
                SweepFindingRecord.thing_id,
                SweepFindingRecord.finding_type,
                SweepFindingRecord.message,
                SweepFindingRecord.priority,
                SweepFindingRecord.created_at,
                SweepFindingRecord.expires_at,
                ThingRecord.title.label("thing_title"),
            )
            .outerjoin(ThingRecord, SweepFindingRecord.thing_id == ThingRecord.id)
            .where(
                SweepFindingRecord.dismissed == False,  # noqa: E712
                user_filter_clause(SweepFindingRecord.user_id, user_id),
                or_(
                    SweepFindingRecord.expires_at.is_(None),  # type: ignore[union-attr]
                    SweepFindingRecord.expires_at > now,
                ),
            )
            .order_by(SweepFindingRecord.priority, SweepFindingRecord.created_at.desc())
        )
        rows = session.execute(stmt).all()
    return [r._asdict() for r in rows]


def _format_active_findings_for_prompt(findings: list[dict]) -> str:
    """Format active findings into a prompt section for deduplication."""
    if not findings:
        return ""

    lines = [
        "",
        "## Currently active findings (do NOT repeat these):",
    ]
    for i, f in enumerate(findings, 1):
        thing_info = f" (thing: {f['thing_title']})" if f.get("thing_title") else ""
        lines.append(
            f"{i}. [priority {f['priority']}] \"{f['message']}\"{thing_info}"
        )
    lines.append("")
    lines.append("Generate NEW insights only. Skip anything already covered above.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 2: LLM reflection
# ---------------------------------------------------------------------------

SWEEP_REFLECTION_SYSTEM = """\
You are the Nightly Sweep Analyst for Reli, an AI personal information manager.
You receive a list of candidate Things that SQL queries flagged for review.

Your job: provide nuanced, actionable reflection. Think about what the user
should know tomorrow morning. Be genuinely helpful, not generic.

Consider:
- What's truly urgent vs what can wait?
- What connections exist between items that the user might not see?
- What's been forgotten or neglected that deserves attention?
- Are there patterns (too many stale items, many orphans, etc.)?
- Cross-project patterns: shared blockers, resource conflicts, thematic
  connections, and duplicated effort across projects
- What specific action would help most right now?

Respond with ONLY valid JSON matching this schema (no markdown, no explanation):
{
  "findings": [
    {
      "thing_id": "uuid-or-null",
      "finding_type": "llm_insight",
      "message": "Concise, actionable message for the user",
      "priority": 1,
      "expires_in_days": 7
    }
  ]
}

Rules:
- finding_type MUST be "llm_insight" for all your findings
- priority: 0=critical, 1=high, 2=medium, 3=low
- expires_in_days: how long this finding stays relevant (1-30, null for no expiry)
- thing_id: link to a specific Thing when relevant, null for general observations
- message: written for the USER, not for a system. Be warm and direct.
  Good: "Your dentist appointment is tomorrow — don't forget to confirm!"
  Bad: "approaching_date detected for thing_id abc123"
- Keep findings to 3-8 items. Quality over quantity.
- Don't just repeat what the SQL queries found — add insight and connections.
- If candidates are empty or trivial, return {"findings": []} — don't fabricate.

GUARD RAILS — you MUST follow these:
- NEVER suggest deleting any Thing. You may only propose creating, updating, or reviewing.
- Your output is advisory — you create findings (observations), never modify data directly.
- When in doubt, surface information rather than recommend destructive action.
- You will be shown currently active findings. Do NOT generate findings that repeat or \
rephrase existing ones. Only add genuinely new insights.
"""


@dataclass
class ReflectionResult:
    """Result of the LLM reflection phase."""

    findings_created: int = 0
    findings: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


def _format_candidates_for_llm(candidates: list[SweepCandidate]) -> str:
    """Format candidates into a compact prompt for the LLM."""
    if not candidates:
        return "No candidates flagged by SQL queries today."

    lines = [f"Today: {date.today().isoformat()}", "", f"{len(candidates)} candidates:"]
    for i, c in enumerate(candidates, 1):
        extra_str = ""
        if c.extra:
            extra_parts = [f"{k}={v}" for k, v in c.extra.items()]
            extra_str = f" ({', '.join(extra_parts)})"
        lines.append(f"{i}. [{c.finding_type}] {c.message} [id={c.thing_id}, pri={c.priority}{extra_str}]")
    return "\n".join(lines)


async def reflect_on_candidates(
    candidates: list[SweepCandidate] | None = None,
    user_id: str = "",
) -> ReflectionResult:
    """Phase 2: Send SQL candidates to LLM for nuanced reflection.

    If *candidates* is None, runs collect_candidates() first.
    Returns a ReflectionResult with the findings created in sweep_findings.
    """
    from .agents import REQUESTY_REASONING_MODEL, UsageStats, _chat

    if candidates is None:
        candidates = collect_candidates(user_id=user_id)

    usage_stats = UsageStats()
    prompt = _format_candidates_for_llm(candidates)

    # Include active findings so the LLM avoids duplicating them
    active_findings = _fetch_active_findings(user_id)
    active_findings_section = _format_active_findings_for_prompt(active_findings)
    if active_findings_section:
        prompt += "\n" + active_findings_section

    raw = await _chat(
        messages=[
            {"role": "system", "content": SWEEP_REFLECTION_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        model=REQUESTY_REASONING_MODEL,
        response_format={"type": "json_object"},
        usage_stats=usage_stats,
    )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Sweep reflection returned invalid JSON: %s", raw[:200])
        return ReflectionResult(usage=usage_stats.to_dict())

    raw_findings = parsed.get("findings", [])
    if not isinstance(raw_findings, list):
        raw_findings = []

    now = datetime.now(timezone.utc)
    created: list[dict] = []

    # Collect valid thing_ids from candidates for validation
    valid_thing_ids = {c.thing_id for c in candidates}

    with Session(_engine_mod.engine) as session:
        for f in raw_findings:
            if not isinstance(f, dict):
                continue
            message = str(f.get("message", "")).strip()
            if not message:
                continue

            thing_id = f.get("thing_id")
            if thing_id and thing_id not in valid_thing_ids:
                thing_id = None  # don't link to unknown things

            priority = f.get("priority", 2)
            if not isinstance(priority, int) or priority < 0 or priority > 4:
                priority = 2

            expires_in = f.get("expires_in_days")
            expires_at = None
            if isinstance(expires_in, (int, float)) and 1 <= expires_in <= 30:
                expires_at = (now + timedelta(days=int(expires_in))).isoformat()

            finding_id = f"sf-{uuid.uuid4().hex[:8]}"
            session.add(SweepFindingRecord(
                id=finding_id,
                thing_id=thing_id,
                finding_type="llm_insight",
                message=message,
                priority=priority,
                dismissed=False,
                created_at=now,
                expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
                user_id=user_id or None,
            ))
            created.append(
                {
                    "id": finding_id,
                    "thing_id": thing_id,
                    "finding_type": "llm_insight",
                    "message": message,
                    "priority": priority,
                    "expires_at": expires_at,
                }
            )
        session.commit()

    return ReflectionResult(
        findings_created=len(created),
        findings=created,
        usage=usage_stats.to_dict(),
    )


# ---------------------------------------------------------------------------
# Phase 3a: Gap question generation (LLM-based)
# ---------------------------------------------------------------------------

GAP_QUESTION_SYSTEM = """\
You are a knowledge-gap analyst for Reli, an AI personal information manager.
You receive a list of Things that have been identified as incomplete — missing dates,
deadlines, details, or other key information.

Your job: for each Thing, generate 1-3 specific, actionable questions that would
fill the most important gaps. Tailor questions to the Thing's type and context.

Respond with ONLY valid JSON matching this schema (no markdown, no explanation):
{
  "things": [
    {
      "thing_id": "uuid",
      "questions": ["Question 1?", "Question 2?"]
    }
  ]
}

Rules:
- Generate 1-3 questions per Thing. Quality over quantity.
- Questions should be specific to the Thing, not generic.
- For people: ask about role, contact info, how you know them, upcoming events.
- For tasks/projects: ask about deadlines, success criteria, next steps, blockers.
- For events: ask about date, location, who's attending, preparation needed.
- For goals: ask about timeline, milestones, how to measure progress.
- Don't ask about information that's already present in the Thing's data.
- Write questions as if asking the user directly: "When is this due?" not "What is the deadline for this Thing?"
- If a Thing already has enough context to not need questions, return an empty questions list for it.
"""


@dataclass
class GapQuestionResult:
    """Result of the gap question generation phase."""

    things_updated: int = 0
    questions_generated: int = 0
    usage: dict = field(default_factory=dict)


async def generate_gap_questions(
    candidates: list[SweepCandidate] | None = None,
    user_id: str = "",
    batch_size: int = 20,
) -> GapQuestionResult:
    """Generate questions for incomplete Things via LLM and store as open_questions.

    Finds incomplete Things via SQL, sends them to an LLM for question generation,
    and writes the questions to each Thing's open_questions column.
    """
    from .agents import REQUESTY_REASONING_MODEL, UsageStats, _chat

    if candidates is None:
        with Session(_engine_mod.engine) as session:
            candidates = find_incomplete_things(session, user_id=user_id)

    if not candidates:
        return GapQuestionResult()

    # Limit batch size to avoid overly long prompts
    candidates = candidates[:batch_size]

    usage_stats = UsageStats()

    # Format candidates for the LLM
    lines = [f"Today: {date.today().isoformat()}", "", f"{len(candidates)} incomplete Things:"]
    for i, c in enumerate(candidates, 1):
        gaps = ", ".join(c.extra.get("gaps", []))
        data_keys = c.extra.get("data_key_count", 0)
        lines.append(
            f'{i}. [{c.extra.get("type_hint", "unknown")}] "{c.thing_title}" '
            f"(gaps: {gaps}, data keys: {data_keys}) [id={c.thing_id}]"
        )
    prompt = "\n".join(lines)

    raw = await _chat(
        messages=[
            {"role": "system", "content": GAP_QUESTION_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        model=REQUESTY_REASONING_MODEL,
        response_format={"type": "json_object"},
        usage_stats=usage_stats,
    )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Gap question generation returned invalid JSON: %s", raw[:200])
        return GapQuestionResult(usage=usage_stats.to_dict())

    raw_things = parsed.get("things", [])
    if not isinstance(raw_things, list):
        raw_things = []

    # Collect valid thing_ids from candidates
    valid_thing_ids = {c.thing_id for c in candidates}
    things_updated = 0
    questions_generated = 0

    with Session(_engine_mod.engine) as session:
        for item in raw_things:
            if not isinstance(item, dict):
                continue
            thing_id = item.get("thing_id")
            if not thing_id or thing_id not in valid_thing_ids:
                continue
            questions = item.get("questions", [])
            if not isinstance(questions, list) or not questions:
                continue
            # Filter to only string questions
            questions = [q for q in questions if isinstance(q, str) and q.strip()]
            if not questions:
                continue

            thing = session.get(ThingRecord, thing_id)
            if not thing:
                continue
            thing.open_questions = questions  # type: ignore[assignment]
            thing.updated_at = datetime.now(timezone.utc)
            things_updated += 1
            questions_generated += len(questions)
        session.commit()

    logger.info(
        "Gap question generation: %d things updated, %d questions generated",
        things_updated,
        questions_generated,
    )

    return GapQuestionResult(
        things_updated=things_updated,
        questions_generated=questions_generated,
        usage=usage_stats.to_dict(),
    )


# ---------------------------------------------------------------------------
# Phase 1.5: Auto task breakdown for broad Things
# ---------------------------------------------------------------------------

BREAKDOWN_SYSTEM = """You are a PA that auto-creates subtasks for broad Things.

Given a list of broad Things (trips, projects, events, goals) that have no subtasks,
return a JSON object with one key "things", an array where each element is:
{
  "thing_id": "<id from input>",
  "subtasks": ["<title1>", "<title2>", "<title3>"]  // 3-5 items max
}

Rules:
- Only include concrete, non-controversial logistical steps
- Each subtask is a single clear action ("Book flights", "Reserve accommodation")
- Do NOT include personal preferences ("Decide what to wear") or overly specific items
- 3–5 subtasks per Thing, no more
- Return only Things you have clear subtask ideas for; omit vague Things
"""


@dataclass
class BreakdownResult:
    """Result of the auto task breakdown phase."""

    things_created: int = 0
    relationships_created: int = 0
    findings_created: int = 0
    usage: dict = field(default_factory=dict)


async def auto_breakdown_broad_things(
    candidates: list[SweepCandidate] | None = None,
    user_id: str = "",
    batch_size: int = 10,
) -> BreakdownResult:
    """Detect broad Things without subtasks, auto-create child tasks via LLM.

    Phase: runs after collect_candidates, before reflect_on_candidates.
    1. Finds broad Things (project/event/goal/trip) with no active children (SQL).
    2. Asks LLM for 3-5 subtask titles per Thing.
    3. Creates each subtask as a Thing + parent-of relationship.
    4. Creates a SweepFindingRecord surfacing the action in the briefing.
    """
    from .agents import REQUESTY_REASONING_MODEL, UsageStats, _chat
    from . import tools as _tools

    if candidates is None:
        with Session(_engine_mod.engine) as session:
            candidates = find_broad_things_without_subtasks(session, user_id=user_id)

    if not candidates:
        return BreakdownResult()

    candidates = candidates[:batch_size]
    usage_stats = UsageStats()

    lines = [f"Today: {date.today().isoformat()}", "", f"{len(candidates)} broad Things:"]
    for i, c in enumerate(candidates, 1):
        lines.append(
            f'{i}. [{c.extra.get("type_hint", "unknown")}] "{c.thing_title}" [id={c.thing_id}]'
        )
    prompt = "\n".join(lines)

    raw = await _chat(
        messages=[
            {"role": "system", "content": BREAKDOWN_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        model=REQUESTY_REASONING_MODEL,
        response_format={"type": "json_object"},
        usage_stats=usage_stats,
    )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Auto-breakdown returned invalid JSON: %s", raw[:200])
        return BreakdownResult(usage=usage_stats.to_dict())

    raw_things = parsed.get("things", [])
    if not isinstance(raw_things, list):
        raw_things = []

    valid_thing_ids = {c.thing_id: c for c in candidates}
    things_created = 0
    relationships_created = 0
    findings_created = 0
    now = datetime.now(timezone.utc)

    with Session(_engine_mod.engine) as session:
        for item in raw_things:
            if not isinstance(item, dict):
                continue
            thing_id = item.get("thing_id")
            if not thing_id or thing_id not in valid_thing_ids:
                continue
            subtasks = item.get("subtasks", [])
            if not isinstance(subtasks, list) or not subtasks:
                continue
            subtasks = [s for s in subtasks if isinstance(s, str) and s.strip()][:5]
            if not subtasks:
                continue

            candidate = valid_thing_ids[thing_id]
            importance = candidate.extra.get("importance", 2)
            created_titles: list[str] = []

            for title in subtasks:
                result = _tools.create_thing(
                    title=title,
                    type_hint="task",
                    importance=importance,
                    user_id=user_id,
                )
                if "error" in result:
                    logger.warning("Failed to create subtask %r: %s", title, result["error"])
                    continue
                subtask_id = result["id"]

                rel = _tools.create_relationship(
                    from_thing_id=thing_id,
                    to_thing_id=subtask_id,
                    relationship_type="parent-of",
                    user_id=user_id,
                )
                if "error" in rel:
                    logger.warning(
                        "Failed to link subtask %r to parent %s: %s",
                        title, thing_id, rel["error"],
                    )
                    continue  # don't count an unlinked task

                things_created += 1
                if rel.get("status") != "duplicate":
                    relationships_created += 1
                created_titles.append(title)

            if created_titles:
                titles_str = ", ".join(created_titles)
                finding_id = f"sf-{uuid.uuid4().hex[:8]}"
                session.add(SweepFindingRecord(
                    id=finding_id,
                    thing_id=thing_id,
                    finding_type="broad_thing_no_subtasks",
                    message=f"I've set up {len(created_titles)} tasks for {candidate.thing_title}: {titles_str}.",
                    priority=1,
                    dismissed=False,
                    created_at=now,
                    expires_at=now + timedelta(days=14),
                    user_id=user_id or None,
                ))
                findings_created += 1

        session.commit()

    logger.info(
        "Auto-breakdown: %d things created, %d relationships, %d findings",
        things_created, relationships_created, findings_created,
    )
    return BreakdownResult(
        things_created=things_created,
        relationships_created=relationships_created,
        findings_created=findings_created,
        usage=usage_stats.to_dict(),
    )


# ---------------------------------------------------------------------------
# Phase 3b: Personality pattern aggregation
# ---------------------------------------------------------------------------


@dataclass
class BehavioralSignal:
    """A behavioral signal observed from user interactions."""

    signal_type: str  # e.g. "title_shortening", "finding_dismissal", "finding_engagement"
    description: str
    count: int = 0
    total: int = 0  # total relevant events (for ratio calculation)
    examples: list[str] = field(default_factory=list)


def collect_behavioral_signals(
    user_id: str,
    lookback_days: int = 30,
) -> list[BehavioralSignal]:
    """Collect implicit behavioral signals from recent user interactions.

    Analyzes chat_history (applied_changes) and sweep_findings (dismissals)
    to detect patterns in how the user interacts with Reli.
    """
    if not user_id:
        return []

    today = date.today()
    cutoff = (today - timedelta(days=lookback_days)).isoformat()
    signals: list[BehavioralSignal] = []

    with Session(_engine_mod.engine) as session:
        signals.extend(_detect_title_shortening(session, user_id, cutoff))
        signals.extend(_detect_finding_dismissal_patterns(session, user_id, cutoff))
        signals.extend(_detect_finding_engagement_patterns(session, user_id, cutoff))

    return [s for s in signals if s.count > 0]


def _detect_title_shortening(
    session: Session,
    user_id: str,
    cutoff: str,
) -> list[BehavioralSignal]:
    """Detect when the user consistently shortens Thing titles created by Reli.

    Looks at chat_history applied_changes for 'updated' entries that change
    titles, comparing old vs new length.
    """
    stmt = (
        select(ChatHistoryRecord.applied_changes)
        .where(
            ChatHistoryRecord.role == "assistant",
            ChatHistoryRecord.applied_changes.is_not(None),  # type: ignore[union-attr]
            ChatHistoryRecord.timestamp >= cutoff,
            user_filter_clause(ChatHistoryRecord.user_id, user_id),
        )
        .order_by(ChatHistoryRecord.timestamp.desc())
    )
    rows = session.exec(stmt).all()  # type: ignore[arg-type]

    title_updates = 0
    title_shortenings = 0
    examples: list[str] = []

    for raw in rows:
        if not raw:
            continue
        try:
            changes = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(changes, dict):
            continue

        updated = changes.get("updated", [])

        for item in updated:
            if not isinstance(item, dict):
                continue
            new_title = item.get("title")
            if not new_title:
                continue
            # Look up the original title for this Thing
            thing_id = item.get("id")
            if not thing_id:
                continue

            # We count any title update as a title modification event.
            # To detect shortening, compare with the Thing's previous title
            # stored in the DB (the current title IS the updated one, so we
            # look at chat_history for the original creation).
            title_updates += 1

    # Now check: among created Things, how many were later updated with shorter titles?
    # We query for Things that were created in the lookback period and have been
    # updated with a shorter title.
    stmt2 = (
        select(ChatHistoryRecord.applied_changes)
        .where(
            ChatHistoryRecord.role == "assistant",
            ChatHistoryRecord.applied_changes.is_not(None),  # type: ignore[union-attr]
            ChatHistoryRecord.timestamp >= cutoff,
            user_filter_clause(ChatHistoryRecord.user_id, user_id),
        )
    )
    created_rows = session.exec(stmt2).all()  # type: ignore[arg-type]

    # Build a map of thing_id -> original title (from creation)
    created_titles: dict[str, str] = {}
    updated_titles: dict[str, str] = {}

    for raw in created_rows:
        if not raw:
            continue
        try:
            changes = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(changes, dict):
            continue
        for item in changes.get("created", []):
            if isinstance(item, dict) and item.get("id") and item.get("title"):
                created_titles[item["id"]] = item["title"]
        for item in changes.get("updated", []):
            if isinstance(item, dict) and item.get("id") and item.get("title"):
                updated_titles[item["id"]] = item["title"]

    # Compare: things that were created by Reli and later had titles shortened
    for thing_id, original in created_titles.items():
        if thing_id in updated_titles:
            new = updated_titles[thing_id]
            title_updates += 1
            if len(new) < len(original):
                title_shortenings += 1
                if len(examples) < 3:
                    examples.append(f'"{original}" \u2192 "{new}"')

    signals: list[BehavioralSignal] = []
    if title_updates > 0:
        signals.append(
            BehavioralSignal(
                signal_type="title_shortening",
                description="User shortens Thing titles after Reli creates them",
                count=title_shortenings,
                total=title_updates,
                examples=examples,
            )
        )
    return signals


def _detect_finding_dismissal_patterns(
    session: Session,
    user_id: str,
    cutoff: str,
) -> list[BehavioralSignal]:
    """Detect which types of sweep findings the user consistently dismisses.

    High dismissal rates for a finding type suggest the user doesn't value
    those findings -> lower their priority in personality preferences.
    """
    stmt = (
        select(
            SweepFindingRecord.finding_type,
            func.count().label("total"),
            func.sum(case((SweepFindingRecord.dismissed == True, 1), else_=0)).label("dismissed_count"),  # noqa: E712
        )
        .where(
            SweepFindingRecord.created_at >= cutoff,
            user_filter_clause(SweepFindingRecord.user_id, user_id),
        )
        .group_by(SweepFindingRecord.finding_type)
    )
    rows = session.execute(stmt).all()

    signals: list[BehavioralSignal] = []
    for row in rows:
        finding_type = row.finding_type
        total = row.total
        dismissed = row.dismissed_count

        if total < 2:
            continue  # need enough data

        # High dismissal rate (>= 60%) signals disinterest
        if dismissed / total >= 0.6:
            signals.append(
                BehavioralSignal(
                    signal_type="finding_dismissal",
                    description=f"User dismisses most '{finding_type}' findings ({dismissed}/{total})",
                    count=dismissed,
                    total=total,
                    examples=[finding_type],
                )
            )

    return signals


def _detect_finding_engagement_patterns(
    session: Session,
    user_id: str,
    cutoff: str,
) -> list[BehavioralSignal]:
    """Detect which types of sweep findings the user consistently engages with.

    Low dismissal rates (user reads and keeps findings) suggest high value
    -> boost those areas in personality preferences.
    """
    stmt = (
        select(
            SweepFindingRecord.finding_type,
            func.count().label("total"),
            func.sum(case((SweepFindingRecord.dismissed == True, 1), else_=0)).label("dismissed_count"),  # noqa: E712
        )
        .where(
            SweepFindingRecord.created_at >= cutoff,
            user_filter_clause(SweepFindingRecord.user_id, user_id),
        )
        .group_by(SweepFindingRecord.finding_type)
    )
    rows = session.execute(stmt).all()

    signals: list[BehavioralSignal] = []
    for row in rows:
        finding_type = row.finding_type
        total = row.total
        dismissed = row.dismissed_count

        if total < 2:
            continue

        # Low dismissal rate (<= 30%) signals high engagement
        if dismissed / total <= 0.3:
            signals.append(
                BehavioralSignal(
                    signal_type="finding_engagement",
                    description=f"User engages with '{finding_type}' findings ({total - dismissed}/{total} kept)",
                    count=total - dismissed,
                    total=total,
                    examples=[finding_type],
                )
            )

    return signals


PATTERN_AGGREGATION_SYSTEM = """\
You are analyzing behavioral signals from a user's interaction history with Reli,
an AI personal information manager. Your job is to identify implicit personality
preferences that should shape how Reli communicates and behaves.

You receive behavioral signals (counts, ratios, examples) and must produce
personality pattern updates.

Respond with ONLY valid JSON matching this schema (no markdown, no explanation):
{
  "patterns": [
    {
      "pattern": "Short, actionable description of the preference",
      "confidence": "emerging|established|strong",
      "observations": 5
    }
  ]
}

Rules:
- confidence levels:
  - "emerging": 2-4 observations, tentative signal
  - "established": 5-9 observations, consistent pattern
  - "strong": 10+ observations, reliable pattern
- observations: use the actual count from signals
- pattern: written as an instruction to Reli (e.g., "Use shorter task titles",
  "Reduce staleness alert frequency", "Prioritize date-related reminders")
- Only emit patterns with genuine signal -- don't fabricate from weak data
- Return {"patterns": []} if no clear patterns emerge
- Keep to 1-5 patterns. Quality over quantity.
- Don't emit contradictory patterns (e.g., "be verbose" and "be concise")
"""


@dataclass
class PatternAggregationResult:
    """Result of the personality pattern aggregation phase."""

    patterns_updated: int = 0
    patterns: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


def _format_signals_for_llm(signals: list[BehavioralSignal]) -> str:
    """Format behavioral signals into a compact prompt for the LLM."""
    if not signals:
        return "No behavioral signals detected in the lookback period."

    lines = [f"Behavioral signals from last 30 days ({len(signals)} signals):"]
    for i, s in enumerate(signals, 1):
        ratio = f"{s.count}/{s.total}" if s.total > 0 else str(s.count)
        examples_str = f" Examples: {'; '.join(s.examples)}" if s.examples else ""
        lines.append(f"{i}. [{s.signal_type}] {s.description} (ratio: {ratio}){examples_str}")
    return "\n".join(lines)


async def aggregate_personality_patterns(
    user_id: str,
    lookback_days: int = 30,
) -> PatternAggregationResult:
    """Aggregate behavioral signals into personality preference updates.

    Collects implicit behavioral signals from user interactions and uses an LLM
    to synthesize them into personality pattern updates. Creates or updates a
    preference Thing with the aggregated patterns.
    """
    from .agents import REQUESTY_REASONING_MODEL, UsageStats, _chat

    signals = collect_behavioral_signals(user_id, lookback_days)
    if not signals:
        return PatternAggregationResult()

    usage_stats = UsageStats()
    prompt = _format_signals_for_llm(signals)

    raw = await _chat(
        messages=[
            {"role": "system", "content": PATTERN_AGGREGATION_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        model=REQUESTY_REASONING_MODEL,
        response_format={"type": "json_object"},
        usage_stats=usage_stats,
    )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Pattern aggregation returned invalid JSON: %s", raw[:200])
        return PatternAggregationResult(usage=usage_stats.to_dict())

    raw_patterns = parsed.get("patterns", [])
    if not isinstance(raw_patterns, list) or not raw_patterns:
        return PatternAggregationResult(usage=usage_stats.to_dict())

    # Validate and normalize patterns
    validated: list[dict] = []
    for p in raw_patterns:
        if not isinstance(p, dict):
            continue
        pattern_text = str(p.get("pattern", "")).strip()
        if not pattern_text:
            continue
        confidence = p.get("confidence", "emerging")
        if confidence not in ("emerging", "established", "strong"):
            confidence = "emerging"
        observations = p.get("observations", 1)
        if not isinstance(observations, int) or observations < 1:
            observations = 1
        validated.append(
            {
                "pattern": pattern_text,
                "confidence": confidence,
                "observations": observations,
            }
        )

    if not validated:
        return PatternAggregationResult(usage=usage_stats.to_dict())

    # Upsert the sweep-learned preference Thing
    _upsert_sweep_preference(user_id, validated)

    return PatternAggregationResult(
        patterns_updated=len(validated),
        patterns=validated,
        usage=usage_stats.to_dict(),
    )


_SWEEP_PREF_TITLE = "Sweep-learned personality patterns"


def _upsert_sweep_preference(user_id: str, new_patterns: list[dict]) -> None:
    """Create or update the sweep-learned preference Thing.

    Merges new patterns with existing ones:
    - Matching patterns (same text): update confidence and observations
    - New patterns: add them
    - Missing patterns (in DB but not in new): keep but decay confidence
    """
    with Session(_engine_mod.engine) as session:
        # Find existing sweep-learned preference Thing
        stmt = (
            select(ThingRecord)
            .where(
                ThingRecord.title == _SWEEP_PREF_TITLE,
                ThingRecord.type_hint == "preference",
                ThingRecord.active == True,  # noqa: E712
                user_filter_clause(ThingRecord.user_id, user_id),
            )
        )
        existing = session.exec(stmt).first()  # type: ignore[arg-type]

        if existing:
            # Merge with existing patterns
            existing_data = {}
            raw = existing.data
            if raw:
                try:
                    existing_data = json.loads(raw) if isinstance(raw, str) else raw
                except (json.JSONDecodeError, TypeError):
                    existing_data = {}

            existing_patterns = existing_data.get("patterns", []) if isinstance(existing_data, dict) else []
            merged = _merge_patterns(existing_patterns, new_patterns)

            existing.data = {"patterns": merged}
            existing.updated_at = datetime.now(timezone.utc)
        else:
            # Create new preference Thing
            now = datetime.now(timezone.utc)
            session.add(ThingRecord(
                id=f"t-sweep-{uuid.uuid4().hex[:8]}",
                title=_SWEEP_PREF_TITLE,
                type_hint="preference",
                active=True,
                data={"patterns": new_patterns},
                created_at=now,
                updated_at=now,
                user_id=user_id or None,
            ))
        session.commit()


def _merge_patterns(
    existing: list[dict],
    new: list[dict],
) -> list[dict]:
    """Merge new patterns into existing ones.

    - Matching patterns: take the higher observation count, update confidence
    - New patterns: add as-is
    - Existing-only patterns: keep but decay (reduce observations by 1, lower confidence)
    """
    # Index existing by normalized pattern text
    existing_by_text: dict[str, dict] = {}
    for p in existing:
        if isinstance(p, dict) and p.get("pattern"):
            key = p["pattern"].strip().lower()
            existing_by_text[key] = p

    new_by_text: dict[str, dict] = {}
    for p in new:
        key = p["pattern"].strip().lower()
        new_by_text[key] = p

    merged: list[dict] = []

    # Process new patterns (add or update)
    for key, p in new_by_text.items():
        if key in existing_by_text:
            old = existing_by_text[key]
            merged.append(
                {
                    "pattern": p["pattern"],
                    "confidence": p["confidence"],
                    "observations": max(
                        p.get("observations", 1),
                        old.get("observations", 1),
                    ),
                }
            )
        else:
            merged.append(p)

    # Keep existing-only patterns with decay
    _CONFIDENCE_DECAY = {"strong": "established", "established": "emerging"}
    for key, p in existing_by_text.items():
        if key not in new_by_text:
            obs = max(1, p.get("observations", 1) - 1)
            conf = p.get("confidence", "emerging")
            decayed_conf = _CONFIDENCE_DECAY.get(conf, conf)
            # Drop patterns that have fully decayed
            if obs <= 1 and decayed_conf == "emerging":
                continue
            merged.append(
                {
                    "pattern": p["pattern"],
                    "confidence": decayed_conf,
                    "observations": obs,
                }
            )

    return merged
