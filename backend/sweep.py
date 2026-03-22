"""Nightly sweep — SQL candidate queries and LLM reflection.

Phase 1 (SQL): Identifies Things that may need the user's attention using cheap
SQL queries.  Phase 2 (LLM): Sends the candidate list to an LLM for nuanced
reflection, producing sweep_findings with priority and expiry.

Finding types:
  - approaching_date: Thing with a date (checkin, birthday, deadline, etc.) within 7 days
  - stale: Active Thing not updated in the configured threshold (low priority, no pending work)
  - neglected: Active Thing not updated AND high-priority or has pending children
  - overdue_checkin: Active Thing whose checkin_date is in the past (beyond grace period)
  - orphan: Active Thing with no relationships (no parent, no children, no graph edges)
  - completed_project: Project where all children are inactive but project is still active
  - open_question: Active Thing with unanswered open_questions
  - cross_project_shared_blocker: Thing that blocks tasks in multiple projects
  - cross_project_resource_conflict: Person/entity involved in multiple stale projects
  - cross_project_thematic_connection: Similar Things across different projects
  - cross_project_duplicate_effort: Tasks with near-identical titles in different projects
  - personality_pattern: Implicit user preference detected from interaction history
  - llm_insight: LLM-generated finding from reflection phase
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .auth import user_filter
from .database import db

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
    conn: sqlite3.Connection,
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
    uf_sql, uf_params = user_filter(user_id)

    # 1. checkin_date column (already in ISO format)
    rows = conn.execute(
        f"""SELECT id, title, checkin_date FROM things
           WHERE active = 1
             AND checkin_date IS NOT NULL
             AND DATE(checkin_date) BETWEEN ? AND ?{uf_sql}""",
        (today.isoformat(), cutoff.isoformat(), *uf_params),
    ).fetchall()
    for row in rows:
        parsed = _parse_date_value(row["checkin_date"])
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
                    thing_id=row["id"],
                    thing_title=row["title"],
                    finding_type="approaching_date",
                    message=f"{label}: {row['title']}",
                    priority=1 if days <= 1 else 2,
                    extra={"date_key": "checkin_date", "days_away": days},
                )
            )

    # 2. Date fields in the data JSON
    data_rows = conn.execute(
        f"""SELECT id, title, data FROM things
           WHERE active = 1
             AND data IS NOT NULL AND data != '{{}}' AND data != 'null'{uf_sql}""",
        uf_params,
    ).fetchall()
    for row in data_rows:
        try:
            data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
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
                        thing_id=row["id"],
                        thing_title=row["title"],
                        finding_type="approaching_date",
                        message=f"{reason}: {row['title']}",
                        priority=1 if days <= 1 else 2,
                        extra={"date_key": key, "days_away": days},
                    )
                )

    return candidates


def find_stale_things(
    conn: sqlite3.Connection,
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
    uf_sql, uf_params = user_filter(user_id)
    rows = conn.execute(
        f"""SELECT t.id, t.title, t.type_hint, t.updated_at, t.priority,
                  t.checkin_date,
                  (SELECT COUNT(*) FROM things c WHERE c.parent_id = t.id AND c.active = 1) AS active_children
           FROM things t
           WHERE t.active = 1
             AND t.updated_at < ?{uf_sql}
           ORDER BY t.updated_at ASC""",
        (cutoff, *uf_params),
    ).fetchall()

    candidates: list[SweepCandidate] = []
    for row in rows:
        parsed_dt = _parse_date_value(row["updated_at"])
        days_stale = (today - parsed_dt).days if parsed_dt else stale_days
        type_label = row["type_hint"] or "Thing"
        priority_val = row["priority"] or 3
        active_children = row["active_children"] or 0

        # Distinguish neglected (high-priority or has pending work) from plain stale
        is_neglected = priority_val <= 2 or active_children > 0
        finding_type = "neglected" if is_neglected else "stale"

        if is_neglected:
            parts = []
            if priority_val <= 2:
                parts.append("high-priority")
            if active_children > 0:
                parts.append(f"{active_children} pending subtask{'s' if active_children != 1 else ''}")
            context = ", ".join(parts)
            message = f"Neglected for {days_stale}d ({context}): {row['title']}"
            pri = 2  # higher urgency for neglected items
        else:
            message = f"Untouched for {days_stale}d: {row['title']}"
            pri = 3

        candidates.append(
            SweepCandidate(
                thing_id=row["id"],
                thing_title=row["title"],
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
    conn: sqlite3.Connection,
    today: date | None = None,
    grace_days: int = 1,
) -> list[SweepCandidate]:
    """Find active Things with overdue checkin_date (past the grace period).

    Things whose checkin_date is today or within *grace_days* are handled by
    ``find_approaching_dates``; this catches items that have been overdue longer.
    """
    today = today or date.today()
    cutoff = (today - timedelta(days=grace_days)).isoformat()
    rows = conn.execute(
        """SELECT id, title, type_hint, checkin_date, priority FROM things
           WHERE active = 1
             AND checkin_date IS NOT NULL
             AND DATE(checkin_date) < ?
           ORDER BY checkin_date ASC""",
        (cutoff,),
    ).fetchall()

    candidates: list[SweepCandidate] = []
    for row in rows:
        parsed = _parse_date_value(row["checkin_date"])
        if not parsed:
            continue
        days_overdue = (today - parsed).days
        priority_val = row["priority"] or 3
        pri = 1 if days_overdue >= 7 or priority_val <= 2 else 2
        candidates.append(
            SweepCandidate(
                thing_id=row["id"],
                thing_title=row["title"],
                finding_type="overdue_checkin",
                message=f"Check-in overdue by {days_overdue}d: {row['title']}",
                priority=pri,
                extra={
                    "days_overdue": days_overdue,
                    "type_hint": row["type_hint"] or "Thing",
                },
            )
        )
    return candidates


def find_orphan_things(conn: sqlite3.Connection, user_id: str = "") -> list[SweepCandidate]:
    """Find active Things with no relationships (no parent, no children, no graph edges)."""
    uf_sql, uf_params = user_filter(user_id, "t")
    rows = conn.execute(
        f"""SELECT t.id, t.title, t.type_hint FROM things t
           LEFT JOIN thing_relationships r
             ON t.id = r.from_thing_id OR t.id = r.to_thing_id
           WHERE t.active = 1
             AND t.parent_id IS NULL
             AND r.id IS NULL{uf_sql}
           ORDER BY t.created_at DESC""",
        uf_params,
    ).fetchall()

    candidates: list[SweepCandidate] = []
    for row in rows:
        candidates.append(
            SweepCandidate(
                thing_id=row["id"],
                thing_title=row["title"],
                finding_type="orphan",
                message=f"No connections: {row['title']}",
                priority=3,
                extra={"type_hint": row["type_hint"] or "Thing"},
            )
        )
    return candidates


def find_completed_projects(conn: sqlite3.Connection, user_id: str = "") -> list[SweepCandidate]:
    """Find active projects where all children are inactive (completed).

    A project qualifies if:
    - It's active with type_hint='project'
    - It has at least one child (via parent_id)
    - ALL of its children are inactive
    """
    uf_sql, uf_params = user_filter(user_id, "p")
    rows = conn.execute(
        f"""SELECT p.id, p.title,
                  COUNT(c.id) AS total_children,
                  SUM(CASE WHEN c.active = 0 THEN 1 ELSE 0 END) AS inactive_children
           FROM things p
           JOIN things c ON c.parent_id = p.id
           WHERE p.active = 1
             AND p.type_hint = 'project'{uf_sql}
           GROUP BY p.id
           HAVING total_children > 0 AND total_children = inactive_children""",
        uf_params,
    ).fetchall()

    candidates: list[SweepCandidate] = []
    for row in rows:
        n = row["total_children"]
        candidates.append(
            SweepCandidate(
                thing_id=row["id"],
                thing_title=row["title"],
                finding_type="completed_project",
                message=f"All {n} tasks done — still active: {row['title']}",
                priority=2,
                extra={"total_children": n},
            )
        )
    return candidates


def find_open_questions(conn: sqlite3.Connection, user_id: str = "") -> list[SweepCandidate]:
    """Find active Things that have unanswered open_questions."""
    uf_sql, uf_params = user_filter(user_id)
    rows = conn.execute(
        f"""SELECT id, title, open_questions FROM things
           WHERE active = 1
             AND open_questions IS NOT NULL
             AND open_questions != '[]'
             AND open_questions != 'null'{uf_sql}""",
        uf_params,
    ).fetchall()

    candidates: list[SweepCandidate] = []
    for row in rows:
        try:
            raw = row["open_questions"]
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
                thing_id=row["id"],
                thing_title=row["title"],
                finding_type="open_question",
                message=f"{n} unanswered question{'s' if n != 1 else ''}: {row['title']}",
                priority=2,
                extra={"question_count": n, "first_question": preview},
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Cross-project pattern detection (#sweep-finding)
# ---------------------------------------------------------------------------


def find_cross_project_shared_blockers(conn: sqlite3.Connection) -> list[SweepCandidate]:
    """Find Things that block active tasks in multiple projects.

    A "shared blocker" is a Thing connected (via relationships) to active tasks
    in 2+ different projects. This means one Thing's resolution would unblock
    progress across multiple projects.
    """
    # Find Things that have "blocks" or similar relationships to tasks in
    # different projects.  We look for Things connected to children of
    # different projects via typed edges.
    rows = conn.execute(
        """SELECT blocker.id        AS blocker_id,
                  blocker.title     AS blocker_title,
                  COUNT(DISTINCT p.id) AS project_count,
                  GROUP_CONCAT(DISTINCT p.title) AS project_titles
           FROM things blocker
           JOIN thing_relationships r
             ON blocker.id = r.from_thing_id OR blocker.id = r.to_thing_id
           JOIN things task
             ON task.id = CASE
                  WHEN blocker.id = r.from_thing_id THEN r.to_thing_id
                  ELSE r.from_thing_id
                END
           JOIN things p
             ON task.parent_id = p.id
             AND p.type_hint = 'project'
             AND p.active = 1
           WHERE blocker.active = 1
             AND task.active = 1
             AND r.relationship_type IN ('blocks', 'blocked_by', 'depends_on', 'dependency')
           GROUP BY blocker.id
           HAVING project_count >= 2"""
    ).fetchall()

    candidates: list[SweepCandidate] = []
    for row in rows:
        projects = row["project_titles"]
        candidates.append(
            SweepCandidate(
                thing_id=row["blocker_id"],
                thing_title=row["blocker_title"],
                finding_type="cross_project_shared_blocker",
                message=(f"Blocks tasks in {row['project_count']} projects ({projects}): {row['blocker_title']}"),
                priority=1,
                extra={
                    "project_count": row["project_count"],
                    "project_titles": projects,
                },
            )
        )
    return candidates


def find_cross_project_resource_conflicts(
    conn: sqlite3.Connection,
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

    rows = conn.execute(
        """SELECT person.id          AS person_id,
                  person.title       AS person_title,
                  COUNT(DISTINCT p.id) AS project_count,
                  GROUP_CONCAT(DISTINCT p.title) AS project_titles,
                  SUM(CASE WHEN task.updated_at < ? THEN 1 ELSE 0 END) AS stale_tasks
           FROM things person
           JOIN thing_relationships r
             ON person.id = r.from_thing_id OR person.id = r.to_thing_id
           JOIN things task
             ON task.id = CASE
                  WHEN person.id = r.from_thing_id THEN r.to_thing_id
                  ELSE r.from_thing_id
                END
           JOIN things p
             ON task.parent_id = p.id
             AND p.type_hint = 'project'
             AND p.active = 1
           WHERE person.active = 1
             AND person.type_hint = 'person'
             AND task.active = 1
           GROUP BY person.id
           HAVING project_count >= 2 AND stale_tasks > 0""",
        (stale_cutoff,),
    ).fetchall()

    candidates: list[SweepCandidate] = []
    for row in rows:
        candidates.append(
            SweepCandidate(
                thing_id=row["person_id"],
                thing_title=row["person_title"],
                finding_type="cross_project_resource_conflict",
                message=(
                    f"{row['person_title']} is involved in {row['project_count']} projects "
                    f"with {row['stale_tasks']} stale task(s): {row['project_titles']}"
                ),
                priority=2,
                extra={
                    "project_count": row["project_count"],
                    "project_titles": row["project_titles"],
                    "stale_tasks": row["stale_tasks"],
                },
            )
        )
    return candidates


def find_cross_project_thematic_connections(
    conn: sqlite3.Connection,
) -> list[SweepCandidate]:
    """Find active Things with similar titles across different projects.

    Uses SQL LIKE matching to find tasks whose titles share significant words
    (3+ chars) across different project hierarchies. This helps identify
    thematic connections or potential collaboration opportunities.
    """
    # Get all active tasks that belong to a project (via parent_id)
    rows = conn.execute(
        """SELECT t.id, t.title, t.parent_id, p.title AS project_title
           FROM things t
           JOIN things p ON t.parent_id = p.id AND p.type_hint = 'project' AND p.active = 1
           WHERE t.active = 1
           ORDER BY t.title"""
    ).fetchall()

    if len(rows) < 2:
        return []

    # Build a list of (id, title, parent_id, project_title) for comparison
    items = [(row["id"], row["title"], row["parent_id"], row["project_title"]) for row in rows]

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
    conn: sqlite3.Connection,
) -> list[SweepCandidate]:
    """Find tasks with near-identical titles across different projects.

    Unlike thematic connections (which find related work), this specifically
    targets cases where the same work appears to be duplicated in multiple
    projects — suggesting consolidation.
    """
    rows = conn.execute(
        """SELECT t1.id       AS id_a,
                  t1.title    AS title_a,
                  t1.parent_id AS proj_id_a,
                  p1.title    AS proj_title_a,
                  t2.id       AS id_b,
                  t2.title    AS title_b,
                  t2.parent_id AS proj_id_b,
                  p2.title    AS proj_title_b
           FROM things t1
           JOIN things t2
             ON t1.id < t2.id
             AND LOWER(TRIM(t1.title)) = LOWER(TRIM(t2.title))
           JOIN things p1
             ON t1.parent_id = p1.id AND p1.type_hint = 'project' AND p1.active = 1
           JOIN things p2
             ON t2.parent_id = p2.id AND p2.type_hint = 'project' AND p2.active = 1
           WHERE t1.active = 1
             AND t2.active = 1
             AND t1.parent_id != t2.parent_id"""
    ).fetchall()

    candidates: list[SweepCandidate] = []
    for row in rows:
        candidates.append(
            SweepCandidate(
                thing_id=row["id_a"],
                thing_title=row["title_a"],
                finding_type="cross_project_duplicate_effort",
                message=(
                    f'Possible duplicate: "{row["title_a"]}" exists in both '
                    f"{row['proj_title_a']} and {row['proj_title_b']}"
                ),
                priority=2,
                extra={
                    "duplicate_thing_id": row["id_b"],
                    "project_a": row["proj_title_a"],
                    "project_b": row["proj_title_b"],
                },
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Personality pattern aggregation
# ---------------------------------------------------------------------------


def aggregate_personality_patterns(
    conn: sqlite3.Connection,
    today: date | None = None,
    lookback_days: int = 30,
    user_id: str = "",
) -> list[SweepCandidate]:
    """Analyze recent interactions for implicit personality/preference patterns.

    Detects three patterns from chat history and sweep finding interactions:
      - title_brevity: user frequently creates/updates short titles (Reli too verbose)
      - staleness_fatigue: user dismisses most stale/neglected findings (reduce priority)
      - date_engagement: user preferentially acts on date-related Things (boost dates)

    Returns personality_pattern candidates for LLM reflection.
    """
    today = today or date.today()
    cutoff = (today - timedelta(days=lookback_days)).isoformat()
    uf_sql, uf_params = user_filter(user_id)
    candidates: list[SweepCandidate] = []

    # --- Load applied_changes from recent assistant messages ---
    change_rows = conn.execute(
        f"""SELECT applied_changes FROM chat_history
           WHERE role = 'assistant'
             AND applied_changes IS NOT NULL
             AND applied_changes != '{{}}'
             AND applied_changes != 'null'
             AND timestamp >= ?{uf_sql}""",
        (cutoff, *uf_params),
    ).fetchall()

    parsed_changes: list[dict] = []
    for row in change_rows:
        try:
            raw = row["applied_changes"]
            changes = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(changes, dict):
            parsed_changes.append(changes)

    # --- Pattern 1: Title brevity ---
    title_lengths: list[int] = []
    for changes in parsed_changes:
        for thing in changes.get("updated", []) + changes.get("created", []):
            if isinstance(thing, dict) and "title" in thing:
                title_lengths.append(len(thing["title"].split()))

    if len(title_lengths) >= 5:
        avg_words = sum(title_lengths) / len(title_lengths)
        short_count = sum(1 for length in title_lengths if length <= 3)
        short_ratio = short_count / len(title_lengths)
        if short_ratio >= 0.6:
            candidates.append(
                SweepCandidate(
                    thing_id="_pattern_brevity",
                    thing_title="Personality Pattern",
                    finding_type="personality_pattern",
                    message=(
                        f"You tend to keep titles concise ({short_count}/{len(title_lengths)} "
                        f"are 3 words or fewer, avg {avg_words:.1f} words). "
                        "Reli will aim for shorter, punchier titles."
                    ),
                    priority=3,
                    extra={
                        "pattern": "title_brevity",
                        "avg_words": round(avg_words, 1),
                        "short_ratio": round(short_ratio, 2),
                    },
                )
            )

    # --- Pattern 2: Staleness dismissal fatigue ---
    stale_row = conn.execute(
        f"""SELECT COUNT(*) AS total,
                  SUM(CASE WHEN dismissed = 1 THEN 1 ELSE 0 END) AS dismissed_count
           FROM sweep_findings
           WHERE finding_type IN ('stale', 'neglected')
             AND created_at >= ?{uf_sql}""",
        (cutoff, *uf_params),
    ).fetchone()

    if stale_row and stale_row["total"] and stale_row["total"] >= 5:
        total = stale_row["total"]
        dismissed = stale_row["dismissed_count"] or 0
        dismiss_rate = dismissed / total
        if dismiss_rate >= 0.6:
            candidates.append(
                SweepCandidate(
                    thing_id="_pattern_staleness",
                    thing_title="Personality Pattern",
                    finding_type="personality_pattern",
                    message=(
                        f"You've dismissed {dismissed}/{total} staleness alerts recently. "
                        "Consider increasing your stale threshold or reducing staleness alert priority."
                    ),
                    priority=3,
                    extra={
                        "pattern": "staleness_fatigue",
                        "dismiss_rate": round(dismiss_rate, 2),
                        "total": total,
                        "dismissed": dismissed,
                    },
                )
            )

    # --- Pattern 3: Date engagement ---
    date_thing_ids: set[str] = set()
    non_date_thing_ids: set[str] = set()

    for changes in parsed_changes:
        for thing in changes.get("updated", []):
            if not isinstance(thing, dict) or "id" not in thing:
                continue
            tid = thing["id"]
            has_date = bool(thing.get("checkin_date"))
            if not has_date:
                data = thing.get("data")
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except (json.JSONDecodeError, TypeError):
                        data = {}
                if isinstance(data, dict):
                    has_date = any(
                        k.lower().replace(" ", "_") in _ALL_DATE_KEYS for k in data
                    )
            if has_date:
                date_thing_ids.add(tid)
            else:
                non_date_thing_ids.add(tid)

    # Only count Things that are exclusively in one category
    date_only = date_thing_ids - non_date_thing_ids
    non_date_only = non_date_thing_ids - date_thing_ids
    total_acted = len(date_only) + len(non_date_only)

    if total_acted >= 5:
        date_ratio = len(date_only) / total_acted
        if date_ratio >= 0.6:
            candidates.append(
                SweepCandidate(
                    thing_id="_pattern_dates",
                    thing_title="Personality Pattern",
                    finding_type="personality_pattern",
                    message=(
                        f"You consistently act on date-related items "
                        f"({len(date_only)}/{total_acted} recent updates). "
                        "Boosting date awareness in your briefings."
                    ),
                    priority=3,
                    extra={
                        "pattern": "date_engagement",
                        "date_ratio": round(date_ratio, 2),
                        "date_things": len(date_only),
                        "total_acted": total_acted,
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

    with db() as conn:
        candidates = (
            find_approaching_dates(conn, today, window_days, user_id=user_id)
            + find_stale_things(conn, today, stale_days, user_id=user_id)
            + find_overdue_checkins(conn, today)
            + find_orphan_things(conn, user_id=user_id)
            + find_completed_projects(conn, user_id=user_id)
            + find_open_questions(conn, user_id=user_id)
            + find_cross_project_shared_blockers(conn)
            + find_cross_project_resource_conflicts(conn, today, stale_days)
            + find_cross_project_thematic_connections(conn)
            + find_cross_project_duplicate_effort(conn)
            + aggregate_personality_patterns(conn, today, user_id=user_id)
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

    with db() as conn:
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
            conn.execute(
                """INSERT INTO sweep_findings
                   (id, thing_id, finding_type, message, priority, dismissed, created_at, expires_at, user_id)
                   VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)""",
                (finding_id, thing_id, "llm_insight", message, priority, now.isoformat(), expires_at, user_id or None),
            )
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

    return ReflectionResult(
        findings_created=len(created),
        findings=created,
        usage=usage_stats.to_dict(),
    )
