"""Nightly sweep — SQL candidate queries and LLM reflection.

Phase 1 (SQL): Identifies Things that may need the user's attention using cheap
SQL queries.  Phase 2 (LLM): Sends the candidate list to an LLM for nuanced
reflection, producing sweep_findings with priority and expiry.

Finding types:
  - approaching_date: Thing with a date (checkin, birthday, deadline, etc.) within 7 days
  - stale: Active Thing not updated in 14+ days
  - orphan: Active Thing with no relationships (no parent, no children, no graph edges)
  - completed_project: Project where all children are inactive but project is still active
  - open_question: Active Thing with unanswered open_questions
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
from typing import Any

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
) -> list[SweepCandidate]:
    """Find Things with dates (checkin_date or data JSON dates) within *window_days*.

    Covers both the checkin_date column and date fields stored in the data JSON.
    """
    today = today or date.today()
    cutoff = today + timedelta(days=window_days)
    candidates: list[SweepCandidate] = []

    # 1. checkin_date column (already in ISO format)
    rows = conn.execute(
        """SELECT id, title, checkin_date FROM things
           WHERE active = 1
             AND checkin_date IS NOT NULL
             AND DATE(checkin_date) BETWEEN ? AND ?""",
        (today.isoformat(), cutoff.isoformat()),
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
        """SELECT id, title, data FROM things
           WHERE active = 1
             AND data IS NOT NULL AND data != '{}' AND data != 'null'"""
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
) -> list[SweepCandidate]:
    """Find active Things not updated in *stale_days* or more."""
    today = today or date.today()
    cutoff = (today - timedelta(days=stale_days)).isoformat()
    rows = conn.execute(
        """SELECT id, title, type_hint, updated_at FROM things
           WHERE active = 1
             AND updated_at < ?
           ORDER BY updated_at ASC""",
        (cutoff,),
    ).fetchall()

    candidates: list[SweepCandidate] = []
    for row in rows:
        parsed_dt = _parse_date_value(row["updated_at"])
        days_stale = (today - parsed_dt).days if parsed_dt else stale_days
        type_label = row["type_hint"] or "Thing"
        candidates.append(
            SweepCandidate(
                thing_id=row["id"],
                thing_title=row["title"],
                finding_type="stale",
                message=f"Untouched for {days_stale}d: {row['title']}",
                priority=3,
                extra={"days_stale": days_stale, "type_hint": type_label},
            )
        )
    return candidates


def find_orphan_things(conn: sqlite3.Connection) -> list[SweepCandidate]:
    """Find active Things with no relationships (no parent, no children, no graph edges)."""
    rows = conn.execute(
        """SELECT t.id, t.title, t.type_hint FROM things t
           LEFT JOIN thing_relationships r
             ON t.id = r.from_thing_id OR t.id = r.to_thing_id
           WHERE t.active = 1
             AND t.parent_id IS NULL
             AND r.id IS NULL
           ORDER BY t.created_at DESC"""
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


def find_completed_projects(conn: sqlite3.Connection) -> list[SweepCandidate]:
    """Find active projects where all children are inactive (completed).

    A project qualifies if:
    - It's active with type_hint='project'
    - It has at least one child (via parent_id)
    - ALL of its children are inactive
    """
    rows = conn.execute(
        """SELECT p.id, p.title,
                  COUNT(c.id) AS total_children,
                  SUM(CASE WHEN c.active = 0 THEN 1 ELSE 0 END) AS inactive_children
           FROM things p
           JOIN things c ON c.parent_id = p.id
           WHERE p.active = 1
             AND p.type_hint = 'project'
           GROUP BY p.id
           HAVING total_children > 0 AND total_children = inactive_children"""
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


def find_open_questions(conn: sqlite3.Connection) -> list[SweepCandidate]:
    """Find active Things that have unanswered open_questions."""
    rows = conn.execute(
        """SELECT id, title, open_questions FROM things
           WHERE active = 1
             AND open_questions IS NOT NULL
             AND open_questions != '[]'
             AND open_questions != 'null'"""
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
# Main sweep entry point
# ---------------------------------------------------------------------------


def collect_candidates(
    today: date | None = None,
    window_days: int = 7,
    stale_days: int = 14,
) -> list[SweepCandidate]:
    """Run all SQL candidate queries and return a combined, deduplicated list.

    This is Phase 1 of the nightly sweep. The returned candidates are intended
    to be passed to the LLM reflection phase (Phase 2).
    """
    today = today or date.today()

    with db() as conn:
        candidates = (
            find_approaching_dates(conn, today, window_days)
            + find_stale_things(conn, today, stale_days)
            + find_orphan_things(conn)
            + find_completed_projects(conn)
            + find_open_questions(conn)
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
) -> ReflectionResult:
    """Phase 2: Send SQL candidates to LLM for nuanced reflection.

    If *candidates* is None, runs collect_candidates() first.
    Returns a ReflectionResult with the findings created in sweep_findings.
    """
    from .agents import UsageStats, _chat

    if candidates is None:
        candidates = collect_candidates()

    usage_stats = UsageStats()
    prompt = _format_candidates_for_llm(candidates)

    raw = await _chat(
        messages=[
            {"role": "system", "content": SWEEP_REFLECTION_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        model=None,  # uses default context model (cheapest)
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
                   (id, thing_id, finding_type, message, priority, dismissed, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, 0, ?, ?)""",
                (finding_id, thing_id, "llm_insight", message, priority, now.isoformat(), expires_at),
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


