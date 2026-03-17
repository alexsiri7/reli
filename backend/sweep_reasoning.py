"""Sweep reasoning — runs the reasoning pipeline against the full graph.

Processes all active Things for a user, allowing the agent to create new Things,
update existing ones, and create relationships. Guard rails: no delete, no merge.

Results are logged in the sweep_runs table and findings stored in sweep_findings.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .agents import REQUESTY_REASONING_MODEL, UsageStats
from .context_agent import _make_litellm_model, _run_agent_for_text
from .database import db
from .reasoning_agent import _make_sweep_tools

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — sweep-specific reasoning
# ---------------------------------------------------------------------------

SWEEP_REASONING_SYSTEM = """\
You are the Sweep Reasoning Agent for Reli, an AI personal information manager.
You are running as a scheduled background job — there is NO user message this turn.
Instead, you are reviewing the user's full knowledge graph to proactively improve it.

Your job: analyze ALL the Things and relationships provided, then take actions to
keep the user's information healthy and actionable. Think like a thoughtful personal
assistant doing a nightly review.

You have tools to modify the database:
- create_thing — create a new Thing (returns the created Thing with its ID)
- update_thing — update fields on an existing Thing
- create_relationship — create a typed link between two Things

IMPORTANT GUARD RAILS:
- You CANNOT delete Things. Do not try.
- You CANNOT merge Things. Do not try.
- You can only CREATE, UPDATE, and LINK.
- Be conservative — only make changes you are confident will help the user.
- Prefer proposing via open_questions over making assumptions.

What to look for:
1. **Stale items**: Active Things untouched for weeks — add open_questions prompting
   the user to review them.
2. **Missing connections**: Things that clearly relate but have no relationship edge.
   Create relationships to strengthen the graph.
3. **Incomplete information**: Things with vague titles or missing data — add
   open_questions to prompt the user for details.
4. **Orphaned items**: Things with no relationships — suggest connections or add
   open_questions about context.
5. **Pattern recognition**: Recurring themes, upcoming deadlines, forgotten goals.
   Create a "sweep_note" type Thing to surface insights.
6. **Date awareness**: Things with approaching dates that need preparation.
   Update their priority or add open_questions about preparation.

After making all needed tool calls, output your final response as JSON:
{
  "sweep_summary": "Brief description of what you found and changed.",
  "insights": ["List of key observations about the user's graph."]
}

