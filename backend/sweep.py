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


def _user_where(user_id: str | None, alias: str = "") -> tuple[str, list[str]]:
    """Return a SQL WHERE fragment and params to filter by user_id."""
    if not user_id:
        return "", []
    prefix = f"{alias}." if alias else ""
    return f" AND ({prefix}user_id = ? OR {prefix}user_id IS NULL)", [user_id]


def find_approaching_dates(
    conn: sqlite3.Connection,
    today: date | None = None,
    window_days: int = 7,
    user_id: str | None = None,
) -> list[SweepCandidate]:
    """Find Things with dates (checkin_date or data JSON dates) within *window_days*.

    Covers both the checkin_date column and date fields stored in the data JSON.
    """
    today = today or date.today()
    cutoff = today + timedelta(days=window_days)
    candidates: list[SweepCandidate] = []
    uf_sql, uf_params = _user_where(user_id)

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
             AND data IS NOT NULL AND data != '{{}}'  AND data != 'null'{uf_sql}""",
        (*uf_params,),
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
    user_id: str | None = None,
) -> list[SweepCandidate]:
    """Find active Things not updated in *stale_days* or more."""
    today = today or date.today()
    cutoff = (today - timedelta(days=stale_days)).isoformat()
    uf_sql, uf_params = _user_where(user_id)
    rows = conn.execute(
        f"""SELECT id, title, type_hint, updated_at FROM things
           WHERE active = 1
             AND updated_at < ?{uf_sql}
           ORDER BY updated_at ASC""",
        (cutoff, *uf_params),
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


def find_orphan_things(
    conn: sqlite3.Connection,
    user_id: str | None = None,
) -> list[SweepCandidate]:
    """Find active Things with no relationships (no parent, no children, no graph edges)."""
    uf_sql, uf_params = _user_where(user_id, "t")
    rows = conn.execute(
        f"""SELECT t.id, t.title, t.type_hint FROM things t
           LEFT JOIN thing_relationships r
             ON t.id = r.from_thing_id OR t.id = r.to_thing_id
           WHERE t.active = 1
             AND t.parent_id IS NULL
             AND r.id IS NULL{uf_sql}
           ORDER BY t.created_at DESC""",
        (*uf_params,),
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


def find_completed_projects(
    conn: sqlite3.Connection,
    user_id: str | None = None,
) -> list[SweepCandidate]:
    """Find active projects where all children are inactive (completed).

    A project qualifies if:
    - It's active with type_hint='project'
    - It has at least one child (via parent_id)
    - ALL of its children are inactive
    """
    uf_sql, uf_params = _user_where(user_id, "p")
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
        (*uf_params,),
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


def find_open_questions(
    conn: sqlite3.Connection,
    user_id: str | None = None,
) -> list[SweepCandidate]:
    """Find active Things that have unanswered open_questions."""
    uf_sql, uf_params = _user_where(user_id)
    rows = conn.execute(
        f"""SELECT id, title, open_questions FROM things
           WHERE active = 1
             AND open_questions IS NOT NULL
             AND open_questions != '[]'
             AND open_questions != 'null'{uf_sql}""",
        (*uf_params,),
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
    user_id: str | None = None,
) -> list[SweepCandidate]:
    """Run all SQL candidate queries and return a combined, deduplicated list.

    This is Phase 1 of the nightly sweep. The returned candidates are intended
    to be passed to the LLM reflection phase (Phase 2).

    When *user_id* is provided, only Things belonging to that user are considered.
    """
    today = today or date.today()

    with db() as conn:
        candidates = (
            find_approaching_dates(conn, today, window_days, user_id=user_id)
            + find_stale_things(conn, today, stale_days, user_id=user_id)
            + find_orphan_things(conn, user_id=user_id)
            + find_completed_projects(conn, user_id=user_id)
            + find_open_questions(conn, user_id=user_id)
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
    user_id: str | None = None,
) -> ReflectionResult:
    """Phase 2: Send SQL candidates to LLM for nuanced reflection.

    If *candidates* is None, runs collect_candidates() first.
    Uses the powerful reasoning model for higher-quality insights.
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
        model=REQUESTY_REASONING_MODEL or None,  # use powerful reasoning model
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
                (finding_id, thing_id, "llm_insight", message, priority, now.isoformat(), expires_at, user_id),
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
# Phase 3: Full reasoning pipeline sweep (guard-railed)
# ---------------------------------------------------------------------------

