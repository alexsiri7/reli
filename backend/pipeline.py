"""Chat pipeline for Reli: reasoning agent + response agent.

The reasoning agent fetches its own context on-demand via the fetch_context
tool (formerly a separate pipeline stage). The pipeline handles:
  - Reasoning with on-demand context fetching and tool-based storage changes
  - Streaming response generation
"""

import json
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import String, cast, func
from sqlmodel import Session, or_, select

import backend.db_engine as _engine_mod

from .agents import (
    REQUESTY_REASONING_MODEL,
    REQUESTY_RESPONSE_MODEL,
    UsageStats,
)
from .db_engine import user_filter_clause
from .db_models import ChatHistoryRecord, ThingRecord, ThingRelationshipRecord
from .google_calendar import fetch_upcoming_events
from .google_calendar import is_connected as gcal_connected
from .reasoning_agent import run_reasoning_agent
from .response_agent import parse_response, run_response_agent, run_response_agent_stream
from .tracing import get_tracer, set_span_error
from .vector_store import VECTOR_SEARCH_THRESHOLD, vector_count, vector_search

logger = logging.getLogger(__name__)
_tracer = get_tracer()

ONBOARDING_SYSTEM_ADDENDUM = """
ONBOARDING MODE: This is the user's very first conversation — they have no Things yet.
Your goals for this session:
1. Open with a warm welcome and ask what they're working on this week.
2. As they share details, proactively call create_thing for each task, project, or person they mention.
3. Ask 2-3 follow-up questions to learn more (e.g., "Who else is involved?", "When does this need to be done?").
4. After 3+ Things are created, close with: "Here's what I know so far: [list]. Tomorrow I'll check in on these."
5. Keep the tone warm and conversational — not a form or questionnaire.
Be proactive: don't wait for the user to say "create a thing". Just do it naturally.
"""


# ---------------------------------------------------------------------------
# Pipeline result types
# ---------------------------------------------------------------------------


@dataclass
class PipelineResult:
    """Result from running the chat pipeline."""

    reply: str
    applied_changes: dict[str, Any]
    questions_for_user: list[str]
    priority_question: str
    reasoning_summary: str
    briefing_mode: bool
    relevant_things: list[dict[str, Any]]
    context_relationships: list[dict[str, Any]]
    web_results: list[dict[str, Any]] | None
    gmail_context: list[dict[str, Any]]
    calendar_events: list[dict[str, Any]] | None
    open_questions_by_thing: dict[str, list[str]]
    usage: UsageStats
    referenced_things: list[dict[str, str]] = field(default_factory=list)


@dataclass
class PipelineEvent:
    """Event emitted during streaming pipeline execution."""

    type: str  # "stage_start", "stage_complete", "token"
    stage: str = ""
    data: Any = None


# ---------------------------------------------------------------------------
# Data-gathering helpers (moved from chat.py)
# ---------------------------------------------------------------------------


def _parse_thing_open_questions(thing: dict[str, Any]) -> dict[str, Any]:
    """Deserialize open_questions on a raw Thing dict from JSON string to list.

    SQLite stores open_questions as a JSON-encoded string.  When the dict is
    later serialized (e.g. for the reasoning agent), this causes double-encoding.
    Parsing it eagerly ensures downstream consumers see a proper list.
    """
    oq = thing.get("open_questions")
    if oq and isinstance(oq, str):
        try:
            parsed = json.loads(oq)
            thing["open_questions"] = parsed if isinstance(parsed, list) else None
        except (json.JSONDecodeError, TypeError):
            thing["open_questions"] = None
    return thing


def _sql_things_count(session: Session) -> int:
    """Return total number of Things in the database."""
    result = session.execute(select(func.count()).select_from(ThingRecord)).scalar()
    return result or 0