# ---------------------------------------------------------------------------
# Phase 3: Morning briefing generation
# ---------------------------------------------------------------------------

MORNING_BRIEFING_SYSTEM = """\
You are the Morning Briefing Generator for Reli, an AI personal information manager.
You receive the user's current state: active sweep findings, priorities, overdue items,
and other relevant data. Your job is to compose a concise, warm morning briefing.

Respond with ONLY valid JSON matching this schema (no markdown, no explanation):
{
  "summary": "A 1-2 sentence overview of the day ahead",
  "sections": [
    {
      "key": "priorities",
      "title": "Top Priorities",
      "items": ["Concise bullet point 1", "Concise bullet point 2"]
    },
    {
      "key": "overdue",
      "title": "Overdue",
      "items": ["Item that needs attention"]
    },
    {
      "key": "blockers",
      "title": "Blockers",
      "items": ["Something blocking progress"]
    },
    {
      "key": "findings",
      "title": "Insights",
      "items": ["Sweep insight or observation"]
    }
  ]
}

Rules:
- summary: 1-2 warm, direct sentences. Personal tone. Written for a human, not a system.
- sections: Only include sections that have content. Omit empty sections.
- items: Each item is a concise, actionable bullet (max ~80 chars).
- priorities: High-priority tasks and upcoming deadlines.
- overdue: Things past their due date or check-in date.
- blockers: Open questions, stale items blocking progress, completed projects not closed.
- findings: LLM insights from the sweep, interesting patterns.
- Keep the entire briefing scannable — total items across all sections should be 3-10.
- If there's genuinely nothing to report, return {"summary": "All clear — nothing urgent today.", "sections": []}
"""


def _collect_briefing_data(conn: sqlite3.Connection, user_id: str | None, today: date) -> dict[str, Any]:
    """Gather raw data for the morning briefing from the database."""
    now_iso = datetime.now(timezone.utc).isoformat()

    # User filter for multi-user
    uf_sql = ""
    uf_params: list[Any] = []
    if user_id:
        uf_sql = " AND user_id = ?"
        uf_params = [user_id]

    # High-priority active things (priority 1-2)
    priorities = conn.execute(
        f"""SELECT id, title, type_hint, priority, checkin_date FROM things
           WHERE active = 1 AND priority <= 2{uf_sql}
           ORDER BY priority ASC, checkin_date ASC
           LIMIT 10""",
        uf_params,
    ).fetchall()

    # Overdue items (checkin_date in the past)
    overdue = conn.execute(
        f"""SELECT id, title, type_hint, checkin_date FROM things
           WHERE active = 1 AND checkin_date IS NOT NULL AND DATE(checkin_date) < ?{uf_sql}
           ORDER BY checkin_date ASC
           LIMIT 10""",
        [today.isoformat(), *uf_params],
    ).fetchall()

    # Active sweep findings (not dismissed, not expired, not snoozed)
    findings = conn.execute(
        f"""SELECT id, finding_type, message, priority FROM sweep_findings
           WHERE dismissed = 0
             AND (expires_at IS NULL OR expires_at > ?)
             AND (snoozed_until IS NULL OR snoozed_until <= ?){uf_sql.replace('user_id', 'sweep_findings.user_id')}
           ORDER BY priority ASC
           LIMIT 10""",
        [now_iso, now_iso, *uf_params],
    ).fetchall()

    # Open questions / stale items as blockers
    blockers = conn.execute(
        f"""SELECT id, title, open_questions FROM things
           WHERE active = 1
             AND open_questions IS NOT NULL
             AND open_questions != '[]'
             AND open_questions != 'null'{uf_sql}
           ORDER BY priority ASC
           LIMIT 5""",
        uf_params,
    ).fetchall()

    return {
        "priorities": [dict(r) for r in priorities],
        "overdue": [dict(r) for r in overdue],
        "findings": [dict(r) for r in findings],
        "blockers": [dict(r) for r in blockers],
    }