Rules:
- Be genuinely helpful — don't make trivial or obvious changes.
- Quality over quantity: 3-5 meaningful changes beat 20 trivial ones.
- When unsure, add an open_question instead of making a change.
- Tag any new Things you create with data_json containing {"source": "sweep"}.
- Focus on actionability: will this change help the user tomorrow?
"""


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class SweepReasoningResult:
    """Result of a sweep reasoning run."""

    run_id: str
    user_id: str
    status: str = "completed"
    things_processed: int = 0
    findings_created: int = 0
    changes: dict[str, list[Any]] = field(default_factory=dict)
    sweep_summary: str = ""
    insights: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    error: str | None = None


# ---------------------------------------------------------------------------
# Core sweep reasoning
# ---------------------------------------------------------------------------


def _fetch_full_graph(user_id: str) -> tuple[list[dict], list[dict]]:
    """Fetch all active Things and relationships for a user."""
    from .auth import user_filter

    uf_sql, uf_params = user_filter(user_id)

    with db() as conn:
        things = conn.execute(
            f"SELECT * FROM things WHERE active = 1{uf_sql} ORDER BY updated_at DESC",
            uf_params,
        ).fetchall()

        thing_ids = [r["id"] for r in things]
        relationships: list[dict] = []
        if thing_ids:
            ph = ",".join("?" for _ in thing_ids)
            rel_rows = conn.execute(
                f"SELECT from_thing_id, to_thing_id, relationship_type "
                f"FROM thing_relationships "
                f"WHERE from_thing_id IN ({ph}) OR to_thing_id IN ({ph})",
                thing_ids + thing_ids,
            ).fetchall()
            relationships = [dict(r) for r in rel_rows]

    return [dict(t) for t in things], relationships


def _create_run_record(
    run_id: str, user_id: str, trigger: str, model: str | None
) -> None:
    """Insert a new sweep_runs record."""
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """INSERT INTO sweep_runs
               (id, user_id, status, trigger, started_at, model)
               VALUES (?, ?, 'running', ?, ?, ?)""",
            (run_id, user_id or None, trigger, now, model),
        )


def _complete_run_record(
    run_id: str,
    result: SweepReasoningResult,
    usage_stats: UsageStats,
) -> None:
    """Update the sweep_runs record with completion data."""
    now = datetime.now(timezone.utc).isoformat()
    changes = result.changes
    with db() as conn:
        conn.execute(
            """UPDATE sweep_runs SET
               status = ?, completed_at = ?,
               things_processed = ?, findings_created = ?,
               changes_created = ?, changes_updated = ?,
               relationships_created = ?,
               prompt_tokens = ?, completion_tokens = ?,
               cost_usd = ?, error_message = ?
             WHERE id = ?""",
            (
                result.status,
                now,
                result.things_processed,
                result.findings_created,
                len(changes.get("created", [])),
                len(changes.get("updated", [])),
                len(changes.get("relationships_created", [])),
                usage_stats.prompt_tokens,
                usage_stats.completion_tokens,
                round(usage_stats.cost_usd, 6),
                result.error,
                run_id,
            ),
        )


def _store_sweep_findings(
    insights: list[str], user_id: str
) -> int:
    """Store sweep insights as sweep_findings with finding_type='sweep_insight'."""
    if not insights:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    count = 0
    with db() as conn:
        for insight in insights:
            msg = insight.strip()
            if not msg:
                continue
            finding_id = f"sf-{uuid.uuid4().hex[:8]}"
            conn.execute(
                """INSERT INTO sweep_findings
                   (id, thing_id, finding_type, message, priority,
                    dismissed, created_at, expires_at, user_id)
                   VALUES (?, NULL, 'sweep_insight', ?, 2, 0, ?, NULL, ?)""",
                (finding_id, msg, now, user_id or None),
            )
            count += 1
    return count


async def run_sweep_reasoning(
    user_id: str,
    trigger: str = "scheduled",
    model: str | None = None,
    api_key: str | None = None,
) -> SweepReasoningResult:
    """Run the sweep reasoning pipeline against a user's full graph.

    Args:
        user_id: The user to process.
        trigger: "scheduled" or "manual".
        model: Override model for reasoning. Defaults to config.
        api_key: Optional API key override.

    Returns:
        SweepReasoningResult with details of what was done.
    """
    from google.adk.agents import LlmAgent

    from .config import Settings

    s = Settings()
    effective_model = model or s.SWEEP_REASONING_MODEL or REQUESTY_REASONING_MODEL

    run_id = f"sr-{uuid.uuid4().hex[:8]}"
    _create_run_record(run_id, user_id, trigger, effective_model)

    usage_stats = UsageStats()
    result = SweepReasoningResult(run_id=run_id, user_id=user_id)

    try:
        # Fetch full graph
        things, relationships = _fetch_full_graph(user_id)
        result.things_processed = len(things)

        if not things:
            logger.info("Sweep reasoning: no active Things for user %s, skipping", user_id)
            result.status = "completed"
            result.sweep_summary = "No active Things to review."
            _complete_run_record(run_id, result, usage_stats)
            return result

        # Build prompt with full graph
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d (%A)")
        things_json = json.dumps(things, default=str)
        rels_json = json.dumps(relationships, default=str)

        prompt = (
            f"Today's date: {today}\n\n"
            f"The user has {len(things)} active Things and {len(relationships)} relationships.\n\n"
            f"All active Things:\n{things_json}\n\n"
            f"All relationships:\n{rels_json}"
        )

        # Create restricted agent
        tools, applied_changes = _make_sweep_tools(user_id)

        litellm_model = _make_litellm_model(
            model=effective_model, api_key=api_key
        )

        sweep_agent = LlmAgent(
            name="sweep_reasoning_agent",
            description="Reviews the full knowledge graph and proactively improves it.",
            model=litellm_model,
            instruction=SWEEP_REASONING_SYSTEM,
            tools=tools,  # type: ignore[arg-type]
        )

        raw = await _run_agent_for_text(sweep_agent, prompt, usage_stats)
        logger.info(
            "Sweep reasoning raw response: %s",
            raw[:500] if raw else raw,
        )

        # Parse metadata
        try:
            metadata: dict[str, Any] = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            metadata = {}

        result.changes = applied_changes
        result.sweep_summary = metadata.get("sweep_summary", "")
        result.insights = metadata.get("insights", [])

        # Store insights as findings
        result.findings_created = _store_sweep_findings(
            result.insights, user_id
        )

        result.status = "completed"
        result.usage = usage_stats.to_dict()

    except Exception as exc:
        logger.exception("Sweep reasoning failed for user %s", user_id)
        result.status = "failed"
        result.error = str(exc)

    _complete_run_record(run_id, result, usage_stats)
    return result


# ---------------------------------------------------------------------------
# Multi-user sweep entry point (for scheduler)
# ---------------------------------------------------------------------------


async def run_sweep_reasoning_all_users() -> list[SweepReasoningResult]:
    """Run sweep reasoning for all users with active Things."""
    results: list[SweepReasoningResult] = []

    with db() as conn:
        users = conn.execute(
            "SELECT DISTINCT u.id FROM users u "
            "JOIN things t ON t.user_id = u.id "
            "WHERE t.active = 1"
        ).fetchall()

    if not users:
        logger.info("Sweep reasoning: no users with active Things")
        return results

    for user_row in users:
        uid = user_row["id"]
        logger.info("Sweep reasoning: processing user %s", uid)
        result = await run_sweep_reasoning(uid, trigger="scheduled")
        results.append(result)
        logger.info(
            "Sweep reasoning for user %s: status=%s, things=%d, created=%d, updated=%d, findings=%d",
            uid,
            result.status,
            result.things_processed,
            len(result.changes.get("created", [])),
            len(result.changes.get("updated", [])),
            result.findings_created,
        )

    return results