def _fetch_with_family(session: Session, seed_ids: list[str], user_id: str = "") -> list[dict[str, Any]]:
    """Given seed Thing IDs, return those Things plus their parents, children, and related Things via relationships."""
    seen_ids: set[str] = set()
    results: list[dict] = []

    def _add_record(rec: ThingRecord) -> None:
        if rec.id not in seen_ids:
            seen_ids.add(rec.id)
            results.append(_parse_thing_open_questions(rec.model_dump()))

    for thing_id in seed_ids:
        rec = session.get(ThingRecord, thing_id)
        if rec is None:
            continue
        # Skip seed records not owned by this user (Stage A: NULL-owner records still readable)
        if user_id and rec.user_id and rec.user_id != user_id:
            continue
        _add_record(rec)
        # Fetch parent-of / child-of related Things via relationships
        parent_rels = session.exec(
            select(ThingRelationshipRecord).where(
                ThingRelationshipRecord.to_thing_id == thing_id,
                ThingRelationshipRecord.relationship_type == "parent-of",
            )
        ).all()
        for pr in parent_rels:
            parent = session.get(ThingRecord, pr.from_thing_id)
            if parent:
                _add_record(parent)
        child_rels = session.exec(
            select(ThingRelationshipRecord).where(
                ThingRelationshipRecord.from_thing_id == thing_id,
                ThingRelationshipRecord.relationship_type == "parent-of",
            )
        ).all()
        for cr in child_rels:
            child = session.get(ThingRecord, cr.to_thing_id)
            if child:
                _add_record(child)
        rels = session.exec(
            select(ThingRelationshipRecord).where(
                or_(
                    ThingRelationshipRecord.from_thing_id == thing_id,
                    ThingRelationshipRecord.to_thing_id == thing_id,
                )
            )
        ).all()
        for rel in rels:
            other_id = rel.to_thing_id if rel.from_thing_id == thing_id else rel.from_thing_id
            if other_id not in seen_ids:
                other = session.get(ThingRecord, other_id)
                if other:
                    _add_record(other)

    return results


def _fetch_user_relationships(
    session: Session,
    user_thing_id: str,
    search_queries: list[str],
    user_id: str = "",
) -> list[dict[str, Any]]:
    """Fetch 1-hop relationships from the user Thing, filtered by search query relevance."""
    if not user_thing_id or not search_queries:
        return []

    rels = session.exec(
        select(ThingRelationshipRecord).where(
            or_(
                ThingRelationshipRecord.from_thing_id == user_thing_id,
                ThingRelationshipRecord.to_thing_id == user_thing_id,
            )
        )
    ).all()
    if not rels:
        return []

    other_ids: list[str] = []
    for rel in rels:
        other_id = rel.to_thing_id if rel.from_thing_id == user_thing_id else rel.from_thing_id
        other_ids.append(other_id)

    if not other_ids:
        return []

    # Build LIKE filter conditions for search queries
    like_conditions = []
    for query in search_queries[:3]:
        pattern = f"%{query}%"
        like_conditions.append(
            or_(
                ThingRecord.title.like(pattern),  # type: ignore[union-attr]
                cast(ThingRecord.data, String).like(pattern),
            )
        )

    stmt = (
        select(ThingRecord)
        .where(
            ThingRecord.id.in_(other_ids),  # type: ignore[union-attr]
            user_filter_clause(ThingRecord.user_id, user_id),
            or_(*like_conditions),
        )
        .order_by(
            # NULL last_referenced sorts after non-NULL
            ThingRecord.last_referenced.desc().nulls_last(),  # type: ignore[union-attr]
            ThingRecord.updated_at.desc(),  # type: ignore[union-attr]
        )
        .limit(10)
    )
    rows = session.exec(stmt).all()
    logger.info(
        "User relationship search: %d edges, %d query-matched (queries=%r)",
        len(other_ids),
        len(rows),
        search_queries[:3],
    )
    return [_parse_thing_open_questions(r.model_dump()) for r in rows]


def _fetch_user_thing(session: Session, user_id: str) -> dict[str, Any] | None:
    """Fetch the user's own Thing (type_hint='person', matching user_id)."""
    if not user_id:
        return None
    stmt = (
        select(ThingRecord)
        .where(
            ThingRecord.user_id == user_id,
            ThingRecord.type_hint == "person",
        )
        .limit(1)
    )
    rec = session.exec(stmt).first()
    return _parse_thing_open_questions(rec.model_dump()) if rec else None


