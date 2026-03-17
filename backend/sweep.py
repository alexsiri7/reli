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
# Phase 3: Learning generation (FR-102)
# ---------------------------------------------------------------------------

LEARNING_GENERATION_SYSTEM = """\
You are the Learning Analyst for Reli, an AI personal information manager.
You review recent conversation history and existing Things to identify patterns,
preferences, habits, and observations about the user.

Your job: distill the user's conversations into concise learnings — things Reli
has observed about how the user thinks, works, or lives. These become permanent
knowledge that helps Reli serve the user better over time.

Examples of good learnings:
- "Alex prefers to break down work projects into small tasks before starting"
- "Alex's approach to party planning is detail-oriented and starts weeks early"
- "Alex tends to defer health-related tasks repeatedly"
- "Alex values morning routines and plans around early meetings"

Respond with ONLY valid JSON matching this schema (no markdown, no explanation):
{
  "learnings": [
    {
      "title": "Short, descriptive title of the learning",
      "notes": "Detailed observation with supporting evidence from conversations",
      "tags": ["learning"],
      "related_thing_titles": ["Existing Thing titles this learning relates to"]
    }
  ]
}

Rules:
- Each learning MUST be about the USER — their behavior, preferences, or patterns
- tags: always include "learning". Add "user-pattern" for behavioral patterns
- title: concise, reads as an observation (e.g. "Alex prefers morning meetings")
- notes: 1-3 sentences explaining what was observed and why it matters
- related_thing_titles: titles of existing Things this learning connects to
  (people, projects, concepts, etc.). Empty list if none.
- Return 0-5 learnings per sweep. Quality over quantity.
- Do NOT repeat learnings that already exist (check the existing learnings list).
- Do NOT fabricate — only create learnings supported by conversation evidence.
- If there's nothing new to learn, return {"learnings": []}
"""


@dataclass
class LearningResult:
    """Result of the learning generation phase."""

    learnings_created: int = 0
    learnings: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


