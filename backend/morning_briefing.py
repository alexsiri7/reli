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

from .auth import user_filter
from .database import db
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

    with db() as conn:
        row = conn.execute(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = 'briefing_preferences'",
            (user_id,),
        ).fetchone()

    if not row or not row["value"]:
        return BriefingPreferences()

    try:
        data = json.loads(row["value"])
        return BriefingPreferences(**data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return BriefingPreferences()


def save_briefing_preferences(user_id: str, prefs: BriefingPreferences) -> None:
    """Save briefing preferences to user_settings."""
    if not user_id:
        return  # No user to save for (legacy single-user mode)
    with db() as conn:
        conn.execute(
            """INSERT INTO user_settings (user_id, key, value, updated_at)
               VALUES (?, 'briefing_preferences', ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id, key) DO UPDATE SET
                 value = excluded.value, updated_at = CURRENT_TIMESTAMP""",
            (user_id, prefs.model_dump_json()),
        )


async def generate_natural_language_summary(
    priorities: list[MorningBriefingItem],
    overdue: list[MorningBriefingItem],
    blockers: list[MorningBriefingItem],
    findings: list[MorningBriefingFinding],
    personality_patterns: list[dict],
) -> str:
    """Generate a natural language briefing summary using the response agent.

    Produces a 1-2 sentence conversational summary that references specific
    items by name. Falls back to a generic summary if the LLM call fails.
    Tone adapts to user personality patterns if any have been learned.
    """
    if not (priorities or overdue or blockers or findings):
        return "Everything looks clear today — nothing urgent on the agenda."

    from .agents import REQUESTY_RESPONSE_MODEL, _build_personality_overlay
    from .llm import acomplete

    # Build concise item lists for the prompt
    lines: list[str] = []
    if overdue:
        items = ", ".join(
            f'"{o.title}" ({o.days_overdue}d overdue)' for o in overdue[:3]
        )
        lines.append(f"Overdue: {items}")
    if priorities:
        items = ", ".join(f'"{p.title}"' for p in priorities[:5])
        lines.append(f"Top priorities: {items}")
    if blockers:
        items = ", ".join(f'"{b.title}"' for b in blockers[:3])
        lines.append(f"Blocked items: {items}")
    if findings:
        items = ", ".join(f'"{f.message}"' for f in findings[:3])
        lines.append(f"Sweep findings: {items}")

    item_text = "\n".join(lines)
    personality_overlay = _build_personality_overlay(personality_patterns)

    system = (
        "You write natural language briefing summaries for a personal assistant app. "
        "Write 1-2 sentences summarizing what's on the user's plate today. "
        "Be specific — mention items by name. "
        "Don't start with 'Good morning' or 'You have N items.' Use conversational tone.\n"
        "Examples:\n"
        '- "Busy day — you\'ve got the dentist at 2pm and the proposal draft is due."\n'
        '- "The Q3 report is overdue and blocking two other things; probably worth tackling first."\n'
        '- "Looks like a lighter day, though the expense report has been sitting for a while."'
        f"{personality_overlay}"
    )
    user_msg = f"Today's briefing items:\n{item_text}\n\nWrite the summary:"

    try:
        response = await acomplete(
            [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
            model=REQUESTY_RESPONSE_MODEL,
            max_tokens=120,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        logger.exception("Failed to generate natural language briefing summary; using fallback")
        parts: list[str] = []
        if priorities:
            parts.append(f"{len(priorities)} priorit{'y' if len(priorities) == 1 else 'ies'}")
        if overdue:
            parts.append(f"{len(overdue)} overdue item{'s' if len(overdue) != 1 else ''}")
        if blockers:
            parts.append(f"{len(blockers)} blocked item{'s' if len(blockers) != 1 else ''}")
        if findings:
            parts.append(f"{len(findings)} sweep finding{'s' if len(findings) != 1 else ''}")
        return f"You have {', '.join(parts)} today." if parts else "Everything looks clear."


async def generate_morning_briefing(
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

    uf_sql, uf_params = user_filter(user_id)

    priorities: list[MorningBriefingItem] = []
    overdue: list[MorningBriefingItem] = []
    blockers: list[MorningBriefingItem] = []
    findings_list: list[MorningBriefingFinding] = []

    with db() as conn:
        # Fetch active things
        thing_rows = conn.execute(
            f"""SELECT * FROM things
               WHERE active = 1{uf_sql}
               ORDER BY priority ASC, updated_at DESC""",
            uf_params,
        ).fetchall()

        # Fetch relationships for blocking analysis
        rel_rows = conn.execute(
            "SELECT from_thing_id, to_thing_id, relationship_type FROM thing_relationships"
        ).fetchall()

        # Fetch active sweep findings
        now = datetime.now(timezone.utc).isoformat()
        sf_uf_sql, sf_uf_params = user_filter(user_id, "sf")
        finding_rows = conn.execute(
            f"""SELECT sf.id, sf.message, sf.priority, sf.thing_id,
                      t.title AS thing_title
               FROM sweep_findings sf
               LEFT JOIN things t ON sf.thing_id = t.id
               WHERE sf.dismissed = 0
                 AND (sf.expires_at IS NULL OR sf.expires_at > ?)
                 AND (sf.snoozed_until IS NULL OR sf.snoozed_until <= ?){sf_uf_sql}
               ORDER BY sf.priority ASC, sf.created_at DESC""",
            [now, now, *sf_uf_params],
        ).fetchall()

    # Build thing map
    thing_map: dict[str, dict] = {}
    for r in thing_rows:
        thing_map[r["id"]] = dict(r)

    active_ids = set(thing_map.keys())

    # Build blocking graph
    blocked_by: dict[str, set[str]] = {}
    blocks: dict[str, set[str]] = {}
    for r in rel_rows:
        rtype = r["relationship_type"]
        from_id = r["from_thing_id"]
        to_id = r["to_thing_id"]
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
        priority = t.get("priority", 3)
        score = 0.0
        reasons: list[str] = []

        # Priority boost
        priority_boost = (6 - priority) * 20
        score += priority_boost
        if priority <= 2:
            reasons.append(f"High priority (P{priority})")

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
                    id=r["id"],
                    message=r["message"],
                    priority=r["priority"],
                    thing_id=r["thing_id"],
                    thing_title=r["thing_title"],
                )
            )

    # Generate natural language summary using the response agent
    from .agents import load_personality_preferences

    personality_patterns = load_personality_preferences(user_id)
    summary = await generate_natural_language_summary(
        priorities, overdue, blockers, findings_list, personality_patterns
    )

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

    with db() as conn:
        conn.execute(
            """INSERT INTO morning_briefings (id, user_id, briefing_date, content, generated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id, briefing_date) DO UPDATE SET
                 id = excluded.id,
                 content = excluded.content,
                 generated_at = excluded.generated_at""",
            (briefing_id, user_id or None, today.isoformat(), content.model_dump_json(), now),
        )

    logger.info(
        "Morning briefing stored: %s for user %s on %s", briefing_id, user_id[:8] if user_id else "legacy", today
    )
    return briefing_id


def get_latest_morning_briefing(user_id: str, as_of: date | None = None) -> dict | None:
    """Retrieve the most recent morning briefing for a user.

    If as_of is specified, returns the briefing for that specific date.
    Otherwise, returns the most recent briefing.
    """
    uf_sql, uf_params = user_filter(user_id)

    with db() as conn:
        if as_of:
            row = conn.execute(
                f"""SELECT * FROM morning_briefings
                   WHERE briefing_date = ?{uf_sql}""",
                [as_of.isoformat(), *uf_params],
            ).fetchone()
        else:
            row = conn.execute(
                f"""SELECT * FROM morning_briefings
                   WHERE 1=1{uf_sql}
                   ORDER BY briefing_date DESC
                   LIMIT 1""",
                uf_params,
            ).fetchone()

    if not row:
        return None

    try:
        content = json.loads(row["content"])
    except (json.JSONDecodeError, TypeError):
        content = {}

    return {
        "id": row["id"],
        "briefing_date": row["briefing_date"],
        "content": content,
        "generated_at": row["generated_at"],
    }
