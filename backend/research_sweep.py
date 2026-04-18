"""Research sweep — proactive external lookups for Things with open questions.

For each Thing with open questions and importance <= 2 (critical/high/medium),
asks an LLM what external data would help (web search, Gmail, calendar, or none),
executes the lookup, stores results in Thing.data['research'], and creates a
sweep finding summarising what was found.

Rate-limited to MAX_LOOKUPS_PER_RUN per sweep; skips Things researched within
RESEARCH_COOLDOWN_DAYS unless the Thing was updated since.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

import backend.db_engine as _engine_mod

from .db_engine import user_filter_clause
from .db_models import SweepFindingRecord, ThingRecord
from .google_calendar import fetch_upcoming_events
from .web_search import google_search

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_LOOKUPS_PER_RUN = 10        # Hard cap on external API calls per sweep
RESEARCH_COOLDOWN_DAYS = 7      # Skip if researched < 7 days ago (unless Thing changed)
MIN_IMPORTANCE = 2              # 0=critical, 1=high, 2=medium, 3=low, 4=backlog; skip 3+

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ResearchSweepResult:
    """Result of the proactive research sweep."""

    things_researched: int = 0
    findings_created: int = 0
    lookups_executed: int = 0
    findings: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

RESEARCH_DECISION_SYSTEM = """\
You decide whether a Thing needs external research to answer its open questions.
Given the Thing title and its open questions, respond with JSON:
{"action": "web_search" | "gmail_search" | "calendar_check" | "none",
 "query": "<search query if applicable, else null>",
 "reason": "<one sentence why>"}

Rules:
- web_search: for factual lookups (prices, venues, products, public info)
- gmail_search: for recent threads with people/organisations mentioned in the Thing
- calendar_check: when the open question involves scheduling conflicts or upcoming events
- none: when questions require user decision, not external data
Only suggest a search if the query is specific enough to yield useful results."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _should_skip(thing: ThingRecord) -> bool:
    """Return True if this Thing should be skipped for research."""
    # Skip low-importance Things (3=low, 4=backlog)
    if thing.importance > MIN_IMPORTANCE:
        return True

    # Check cooldown: skip if researched recently and Thing hasn't changed since
    if isinstance(thing.data, dict):
        research = thing.data.get("research")
        if isinstance(research, dict):
            ts_str = research.get("timestamp")
            if ts_str:
                try:
                    last_research = datetime.fromisoformat(ts_str)
                    cooldown = datetime.now(timezone.utc) - timedelta(days=RESEARCH_COOLDOWN_DAYS)
                    if last_research > cooldown:
                        # Researched recently — only re-research if Thing was updated since
                        if thing.updated_at.tzinfo is None:
                            updated = thing.updated_at.replace(tzinfo=timezone.utc)
                        else:
                            updated = thing.updated_at
                        if updated < last_research:
                            return True
                except (ValueError, TypeError):
                    pass

    return False


def _get_open_questions(thing: ThingRecord) -> list[str]:
    """Extract open_questions, handling both list and JSON-string storage."""
    raw = thing.open_questions
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(raw, list):
        return raw
    return []