SWEEP_REASONING_SYSTEM = """\
You are the Nightly Sweep Agent for Reli, an AI personal information manager.
You are processing a user's full graph of Things as a background sweep.
The user did NOT trigger this — you are running autonomously on a schedule.

Your job: review the user's Things and make helpful maintenance changes.

GUARD RAILS — you MUST follow these strictly:
- You may CREATE new Things (e.g. reminders, follow-up tasks, insights)
- You may UPDATE existing Things (e.g. add notes, adjust priorities, add open_questions)
- You may CREATE relationships between Things (e.g. connect related items)
- You MUST NOT delete any Things
- You MUST NOT merge any Things
- You are PROPOSING changes, not responding to a user request
- Be conservative — only make changes you are confident will help
- Prefer adding open_questions over making assumptions

Focus areas:
- Tasks approaching deadlines that need attention
- Stale items that should be reviewed or archived
- Missing connections between related Things
- Open questions that could make Things more actionable
- Patterns the user might not notice (recurring deferrals, etc.)

After making tool calls, output JSON:
{
  "questions_for_user": [],
  "priority_question": "",
  "reasoning_summary": "Brief summary of sweep actions taken.",
  "briefing_mode": false
}
"""


@dataclass
class SweepRunResult:
    """Result of a full sweep run (SQL + reflection + reasoning)."""

    run_id: str = ""
    user_id: str = ""
    candidates_found: int = 0
    findings_created: int = 0
    things_created: int = 0
    things_updated: int = 0
    relationships_created: int = 0
    usage: dict = field(default_factory=dict)
    error: str | None = None


def _fetch_user_graph(conn: sqlite3.Connection, user_id: str | None) -> list[dict]:
    """Fetch all active Things for a user, with relationships."""
    uf_sql, uf_params = _user_where(user_id)
    rows = conn.execute(
        f"""SELECT * FROM things WHERE active = 1{uf_sql}
           ORDER BY priority ASC, updated_at DESC""",
        (*uf_params,),
    ).fetchall()
    things = []
    for r in rows:
        d = dict(r)
        # Parse JSON fields
        for jf in ("data", "open_questions"):
            if isinstance(d.get(jf), str):
                try:
                    d[jf] = json.loads(d[jf])
                except (json.JSONDecodeError, TypeError):
                    pass
        things.append(d)
    return things


def _fetch_relationships(conn: sqlite3.Connection, thing_ids: set[str]) -> list[dict]:
    """Fetch relationships involving any of the given thing IDs."""
    if not thing_ids:
        return []
    placeholders = ",".join("?" * len(thing_ids))
    ids = list(thing_ids)
    rows = conn.execute(
        f"""SELECT * FROM thing_relationships
           WHERE from_thing_id IN ({placeholders})
              OR to_thing_id IN ({placeholders})""",
        ids + ids,
    ).fetchall()
    return [dict(r) for r in rows]


async def run_sweep_reasoning(
    user_id: str,
    candidates: list[SweepCandidate],
    things: list[dict],
    relationships: list[dict],
) -> dict:
    """Run the reasoning agent against the full graph with guard rails.

    Returns applied_changes dict from the reasoning agent.
    Uses only create_thing, update_thing, and create_relationship tools
    (no delete_thing, no merge_things).
    """
    from .agents import REQUESTY_REASONING_MODEL, UsageStats
    from .context_agent import _make_litellm_model, _run_agent_for_text
    from .reasoning_agent import _make_reasoning_tools, _traced_tool

    from google.adk.agents import LlmAgent

    usage_stats = UsageStats()

    # Create guard-railed tools (no delete, no merge)
    all_tools, applied_changes = _make_reasoning_tools(user_id)
    # Filter to only safe tools: create_thing, update_thing, create_relationship
    safe_tool_names = {"create_thing", "update_thing", "create_relationship"}
    safe_tools = [
        t for t in all_tools
        if getattr(getattr(t, "__wrapped__", None), "__name__", "") in safe_tool_names
    ]

    litellm_model = _make_litellm_model(model=REQUESTY_REASONING_MODEL)

    sweep_agent = LlmAgent(
        name="sweep_reasoning_agent",
        description="Sweep agent that reviews user's Things graph and proposes maintenance changes.",
        model=litellm_model,
        instruction=SWEEP_REASONING_SYSTEM,
        tools=safe_tools,  # type: ignore[arg-type]
    )

    # Format the sweep context
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d (%A)")
    candidates_text = _format_candidates_for_llm(candidates)
    things_json = json.dumps(things, default=str)
    rels_json = json.dumps(relationships, default=str)

    prompt = (
        f"Today's date: {today}\n\n"
        f"SQL Sweep Candidates:\n{candidates_text}\n\n"
        f"Full graph of user's active Things ({len(things)} items):\n{things_json}\n\n"
        f"Relationships between Things:\n{rels_json}"
    )

    raw = await _run_agent_for_text(sweep_agent, prompt, usage_stats)
    logger.info(
        "Sweep reasoning agent response: %s",
        raw[:500] if raw else raw,
    )

    return {
        "applied_changes": applied_changes,
        "usage": usage_stats.to_dict(),
    }