def _fetch_warm_context(
    session_id: str,
    user_id: str = "",
    n_messages: int = 3,
) -> list[dict[str, Any]]:
    """Fetch context Things from the last N assistant messages for warm start.

    Extracts Thing IDs from stored context_things in applied_changes,
    then fetches their current state from the database. This gives the
    reasoning agent recent context without needing a fetch_context tool call.
    """
    with Session(_engine_mod.engine) as session:
        stmt = (
            select(ChatHistoryRecord.applied_changes)
            .where(
                ChatHistoryRecord.session_id == session_id,
                ChatHistoryRecord.role == "assistant",
                user_filter_clause(ChatHistoryRecord.user_id, user_id),
            )
            .order_by(ChatHistoryRecord.id.desc())  # type: ignore[union-attr]
            .limit(n_messages)
        )
        rows = session.execute(stmt).fetchall()

        thing_ids: list[str] = []
        seen: set[str] = set()
        for row in rows:
            raw = row.applied_changes
            if not raw:
                continue
            try:
                changes = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(changes, dict):
                continue
            for ct in changes.get("context_things", []):
                tid = ct.get("id")
                if tid and tid not in seen:
                    seen.add(tid)
                    thing_ids.append(tid)

        if not thing_ids:
            return []

        return _fetch_with_family(session, thing_ids)