async def _decide_research(thing: ThingRecord, usage_stats) -> dict:
    """Ask LLM whether this Thing needs external research and what kind."""
    from .agents import _chat

    questions = _get_open_questions(thing)
    prompt = (
        f"Thing: {thing.title}\n"
        f"Open questions:\n" + "\n".join(f"- {q}" for q in questions)
    )

    raw = await _chat(
        messages=[
            {"role": "system", "content": RESEARCH_DECISION_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        model=None,
        response_format={"type": "json_object"},
        usage_stats=usage_stats,
    )

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Research decision returned invalid JSON: %s", raw[:200])
        return {"action": "none", "query": None, "reason": "LLM returned invalid JSON"}


async def _execute_lookup(action: str, query: str | None, user_id: str) -> list[dict]:
    """Dispatch to the appropriate external lookup."""
    if not query:
        return []

    if action == "web_search":
        results = await google_search(query=query, num_results=5)
        out = []
        for r in results:
            d = r.to_dict()
            # Truncate snippets to 500 chars to respect Thing.data 100KB limit
            if len(d.get("snippet", "")) > 500:
                d["snippet"] = d["snippet"][:500]
            out.append(d)
        return out

    if action == "gmail_search":
        try:
            # Lazy import to avoid circular import with router registration
            from .routers.gmail import _get_service, _parse_message

            service = _get_service(user_id=user_id)
            result = (
                service.users()
                .messages()
                .list(userId="me", maxResults=5, q=query)
                .execute()
            )
            msgs = []
            for m in result.get("messages", []):
                full = (
                    service.users()
                    .messages()
                    .get(userId="me", id=m["id"], format="full")
                    .execute()
                )
                parsed = _parse_message(full)
                msgs.append({
                    "subject": parsed.subject,
                    "sender": parsed.sender,
                    "date": parsed.date,
                    "snippet": parsed.snippet[:500] if parsed.snippet else "",
                })
            return msgs
        except Exception as exc:
            logger.warning("Gmail lookup failed (user may not be connected): %s", exc)
            return []

    if action == "calendar_check":
        try:
            events = fetch_upcoming_events(max_results=10, days_ahead=14, user_id=user_id)
            # Filter events whose summary matches the query (case-insensitive)
            query_lower = query.lower()
            matched = [
                e for e in events
                if query_lower in e.get("summary", "").lower()
            ]
            return matched if matched else events[:5]
        except Exception as exc:
            logger.warning("Calendar lookup failed: %s", exc)
            return []

    return []


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


async def run_research_sweep(
    candidates: list[ThingRecord] | None = None,
    user_id: str = "",
) -> ResearchSweepResult:
    """Run proactive research sweep for Things with open questions.

    If *candidates* is None, loads active Things with open_questions directly
    from the database.
    """
    from .agents import UsageStats

    usage_stats = UsageStats()
    result = ResearchSweepResult()

    # 1. Load candidates if not provided
    if candidates is None:
        with Session(_engine_mod.engine) as session:
            stmt = (
                select(ThingRecord)
                .where(
                    ThingRecord.active == True,  # noqa: E712
                    ThingRecord.open_questions.isnot(None),  # type: ignore[union-attr]
                    ThingRecord.importance <= MIN_IMPORTANCE,
                )
            )
            if user_id:
                stmt = stmt.where(
                    user_filter_clause(ThingRecord.user_id, user_id)
                )
            candidates = list(session.exec(stmt).all())
            # Detach from session so we can use them outside
            for c in candidates:
                session.expunge(c)

    # 2. Filter by _should_skip and sort by importance (most important first)
    eligible = [t for t in candidates if not _should_skip(t) and _get_open_questions(t)]
    eligible.sort(key=lambda t: t.importance)

    # 3. Cap at MAX_LOOKUPS_PER_RUN
    to_research = eligible[:MAX_LOOKUPS_PER_RUN]

    # 4. For each: decide → lookup → merge → create finding
    now = datetime.now(timezone.utc)

    for thing in to_research:
        try:
            decision = await _decide_research(thing, usage_stats)
        except Exception as exc:
            logger.warning("Research sweep: LLM call failed for %s: %s", thing.id, exc)
            continue

        action = decision.get("action", "none")
        query = decision.get("query")
        reason = decision.get("reason", "")

        if action == "none" or not action:
            continue

        try:
            lookup_results = await _execute_lookup(action, query, user_id)
        except Exception as exc:
            logger.warning("Research sweep: lookup failed for %s: %s", thing.id, exc)
            continue

        result.lookups_executed += 1

        if not lookup_results:
            continue

        # Trim to max 5 results
        lookup_results = lookup_results[:5]

        # 5. Merge into Thing.data['research']
        research_data = {
            "source": action,
            "query": query,
            "results": lookup_results,
            "timestamp": now.isoformat(),
            "reason": reason,
        }

        try:
            with Session(_engine_mod.engine) as session:
                record = session.get(ThingRecord, thing.id)
                if record is None:
                    continue

                old_data = record.data if isinstance(record.data, dict) else {}
                record.data = {**old_data, "research": research_data}
                record.updated_at = now

                # 6. Create SweepFindingRecord
                top_result_title = ""
                if lookup_results:
                    first = lookup_results[0]
                    top_result_title = first.get("title") or first.get("summary") or first.get("subject") or ""

                finding_msg = (
                    f"Research for '{thing.title}': {reason}. "
                    f"Found {len(lookup_results)} result(s) via {action}."
                )
                if top_result_title:
                    finding_msg += f" Top result: {top_result_title}"

                finding_id = f"sf-{uuid.uuid4().hex[:8]}"
                session.add(SweepFindingRecord(
                    id=finding_id,
                    thing_id=thing.id,
                    finding_type="research",
                    message=finding_msg,
                    priority=2,
                    dismissed=False,
                    created_at=now,
                    expires_at=None,
                    user_id=user_id or None,
                ))

                session.commit()

                result.things_researched += 1
                result.findings_created += 1
                result.findings.append({
                    "id": finding_id,
                    "thing_id": thing.id,
                    "thing_title": thing.title,
                    "action": action,
                    "query": query,
                    "results_count": len(lookup_results),
                    "message": finding_msg,
                })

        except Exception as exc:
            logger.warning("Research sweep: DB update failed for %s: %s", thing.id, exc)
            continue

    # Collect usage
    result.usage = {
        "input_tokens": getattr(usage_stats, "input_tokens", 0),
        "output_tokens": getattr(usage_stats, "output_tokens", 0),
    }

    logger.info(
        "Research sweep complete: %d researched, %d lookups, %d findings",
        result.things_researched,
        result.lookups_executed,
        result.findings_created,
    )

    return result