def _format_briefing_data_for_llm(data: dict[str, Any], today: date) -> str:
    """Format briefing data into a compact prompt for the LLM."""
    lines = [f"Today: {today.isoformat()}", ""]

    if data["priorities"]:
        lines.append(f"HIGH PRIORITY ({len(data['priorities'])} items):")
        for r in data["priorities"]:
            checkin = f" [due: {r['checkin_date']}]" if r.get("checkin_date") else ""
            lines.append(f"  - P{r['priority']}: {r['title']} ({r['type_hint'] or 'thing'}){checkin}")
    else:
        lines.append("HIGH PRIORITY: none")

    if data["overdue"]:
        lines.append(f"\nOVERDUE ({len(data['overdue'])} items):")
        for r in data["overdue"]:
            lines.append(f"  - {r['title']} (was due: {r['checkin_date']})")
    else:
        lines.append("\nOVERDUE: none")

    if data["blockers"]:
        lines.append(f"\nOPEN QUESTIONS / BLOCKERS ({len(data['blockers'])} items):")
        for r in data["blockers"]:
            try:
                qs = json.loads(r["open_questions"]) if isinstance(r["open_questions"], str) else r["open_questions"]
                q_preview = qs[0][:60] + "..." if qs and len(qs[0]) > 60 else (qs[0] if qs else "")
            except (json.JSONDecodeError, TypeError, IndexError):
                q_preview = ""
            lines.append(f"  - {r['title']}: {q_preview}")
    else:
        lines.append("\nBLOCKERS: none")

    if data["findings"]:
        lines.append(f"\nSWEEP FINDINGS ({len(data['findings'])} items):")
        for r in data["findings"]:
            lines.append(f"  - [{r['finding_type']}] {r['message']}")
    else:
        lines.append("\nSWEEP FINDINGS: none")

    return "\n".join(lines)


async def generate_morning_briefing(
    user_id: str | None = None,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Generate a morning briefing for the given user and store it in the DB.

    Returns the briefing dict on success, None if no data to brief on.
    """
    from .agents import UsageStats, _chat

    today = today or date.today()

    # Check user's briefing preferences
    prefs = _get_briefing_preferences(user_id)

    with db() as conn:
        data = _collect_briefing_data(conn, user_id, today)

    # Filter sections based on preferences
    if not prefs.get("include_priorities", True):
        data["priorities"] = []
    if not prefs.get("include_overdue", True):
        data["overdue"] = []
    if not prefs.get("include_blockers", True):
        data["blockers"] = []
    if not prefs.get("include_findings", True):
        data["findings"] = []

    # If there's nothing to brief on, skip
    total_items = sum(len(v) for v in data.values())
    if total_items == 0:
        logger.info("Morning briefing: no data to brief on, skipping")
        return None

    usage_stats = UsageStats()
    prompt = _format_briefing_data_for_llm(data, today)

    raw = await _chat(
        messages=[
            {"role": "system", "content": MORNING_BRIEFING_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        model=None,
        response_format={"type": "json_object"},
        usage_stats=usage_stats,
    )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Morning briefing LLM returned invalid JSON: %s", raw[:200])
        return None

    summary = str(parsed.get("summary", "")).strip()
    sections = parsed.get("sections", [])
    if not isinstance(sections, list):
        sections = []

    # Validate sections
    valid_sections = []
    for s in sections:
        if not isinstance(s, dict):
            continue
        key = str(s.get("key", "")).strip()
        title = str(s.get("title", "")).strip()
        items = s.get("items", [])
        if key and title and isinstance(items, list) and items:
            valid_sections.append({
                "key": key,
                "title": title,
                "items": [str(i).strip() for i in items if str(i).strip()],
            })

    if not summary and not valid_sections:
        logger.info("Morning briefing: LLM returned empty briefing")
        return None

    briefing_id = f"mb-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    with db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO morning_briefings
               (id, user_id, briefing_date, summary, sections, generated_at, read_at, dismissed)
               VALUES (?, ?, ?, ?, ?, ?, NULL, 0)""",
            (
                briefing_id,
                user_id,
                today.isoformat(),
                summary,
                json.dumps(valid_sections),
                now.isoformat(),
            ),
        )

    result = {
        "id": briefing_id,
        "briefing_date": today.isoformat(),
        "summary": summary,
        "sections": valid_sections,
        "generated_at": now.isoformat(),
        "read_at": None,
        "dismissed": False,
    }

    logger.info(
        "Morning briefing generated: %s (%d sections, usage: %s)",
        briefing_id,
        len(valid_sections),
        usage_stats.to_dict(),
    )
    return result


def _get_briefing_preferences(user_id: str | None) -> dict[str, bool]:
    """Read briefing preferences from user_settings."""
    if not user_id:
        return {}
    prefs: dict[str, bool] = {}
    with db() as conn:
        rows = conn.execute(
            "SELECT key, value FROM user_settings WHERE user_id = ? AND key LIKE 'briefing_%'",
            (user_id,),
        ).fetchall()
    for row in rows:
        key = row["key"]
        val = row["value"]
        if key.startswith("briefing_"):
            prefs[key.replace("briefing_", "include_")] = val.lower() not in ("false", "0", "no")
    return prefs