def _fetch_relevant_things(
    session: Session,
    search_queries: list[str],
    filter_params: dict[str, Any],
    user_id: str = "",
) -> list[dict[str, Any]]:
    """Retrieve relevant Things using vector search (>=500 Things) or SQL LIKE fallback (<500)."""
    active_only = filter_params.get("active_only", True)
    type_hint = filter_params.get("type_hint")

    user_thing = _fetch_user_thing(session, user_id)
    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    if user_thing:
        seen_ids.add(user_thing["id"])
        results.append(user_thing)

        user_rels = _fetch_user_relationships(session, user_thing["id"], search_queries, user_id)
        for rel_thing in user_rels:
            if rel_thing["id"] not in seen_ids:
                seen_ids.add(rel_thing["id"])
                results.append(rel_thing)

    vc = vector_count()
    use_vector = vc >= VECTOR_SEARCH_THRESHOLD
    sql_thing_count = _sql_things_count(session)

    logger.info(
        "Retrieval strategy: vector_count=%d, sql_things=%d, threshold=%d, use_vector=%s, active_only=%s, type_hint=%r",
        vc,
        sql_thing_count,
        VECTOR_SEARCH_THRESHOLD,
        use_vector,
        active_only,
        type_hint,
    )

    seed_ids: list[str] = []

    if use_vector:
        seed_ids = vector_search(
            queries=search_queries,
            n_results=20,
            active_only=active_only,
            type_hint=type_hint,
            user_id=user_id,
        )
        logger.info("Vector search returned %d seed IDs", len(seed_ids))
        if not seed_ids:
            use_vector = False

    if not use_vector:
        seen_sql: set[str] = set()
        for query in search_queries[:3]:
            pattern = f"%{query}%"
            stmt = select(ThingRecord.id).where(
                or_(
                    ThingRecord.title.like(pattern),  # type: ignore[union-attr]
                    cast(ThingRecord.data, String).like(pattern),
                ),
                user_filter_clause(ThingRecord.user_id, user_id),
            )
            if active_only:
                stmt = stmt.where(ThingRecord.active)
            if type_hint:
                stmt = stmt.where(ThingRecord.type_hint == type_hint)
            stmt = stmt.order_by(ThingRecord.updated_at.desc()).limit(20)  # type: ignore[union-attr]
            matches = session.execute(stmt).fetchall()
            logger.info("SQL LIKE query=%r matched %d rows", query, len(matches))
            for row in matches:
                if row.id not in seen_sql:
                    seen_sql.add(row.id)
                    seed_ids.append(row.id)

    # Preference boost: run a dedicated search for preference Things so they always
    # surface when their topic matches, ranked above entity Things.
    # Preferences have type_hint='preference' and encode user-specific behavioral rules.
    if search_queries and type_hint != "preference":
        preference_ids: list[str] = []
        if vc > 0:
            preference_ids = vector_search(
                queries=search_queries,
                n_results=10,
                active_only=active_only,
                type_hint="preference",
                user_id=user_id,
            )
        if not preference_ids:
            pref_seen: set[str] = set()
            for query in search_queries[:3]:
                pattern = f"%{query}%"
                pref_stmt = select(ThingRecord.id).where(
                    ThingRecord.type_hint == "preference",
                    or_(
                        ThingRecord.title.like(pattern),  # type: ignore[union-attr]
                        cast(ThingRecord.data, String).like(pattern),
                    ),
                    user_filter_clause(ThingRecord.user_id, user_id),
                )
                if active_only:
                    pref_stmt = pref_stmt.where(ThingRecord.active)
                pref_stmt = pref_stmt.order_by(ThingRecord.updated_at.desc()).limit(10)  # type: ignore[union-attr]
                for row in session.execute(pref_stmt).fetchall():
                    if row.id not in pref_seen:
                        pref_seen.add(row.id)
                        preference_ids.append(row.id)
        if preference_ids:
            pref_set = set(preference_ids)
            seed_ids = preference_ids + [sid for sid in seed_ids if sid not in pref_set]
            logger.info("Preference boost: %d matching preferences ranked first", len(preference_ids))

    logger.info("Total seed IDs before hydration: %d", len(seed_ids))

    family_results = _fetch_with_family(session, seed_ids)
    logger.info("After family expansion: %d Things", len(family_results))

    for thing in family_results:
        if thing["id"] not in seen_ids:
            seen_ids.add(thing["id"])
            results.append(thing)

    if len(results) < 5:
        recent_stmt = (
            select(ThingRecord)
            .where(
                ThingRecord.active,
                user_filter_clause(ThingRecord.user_id, user_id),
            )
            .order_by(ThingRecord.updated_at.desc())  # type: ignore[union-attr]
            .limit(10)
        )
        for rec in session.exec(recent_stmt).all():
            if rec.id not in seen_ids:
                seen_ids.add(rec.id)
                results.append(_parse_thing_open_questions(rec.model_dump()))

    # -----------------------------------------------------------------------
    # Preference boost: ensure preference Things matching the topic are
    # included and ranked higher than entity Things.  Preferences are almost
    # always relevant when their topic matches. (GH#191 task 3)
    # Skip when caller already filters to type_hint='preference' — the main
    # search already covers this and a second boost would be redundant.
    # -----------------------------------------------------------------------
    if type_hint == "preference":
        return results

    pref_ids: list[str] = []
    pref_vc = vector_count()
    if pref_vc > 0:
        pref_ids = vector_search(
            queries=search_queries,
            n_results=10,
            active_only=active_only,
            type_hint="preference",
            user_id=user_id,
        )
    if not pref_ids:
        # SQL fallback for preference Things
        for query in search_queries[:3]:
            pattern = f"%{query}%"
            pref_stmt2 = select(ThingRecord.id).where(
                ThingRecord.type_hint == "preference",
                or_(
                    ThingRecord.title.like(pattern),  # type: ignore[union-attr]
                    cast(ThingRecord.data, String).like(pattern),
                ),
                user_filter_clause(ThingRecord.user_id, user_id),
            )
            if active_only:
                pref_stmt2 = pref_stmt2.where(ThingRecord.active)
            pref_stmt2 = pref_stmt2.order_by(ThingRecord.updated_at.desc()).limit(10)  # type: ignore[union-attr]
            for row in session.execute(pref_stmt2).fetchall():
                if row.id not in set(pref_ids):
                    pref_ids.append(row.id)

    if pref_ids:
        # Hydrate any preference Things not already in results
        new_pref_ids = [pid for pid in pref_ids if pid not in seen_ids]
        if new_pref_ids:
            pref_things = _fetch_with_family(session, new_pref_ids)
            for t in pref_things:
                if t["id"] not in seen_ids:
                    seen_ids.add(t["id"])
                    results.append(t)

        # Re-order: preference Things first, then everything else
        preference_results = [t for t in results if t.get("type_hint") == "preference"]
        other_results = [t for t in results if t.get("type_hint") != "preference"]
        results = preference_results + other_results

        logger.info(
            "Preference boost: %d preference Things promoted to top of %d results",
            len(preference_results),
            len(results),
        )

    return results


