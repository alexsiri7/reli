"""Chat pipeline for Reli: reasoning agent + response agent.

The reasoning agent fetches its own context on-demand via the fetch_context
tool (formerly a separate pipeline stage). The pipeline handles:
  - Reasoning with on-demand context fetching and tool-based storage changes
  - Streaming response generation
"""

import asyncio
import json
import logging
import sqlite3
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any

from .agents import (
    REQUESTY_REASONING_MODEL,
    REQUESTY_RESPONSE_MODEL,
    UsageStats,
)
from .auth import user_filter
from .database import db
from .google_calendar import fetch_upcoming_events
from .google_calendar import is_connected as gcal_connected
from .reasoning_agent import run_reasoning_agent
from .response_agent import run_response_agent, run_response_agent_stream
from .signal_detector import detect_and_apply_signals
from .tracing import get_tracer, set_span_error
from .vector_store import VECTOR_SEARCH_THRESHOLD, vector_count, vector_search

logger = logging.getLogger(__name__)
_tracer = get_tracer()


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


@dataclass
class PipelineEvent:
    """Event emitted during streaming pipeline execution."""

    type: str  # "stage_start", "stage_complete", "token"
    stage: str = ""
    data: Any = None


# ---------------------------------------------------------------------------
# Data-gathering helpers (moved from chat.py)
# ---------------------------------------------------------------------------


def _sql_things_count(conn: sqlite3.Connection) -> int:
    """Return total number of Things in SQLite."""
    row = conn.execute("SELECT COUNT(*) as cnt FROM things").fetchone()
    return row["cnt"] if row else 0


def _fetch_with_family(conn: sqlite3.Connection, seed_ids: list[str]) -> list[dict[str, Any]]:
    """Given seed Thing IDs, return those Things plus their parents, children, and related Things via relationships."""
    seen_ids: set[str] = set()
    results: list[dict] = []

    def _add_row(row: sqlite3.Row) -> None:
        if row["id"] not in seen_ids:
            seen_ids.add(row["id"])
            results.append(dict(row))

    for thing_id in seed_ids:
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
        if row:
            _add_row(row)
            if row["parent_id"]:
                parent = conn.execute("SELECT * FROM things WHERE id = ?", (row["parent_id"],)).fetchone()
                if parent:
                    _add_row(parent)
            children = conn.execute("SELECT * FROM things WHERE parent_id = ?", (thing_id,)).fetchall()
            for child in children:
                _add_row(child)
            rels = conn.execute(
                "SELECT * FROM thing_relationships WHERE from_thing_id = ? OR to_thing_id = ?",
                (thing_id, thing_id),
            ).fetchall()
            for rel in rels:
                other_id = rel["to_thing_id"] if rel["from_thing_id"] == thing_id else rel["from_thing_id"]
                if other_id not in seen_ids:
                    other = conn.execute("SELECT * FROM things WHERE id = ?", (other_id,)).fetchone()
                    if other:
                        _add_row(other)

    return results


def _fetch_user_relationships(
    conn: sqlite3.Connection,
    user_thing_id: str,
    search_queries: list[str],
    user_id: str = "",
) -> list[dict[str, Any]]:
    """Fetch 1-hop relationships from the user Thing, filtered by search query relevance."""
    if not user_thing_id or not search_queries:
        return []

    rels = conn.execute(
        "SELECT * FROM thing_relationships WHERE from_thing_id = ? OR to_thing_id = ?",
        (user_thing_id, user_thing_id),
    ).fetchall()
    if not rels:
        return []

    other_ids: list[str] = []
    for rel in rels:
        other_id = rel["to_thing_id"] if rel["from_thing_id"] == user_thing_id else rel["from_thing_id"]
        other_ids.append(other_id)

    if not other_ids:
        return []

    placeholders = ",".join("?" for _ in other_ids)
    uf_sql, uf_params = user_filter(user_id)

    like_clauses: list[str] = []
    like_params: list[str] = []
    for query in search_queries[:3]:
        pattern = f"%{query}%"
        like_clauses.append("(title LIKE ? OR data LIKE ?)")
        like_params.extend([pattern, pattern])

    query_filter = " OR ".join(like_clauses)
    sql = (
        f"SELECT * FROM things WHERE id IN ({placeholders})"
        f"{uf_sql}"
        f" AND ({query_filter})"
        " ORDER BY"
        " CASE WHEN last_referenced IS NOT NULL THEN 0 ELSE 1 END,"
        " last_referenced DESC,"
        " updated_at DESC"
        " LIMIT 10"
    )
    params: list = [*other_ids, *uf_params, *like_params]
    rows = conn.execute(sql, params).fetchall()
    logger.info(
        "User relationship search: %d edges, %d query-matched (queries=%r)",
        len(other_ids),
        len(rows),
        search_queries[:3],
    )
    return [dict(r) for r in rows]