def _fetch_recent_conversations(
    conn: sqlite3.Connection,
    days: int = 7,
    user_id: str = "",
) -> list[dict]:
    """Fetch recent user messages from chat_history for learning extraction."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    params: list = [cutoff]
    uf = ""
    if user_id:
        uf = " AND user_id = ?"
        params.append(user_id)
    rows = conn.execute(
        f"""SELECT role, content, timestamp FROM chat_history
           WHERE role = 'user' AND timestamp > ?{uf}
           ORDER BY timestamp DESC LIMIT 50""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_existing_learnings(
    conn: sqlite3.Connection,
    user_id: str = "",
) -> list[dict]:
    """Fetch existing learning Things to avoid duplicates."""
    params: list = []
    uf = ""
    if user_id:
        uf = " AND user_id = ?"
        params.append(user_id)
    rows = conn.execute(
        f"""SELECT id, title, data FROM things
           WHERE type_hint = 'learning' AND active = 1{uf}""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def _format_learning_prompt(
    conversations: list[dict],
    existing_learnings: list[dict],
    things: list[dict],
) -> str:
    """Format conversation history and context for the learning LLM."""
    lines = [f"Today: {date.today().isoformat()}", ""]

    if existing_learnings:
        lines.append(f"Existing learnings ({len(existing_learnings)}):")
        for lg in existing_learnings:
            lines.append(f"  - {lg['title']}")
        lines.append("")

    if things:
        lines.append(f"User's Things ({len(things)}):")
        for t in things[:30]:
            lines.append(f"  - [{t.get('type_hint', 'thing')}] {t['title']}")
        lines.append("")

    if conversations:
        lines.append(f"Recent conversations ({len(conversations)} messages):")
        for c in conversations:
            content = c["content"][:300]
            lines.append(f"  [{c.get('timestamp', '')}] {content}")
    else:
        lines.append("No recent conversations.")

    return "\n".join(lines)


async def generate_learnings(
    user_id: str = "",
    days: int = 7,
) -> LearningResult:
    """Phase 3: Analyze conversations to generate Learning Things.

    Reads recent chat history, identifies user patterns and preferences,
    creates Learning Things tagged with #learning, and connects them to
    the User Thing via LearnedAbout relationships and to relevant domain Things.

    This should ONLY be called from the nightly sweep, not during real-time chat.
    """
    from .agents import UsageStats, _chat

    usage_stats = UsageStats()

    with db() as conn:
        conversations = _fetch_recent_conversations(conn, days, user_id)
        existing_learnings = _fetch_existing_learnings(conn, user_id)
        things = conn.execute(
            "SELECT id, title, type_hint, data FROM things WHERE active = 1"
            + (" AND user_id = ?" if user_id else ""),
            ([user_id] if user_id else []),
        ).fetchall()
        things_list = [dict(r) for r in things]

    if not conversations:
        logger.info("No recent conversations for learning generation")
        return LearningResult(usage=usage_stats.to_dict())

    prompt = _format_learning_prompt(conversations, existing_learnings, things_list)

    raw = await _chat(
        messages=[
            {"role": "system", "content": LEARNING_GENERATION_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        model=None,
        response_format={"type": "json_object"},
        usage_stats=usage_stats,
    )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Learning generation returned invalid JSON: %s", raw[:200])
        return LearningResult(usage=usage_stats.to_dict())

    raw_learnings = parsed.get("learnings", [])
    if not isinstance(raw_learnings, list):
        raw_learnings = []

    now = datetime.now(timezone.utc).isoformat()
    created: list[dict] = []

    with db() as conn:
        # Find user Thing for LearnedAbout relationships
        user_thing_row = conn.execute(
            "SELECT id FROM things WHERE type_hint = 'person' AND surface = 0"
            + (" AND user_id = ?" if user_id else "")
            + " LIMIT 1",
            ([user_id] if user_id else []),
        ).fetchone()
        user_thing_id = user_thing_row["id"] if user_thing_row else None

        # Build title→id lookup for linking related Things
        title_lookup: dict[str, str] = {}
        for t in things_list:
            title_lookup[t["title"].lower()] = t["id"]

        for learning in raw_learnings:
            if not isinstance(learning, dict):
                continue
            title = str(learning.get("title", "")).strip()
            if not title:
                continue

            # Skip duplicates by title
            existing_titles = {lg["title"].lower() for lg in existing_learnings}
            if title.lower() in existing_titles:
                logger.info("Skipping duplicate learning: %s", title)
                continue

            notes = str(learning.get("notes", "")).strip()
            tags = learning.get("tags", ["learning"])
            if not isinstance(tags, list):
                tags = ["learning"]
            if "learning" not in tags:
                tags.insert(0, "learning")

            data = {"notes": notes, "tags": tags}

            learning_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO things
                   (id, title, type_hint, priority, active, surface, data,
                    created_at, updated_at, user_id)
                   VALUES (?, ?, 'learning', 3, 1, 0, ?, ?, ?, ?)""",
                (learning_id, title, json.dumps(data), now, now, user_id or None),
            )

            # Create LearnedAbout relationship: User Thing → Learning
            if user_thing_id:
                rel_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO thing_relationships
                       (id, from_thing_id, to_thing_id, relationship_type, created_at)
                       VALUES (?, ?, ?, 'LearnedAbout', ?)""",
                    (rel_id, user_thing_id, learning_id, now),
                )

            # Connect to related domain Things
            related_titles = learning.get("related_thing_titles", [])
            if isinstance(related_titles, list):
                for rt in related_titles[:5]:
                    rt_lower = str(rt).lower().strip()
                    related_id = title_lookup.get(rt_lower)
                    if related_id and related_id != learning_id:
                        conn.execute(
                            """INSERT INTO thing_relationships
                               (id, from_thing_id, to_thing_id, relationship_type,
                                created_at)
                               VALUES (?, ?, ?, 'related-to', ?)""",
                            (str(uuid.uuid4()), learning_id, related_id, now),
                        )

            created.append({
                "id": learning_id,
                "title": title,
                "tags": tags,
                "notes": notes,
            })
            # Track to avoid creating more duplicates within same batch
            existing_learnings.append({"title": title})

    logger.info("Generated %d learnings from conversations", len(created))
    return LearningResult(
        learnings_created=len(created),
        learnings=created,
        usage=usage_stats.to_dict(),
    )