# ---------------------------------------------------------------------------
# ChatPipeline — Reasoning + Response pipeline
# ---------------------------------------------------------------------------


class ChatPipeline:
    """Chat pipeline with reasoning agent (context-fetching via tool) + response agent.

    The reasoning agent fetches its own context on-demand via the fetch_context
    tool, replacing the former separate context agent pipeline stage.
    """

    def __init__(
        self,
        user_id: str,
        user_api_key: str | None = None,
        user_models: Mapping[str, str | None] | None = None,
        context_window: int = 10,
        mode: str = "normal",
        interaction_style: str = "auto",
    ):
        self.user_id = user_id
        self.user_api_key = user_api_key
        self.user_models: Mapping[str, str | None] = user_models or {}
        self.context_window = context_window
        self.mode = mode
        self.interaction_style = interaction_style

        # The context agent is no longer a separate stage — it's registered
        # as a tool on the reasoning agent, called on-demand via fetch_context.
        # Agent instances are created per-call inside run_reasoning_agent() and
        # run_response_agent().

    # ------------------------------------------------------------------
    # Calendar data fetching
    # ------------------------------------------------------------------

    def _is_new_user(self) -> bool:
        """Return True if this user has no surfaced, active Things (new-user onboarding)."""
        with Session(_engine_mod.engine) as session:
            surfaced_count = session.exec(
                select(func.count(ThingRecord.id)).where(
                    user_filter_clause(ThingRecord.user_id, self.user_id),
                    ThingRecord.surface,
                    ThingRecord.active,
                )
            ).one()
        return surfaced_count == 0

    def _fetch_calendar_events(self) -> list[dict] | None:
        """Fetch upcoming calendar events if Google Calendar is connected."""
        if gcal_connected(user_id=self.user_id):
            try:
                return fetch_upcoming_events(max_results=15, days_ahead=7, user_id=self.user_id)
            except Exception:
                return None
        return None

    # ------------------------------------------------------------------
    # Open questions collection
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_open_questions(
        relevant_things: list[dict[str, Any]],
        applied_changes: dict[str, Any],
    ) -> dict[str, list[str]]:
        """Collect open_questions from relevant Things and newly created/updated Things."""
        open_questions_by_thing: dict[str, list[str]] = {}
        for thing in relevant_things:
            oq = thing.get("open_questions")
            if oq:
                parsed = json.loads(oq) if isinstance(oq, str) else oq
                if parsed:
                    open_questions_by_thing[thing.get("title", thing["id"])] = parsed
        for thing in applied_changes.get("created", []) + applied_changes.get("updated", []):
            oq = thing.get("open_questions")
            if oq:
                parsed = json.loads(oq) if isinstance(oq, str) else oq
                if parsed:
                    open_questions_by_thing[thing.get("title", thing.get("id", ""))] = parsed
        return open_questions_by_thing

    # ------------------------------------------------------------------
    # Full pipeline execution
    # ------------------------------------------------------------------

    @staticmethod
    def _record_stage_usage(
        span: Any,
        stage: str,
        usage: UsageStats,
        calls_before: int,
    ) -> None:
        """Set span attributes for token counts from API calls made during a stage."""
        new_calls = usage.calls[calls_before:]
        stage_prompt = sum(c.prompt_tokens for c in new_calls)
        stage_completion = sum(c.completion_tokens for c in new_calls)
        stage_cost = sum(c.cost_usd for c in new_calls)
        models_used = list({c.model for c in new_calls}) if new_calls else []

        span.set_attribute(f"reli.{stage}.prompt_tokens", stage_prompt)
        span.set_attribute(f"reli.{stage}.completion_tokens", stage_completion)
        span.set_attribute(f"reli.{stage}.total_tokens", stage_prompt + stage_completion)
        span.set_attribute(f"reli.{stage}.cost_usd", round(stage_cost, 6))
        span.set_attribute(f"reli.{stage}.api_calls", len(new_calls))
        if models_used:
            span.set_attribute(f"reli.{stage}.model", models_used[0])

    async def run(
        self,
        message: str,
        history: list[dict[str, Any]],
        session_id: str = "",
    ) -> "PipelineResult":
        """Run the full chat pipeline: reasoning (with context tool) → response.

        The reasoning agent fetches context on-demand via its fetch_context
        tool, replacing the former separate context agent stage.
        """
        usage = UsageStats()

        # Warm start: fetch context Things from recent messages
        warm_context = _fetch_warm_context(session_id, self.user_id) if session_id else []

        # Detect new user (0 surfaced, active Things) for onboarding mode
        is_new_user = self._is_new_user()

        with _tracer.start_as_current_span("reli.pipeline") as pipeline_span:
            pipeline_span.set_attribute("reli.user_id", self.user_id)
            pipeline_span.set_attribute("reli.message_length", len(message))
            pipeline_span.set_attribute("reli.history_length", len(history))
            pipeline_span.set_attribute("reli.warm_context_count", len(warm_context))
            pipeline_span.set_attribute("reli.is_new_user", is_new_user)

            try:
                # Pre-fetch calendar events (cheap, always useful if connected)
                calendar_events = self._fetch_calendar_events()

                # Stage 1: Reasoning Agent (fetches its own context via tool)
                calls_before = len(usage.calls)
                with _tracer.start_as_current_span("reli.stage.reasoning") as reason_span:
                    reason_span.set_attribute(
                        "reli.reasoning.model",
                        self.user_models.get("reasoning") or REQUESTY_REASONING_MODEL,
                    )
                    try:
                        reasoning_result = await run_reasoning_agent(
                            message,
                            history,
                            [],
                            None,
                            None,
                            calendar_events,
                            relationships=None,
                            usage_stats=usage,
                            context_window=self.context_window,
                            api_key=self.user_api_key,
                            model=self.user_models.get("reasoning"),
                            user_id=self.user_id,
                            mode=self.mode,
                            interaction_style=self.interaction_style,
                            session_id=session_id,
                            warm_context=warm_context,
                            is_new_user=is_new_user,
                        )

                        # Extract context fetched by the reasoning agent's tool
                        fetched_ctx = reasoning_result.get("fetched_context", {})
                        relevant_things = fetched_ctx.get("things", [])
                        context_relationships = fetched_ctx.get("relationships", [])

                        questions_for_user = reasoning_result.get("questions_for_user", [])
                        priority_question = reasoning_result.get("priority_question", "")
                        reasoning_summary = reasoning_result.get("reasoning_summary", "")
                        briefing_mode = reasoning_result.get("briefing_mode", False)
                        applied_changes = reasoning_result.get(
                            "applied_changes",
                            {
                                "created": [],
                                "updated": [],
                                "deleted": [],
                                "merged": [],
                                "relationships_created": [],
                            },
                        )

                        n_created = len(applied_changes.get("created", []))
                        n_updated = len(applied_changes.get("updated", []))
                        n_deleted = len(applied_changes.get("deleted", []))
                        reason_span.set_attribute("reli.reasoning.things_fetched", len(relevant_things))
                        reason_span.set_attribute("reli.reasoning.changes_created", n_created)
                        reason_span.set_attribute("reli.reasoning.changes_updated", n_updated)
                        reason_span.set_attribute("reli.reasoning.changes_deleted", n_deleted)
                        reason_span.set_attribute("reli.reasoning.questions_count", len(questions_for_user))
                        reason_span.set_attribute("reli.reasoning.briefing_mode", briefing_mode)
                        self._record_stage_usage(reason_span, "reasoning", usage, calls_before)
                    except Exception as exc:
                        set_span_error(reason_span, exc)
                        raise

                open_questions_by_thing = self._collect_open_questions(relevant_things, applied_changes)

                # Stage 2: Response Agent
                calls_before = len(usage.calls)
                with _tracer.start_as_current_span("reli.stage.response") as resp_span:
                    resp_span.set_attribute(
                        "reli.response.model",
                        self.user_models.get("response") or REQUESTY_RESPONSE_MODEL,
                    )
                    try:
                        response_result = await run_response_agent(
                            message,
                            reasoning_summary,
                            questions_for_user,
                            applied_changes,
                            None,
                            usage_stats=usage,
                            open_questions_by_thing=open_questions_by_thing or None,
                            api_key=self.user_api_key,
                            model=self.user_models.get("response"),
                            priority_question=priority_question,
                            briefing_mode=briefing_mode,
                            interaction_style=self.interaction_style,
                            user_id=self.user_id,
                        )
                        reply = response_result.text
                        referenced_things = response_result.referenced_things
                        resp_span.set_attribute("reli.response.reply_length", len(reply))
                        self._record_stage_usage(resp_span, "response", usage, calls_before)
                    except Exception as exc:
                        set_span_error(resp_span, exc)
                        raise

                # Record totals on the pipeline span
                pipeline_span.set_attribute("reli.total_prompt_tokens", usage.prompt_tokens)
                pipeline_span.set_attribute("reli.total_completion_tokens", usage.completion_tokens)
                pipeline_span.set_attribute("reli.total_tokens", usage.total_tokens)
                pipeline_span.set_attribute("reli.total_cost_usd", round(usage.cost_usd, 6))
                pipeline_span.set_attribute("reli.total_api_calls", usage.api_calls)

            except Exception as exc:
                set_span_error(pipeline_span, exc)
                raise

        return PipelineResult(
            reply=reply,
            applied_changes=applied_changes,
            referenced_things=referenced_things,
            questions_for_user=questions_for_user,
            priority_question=priority_question,
            reasoning_summary=reasoning_summary,
            briefing_mode=briefing_mode,
            relevant_things=relevant_things,
            context_relationships=context_relationships,
            web_results=None,
            gmail_context=[],
            calendar_events=calendar_events,
            open_questions_by_thing=open_questions_by_thing,
            usage=usage,
        )

    async def run_stream(
        self,
        message: str,
        history: list[dict[str, Any]],
        session_id: str = "",
    ) -> AsyncIterator[PipelineEvent]:
        """Run the pipeline with streaming, yielding events for SSE delivery.

        Yields PipelineEvent objects for stage transitions and response tokens.
        The final PipelineEvent with type="complete" contains the full
        PipelineResult.
        """
        usage = UsageStats()

        # Warm start: fetch context Things from recent messages
        warm_context = _fetch_warm_context(session_id, self.user_id) if session_id else []

        # Detect new user (0 surfaced, active Things) for onboarding mode
        is_new_user = self._is_new_user()

        with _tracer.start_as_current_span("reli.pipeline.stream") as pipeline_span:
            pipeline_span.set_attribute("reli.user_id", self.user_id)
            pipeline_span.set_attribute("reli.message_length", len(message))
            pipeline_span.set_attribute("reli.history_length", len(history))
            pipeline_span.set_attribute("reli.streaming", True)
            pipeline_span.set_attribute("reli.warm_context_count", len(warm_context))
            pipeline_span.set_attribute("reli.is_new_user", is_new_user)

            try:
                # Pre-fetch calendar events
                calendar_events = self._fetch_calendar_events()

                # Stage 1: Reasoning Agent (fetches its own context via tool)
                yield PipelineEvent(type="stage_start", stage="reasoning")

                calls_before = len(usage.calls)
                with _tracer.start_as_current_span("reli.stage.reasoning") as reason_span:
                    reason_span.set_attribute(
                        "reli.reasoning.model",
                        self.user_models.get("reasoning") or REQUESTY_REASONING_MODEL,
                    )
                    try:
                        reasoning_result = await run_reasoning_agent(
                            message,
                            history,
                            [],
                            None,
                            None,
                            calendar_events,
                            relationships=None,
                            usage_stats=usage,
                            context_window=self.context_window,
                            api_key=self.user_api_key,
                            model=self.user_models.get("reasoning"),
                            user_id=self.user_id,
                            mode=self.mode,
                            interaction_style=self.interaction_style,
                            session_id=session_id,
                            warm_context=warm_context,
                            is_new_user=is_new_user,
                        )

                        fetched_ctx = reasoning_result.get("fetched_context", {})
                        relevant_things = fetched_ctx.get("things", [])
                        context_relationships = fetched_ctx.get("relationships", [])

                        questions_for_user = reasoning_result.get("questions_for_user", [])
                        priority_question = reasoning_result.get("priority_question", "")
                        reasoning_summary = reasoning_result.get("reasoning_summary", "")
                        briefing_mode = reasoning_result.get("briefing_mode", False)
                        applied_changes = reasoning_result.get(
                            "applied_changes",
                            {
                                "created": [],
                                "updated": [],
                                "deleted": [],
                                "merged": [],
                                "relationships_created": [],
                            },
                        )

                        n_created = len(applied_changes.get("created", []))
                        n_updated = len(applied_changes.get("updated", []))
                        n_deleted = len(applied_changes.get("deleted", []))
                        reason_span.set_attribute("reli.reasoning.things_fetched", len(relevant_things))
                        reason_span.set_attribute("reli.reasoning.changes_created", n_created)
                        reason_span.set_attribute("reli.reasoning.changes_updated", n_updated)
                        reason_span.set_attribute("reli.reasoning.changes_deleted", n_deleted)
                        reason_span.set_attribute("reli.reasoning.questions_count", len(questions_for_user))
                        reason_span.set_attribute("reli.reasoning.briefing_mode", briefing_mode)
                        self._record_stage_usage(reason_span, "reasoning", usage, calls_before)
                    except Exception as exc:
                        set_span_error(reason_span, exc)
                        raise

                open_questions_by_thing = self._collect_open_questions(relevant_things, applied_changes)

                yield PipelineEvent(type="stage_complete", stage="reasoning")

                # Stage 2: Response Agent (streaming)
                yield PipelineEvent(type="stage_start", stage="response")

                calls_before = len(usage.calls)
                reply_parts: list[str] = []
                with _tracer.start_as_current_span("reli.stage.response") as resp_span:
                    resp_span.set_attribute(
                        "reli.response.model",
                        self.user_models.get("response") or REQUESTY_RESPONSE_MODEL,
                    )
                    try:
                        async for token in run_response_agent_stream(
                            message,
                            reasoning_summary,
                            questions_for_user,
                            applied_changes,
                            None,
                            usage_stats=usage,
                            open_questions_by_thing=open_questions_by_thing or None,
                            api_key=self.user_api_key,
                            model=self.user_models.get("response"),
                            priority_question=priority_question,
                            briefing_mode=briefing_mode,
                            interaction_style=self.interaction_style,
                            user_id=self.user_id,
                        ):
                            reply_parts.append(token)
                            yield PipelineEvent(type="token", data=token)

                        raw_reply = "".join(reply_parts)
                        response_result = parse_response(raw_reply)
                        reply = response_result.text
                        referenced_things = response_result.referenced_things
                        resp_span.set_attribute("reli.response.reply_length", len(reply))
                        self._record_stage_usage(resp_span, "response", usage, calls_before)
                    except Exception as exc:
                        set_span_error(resp_span, exc)
                        raise

                yield PipelineEvent(type="stage_complete", stage="response")

                # Record totals on the pipeline span
                pipeline_span.set_attribute("reli.total_prompt_tokens", usage.prompt_tokens)
                pipeline_span.set_attribute("reli.total_completion_tokens", usage.completion_tokens)
                pipeline_span.set_attribute("reli.total_tokens", usage.total_tokens)
                pipeline_span.set_attribute("reli.total_cost_usd", round(usage.cost_usd, 6))
                pipeline_span.set_attribute("reli.total_api_calls", usage.api_calls)

            except Exception as exc:
                set_span_error(pipeline_span, exc)
                raise

        # Yield final result
        yield PipelineEvent(
            type="complete",
            data=PipelineResult(
                reply=reply,
                applied_changes=applied_changes,
                referenced_things=referenced_things,
                questions_for_user=questions_for_user,
                priority_question=priority_question,
                reasoning_summary=reasoning_summary,
                briefing_mode=briefing_mode,
                relevant_things=relevant_things,
                context_relationships=context_relationships,
                web_results=None,
                gmail_context=[],
                calendar_events=calendar_events,
                open_questions_by_thing=open_questions_by_thing,
                usage=usage,
            ),
        )