def _fetch_user_thing(conn: sqlite3.Connection, user_id: str) -> dict[str, Any] | None:
    """Fetch the user's own Thing (type_hint='person', matching user_id)."""
    if not user_id:
        return None
    row = conn.execute(
        "SELECT * FROM things WHERE user_id = ? AND type_hint = 'person' LIMIT 1",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


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
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        rows = conn.execute(
            "SELECT applied_changes FROM chat_history"
            f" WHERE session_id = ? AND role = 'assistant'{uf_sql}"
            " ORDER BY id DESC LIMIT ?",
            [session_id, *uf_params, n_messages],
        ).fetchall()

        thing_ids: list[str] = []
        seen: set[str] = set()
        for row in rows:
            raw = row["applied_changes"]
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

        return _fetch_with_family(conn, thing_ids)


def _fetch_relevant_things(
    conn: sqlite3.Connection,
    search_queries: list[str],
    filter_params: dict[str, Any],
    user_id: str = "",
) -> list[dict[str, Any]]:
    """Retrieve relevant Things using vector search (>=500 Things) or SQL LIKE fallback (<500)."""
    active_only = filter_params.get("active_only", True)
    type_hint = filter_params.get("type_hint")
    uf_sql, uf_params = user_filter(user_id)

    user_thing = _fetch_user_thing(conn, user_id)
    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    if user_thing:
        seen_ids.add(user_thing["id"])
        results.append(user_thing)

        user_rels = _fetch_user_relationships(conn, user_thing["id"], search_queries, user_id)
        for rel_thing in user_rels:
            if rel_thing["id"] not in seen_ids:
                seen_ids.add(rel_thing["id"])
                results.append(rel_thing)

    vc = vector_count()
    use_vector = vc >= VECTOR_SEARCH_THRESHOLD
    sql_thing_count = _sql_things_count(conn)

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
            sql = "SELECT id FROM things WHERE (title LIKE ? OR data LIKE ?)"
            params: list = [pattern, pattern]
            sql += uf_sql
            params.extend(uf_params)
            if active_only:
                sql += " AND active = 1"
            if type_hint:
                sql += " AND type_hint = ?"
                params.append(type_hint)
            sql += " ORDER BY updated_at DESC LIMIT 20"
            matches = conn.execute(sql, params).fetchall()
            logger.info("SQL LIKE query=%r matched %d rows", query, len(matches))
            for row in matches:
                if row["id"] not in seen_sql:
                    seen_sql.add(row["id"])
                    seed_ids.append(row["id"])

    logger.info("Total seed IDs before hydration: %d", len(seed_ids))

    family_results = _fetch_with_family(conn, seed_ids)
    logger.info("After family expansion: %d Things", len(family_results))

    for thing in family_results:
        if thing["id"] not in seen_ids:
            seen_ids.add(thing["id"])
            results.append(thing)

    if len(results) < 5:
        recent_sql = "SELECT * FROM things WHERE active = 1" + uf_sql + " ORDER BY updated_at DESC LIMIT 10"
        for row in conn.execute(recent_sql, uf_params).fetchall():
            if row["id"] not in seen_ids:
                seen_ids.add(row["id"])
                results.append(dict(row))

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

    # ------------------------------------------------------------------
    # Personality signal detection (background)
    # ------------------------------------------------------------------

    def _schedule_signal_detection(
        self,
        message: str,
        history: list[dict[str, Any]],
        reply: str,
        usage: UsageStats,
    ) -> None:
        """Schedule personality signal detection as a background task.

        Runs asynchronously without blocking the response to the user.
        Failures are logged but never propagate to the caller.
        """
        if not self.user_id:
            return

        async def _run() -> None:
            try:
                await detect_and_apply_signals(
                    message=message,
                    history=history,
                    last_assistant_reply=reply,
                    user_id=self.user_id,
                    usage_stats=usage,
                    api_key=self.user_api_key,
                    model=self.user_models.get("response"),
                )
            except Exception:
                logger.exception("Background signal detection failed")

        asyncio.ensure_future(_run())

    # ------------------------------------------------------------------
    # Full pipeline execution
    # ------------------------------------------------------------------

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

        with _tracer.start_as_current_span("reli.pipeline") as pipeline_span:
            pipeline_span.set_attribute("reli.user_id", self.user_id)
            pipeline_span.set_attribute("reli.message_length", len(message))
            pipeline_span.set_attribute("reli.history_length", len(history))
            pipeline_span.set_attribute("reli.warm_context_count", len(warm_context))

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
                        reply = await run_response_agent(
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

                # Stage 3: Signal Detection (background, non-blocking)
                # Detect personality preference signals from the conversation
                # and update preference Things for future response adaptation.
                self._schedule_signal_detection(
                    message,
                    history,
                    reply,
                    usage,
                )

            except Exception as exc:
                set_span_error(pipeline_span, exc)
                raise

        return PipelineResult(
            reply=reply,
            applied_changes=applied_changes,
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

        with _tracer.start_as_current_span("reli.pipeline.stream") as pipeline_span:
            pipeline_span.set_attribute("reli.user_id", self.user_id)
            pipeline_span.set_attribute("reli.message_length", len(message))
            pipeline_span.set_attribute("reli.history_length", len(history))
            pipeline_span.set_attribute("reli.streaming", True)
            pipeline_span.set_attribute("reli.warm_context_count", len(warm_context))

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

                        reply = "".join(reply_parts)
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

                # Signal detection (background, non-blocking)
                self._schedule_signal_detection(
                    message,
                    history,
                    reply,
                    usage,
                )

            except Exception as exc:
                set_span_error(pipeline_span, exc)
                raise

        # Yield final result
        yield PipelineEvent(
            type="complete",
            data=PipelineResult(
                reply=reply,
                applied_changes=applied_changes,
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