async def run_full_sweep(
    user_id: str | None = None,
    trigger: str = "scheduled",
) -> SweepRunResult:
    """Execute a complete sweep for a single user: SQL → reflection → reasoning.

    Records the run in the sweep_runs table for logging/audit.
    """
    run_id = f"sr-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(timezone.utc)
    result = SweepRunResult(run_id=run_id, user_id=user_id or "")

    # Log the run start
    with db() as conn:
        conn.execute(
            """INSERT INTO sweep_runs (id, user_id, started_at, status, trigger)
               VALUES (?, ?, ?, 'running', ?)""",
            (run_id, user_id, started_at.isoformat(), trigger),
        )

    try:
        # Phase 1: SQL candidates
        candidates = collect_candidates(user_id=user_id)
        result.candidates_found = len(candidates)
        logger.info("Sweep [%s] user=%s: %d candidates found", run_id, user_id, len(candidates))

        if not candidates:
            logger.info("Sweep [%s] complete — no candidates", run_id)
            _finish_sweep_run(run_id, result, started_at)
            return result

        # Phase 2: LLM reflection (creates findings)
        reflection = await reflect_on_candidates(candidates, user_id=user_id)
        result.findings_created = reflection.findings_created
        result.usage = reflection.usage

        # Phase 3: Full reasoning pipeline against the graph
        with db() as conn:
            things = _fetch_user_graph(conn, user_id)
            thing_ids = {t["id"] for t in things}
            rels = _fetch_relationships(conn, thing_ids)

        if things:
            reasoning_result = await run_sweep_reasoning(
                user_id or "", candidates, things, rels,
            )
            applied = reasoning_result.get("applied_changes", {})
            result.things_created = len(applied.get("created", []))
            result.things_updated = len(applied.get("updated", []))
            result.relationships_created = len(applied.get("relationships_created", []))

            # Merge usage stats
            reasoning_usage = reasoning_result.get("usage", {})
            result.usage["prompt_tokens"] = (
                result.usage.get("prompt_tokens", 0) + reasoning_usage.get("prompt_tokens", 0)
            )
            result.usage["completion_tokens"] = (
                result.usage.get("completion_tokens", 0) + reasoning_usage.get("completion_tokens", 0)
            )
            result.usage["cost_usd"] = (
                result.usage.get("cost_usd", 0.0) + reasoning_usage.get("cost_usd", 0.0)
            )

        logger.info(
            "Sweep [%s] complete — %d findings, %d created, %d updated, %d rels",
            run_id, result.findings_created, result.things_created,
            result.things_updated, result.relationships_created,
        )

    except Exception as exc:
        result.error = str(exc)
        logger.exception("Sweep [%s] failed", run_id)

    _finish_sweep_run(run_id, result, started_at)
    return result


def _finish_sweep_run(
    run_id: str,
    result: SweepRunResult,
    started_at: datetime,
) -> None:
    """Update the sweep_runs row with final results."""
    finished_at = datetime.now(timezone.utc)
    status = "failed" if result.error else "completed"
    with db() as conn:
        conn.execute(
            """UPDATE sweep_runs SET
                finished_at = ?, status = ?, candidates_found = ?,
                findings_created = ?, things_created = ?, things_updated = ?,
                relationships_created = ?, model = ?,
                prompt_tokens = ?, completion_tokens = ?, cost_usd = ?, error = ?
               WHERE id = ?""",
            (
                finished_at.isoformat(),
                status,
                result.candidates_found,
                result.findings_created,
                result.things_created,
                result.things_updated,
                result.relationships_created,
                result.usage.get("model", ""),
                result.usage.get("prompt_tokens", 0),
                result.usage.get("completion_tokens", 0),
                result.usage.get("cost_usd", 0.0),
                result.error,
                run_id,
            ),
        )
