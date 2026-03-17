"""ADK SequentialAgent pipeline for the Reli chat pipeline.

Wires the 3 converted agents (context, reasoning, response) into an ADK
SequentialAgent, replacing the manual orchestration previously in chat.py.

The pipeline handles:
  - Context gathering (with iterative refinement loop)
  - Database retrieval, web search, Gmail, calendar
  - Reasoning with tool-based storage changes
  - Streaming response generation
"""

import json
import logging
import sqlite3
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from google.adk.agents import LlmAgent, SequentialAgent

from .agents import (
    CONTEXT_AGENT_SYSTEM,
    REQUESTY_REASONING_MODEL,
    REQUESTY_RESPONSE_MODEL,
    RESPONSE_AGENT_SYSTEM,
    UsageStats,
)
from .auth import user_filter
from .context_agent import _make_litellm_model, run_context_agent, run_context_refinement
from .database import db
from .google_calendar import fetch_upcoming_events
from .google_calendar import is_connected as gcal_connected
from .reasoning_agent import REASONING_AGENT_TOOL_SYSTEM, run_reasoning_agent
from .response_agent import run_response_agent, run_response_agent_stream
from .vector_store import VECTOR_SEARCH_THRESHOLD, vector_count, vector_search
from .web_search import google_search, is_search_configured

logger = logging.getLogger(__name__)

# Maximum iterations for the context refinement loop
MAX_CONTEXT_ITERATIONS = 4


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
        vc, sql_thing_count, VECTOR_SEARCH_THRESHOLD, use_vector, active_only, type_hint,
    )

    seed_ids: list[str] = []

    if use_vector:
        seed_ids = vector_search(
            queries=search_queries, n_results=20, active_only=active_only,
            type_hint=type_hint, user_id=user_id,
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


def _fetch_gmail_context(query: str, user_id: str = "") -> list[dict[str, Any]]:
    """Fetch Gmail messages matching query for injection into the reasoning agent."""
    try:
        from .routers.gmail import _get_service, _parse_message

        service = _get_service(user_id=user_id)
        result = service.users().messages().list(userId="me", q=query, maxResults=10).execute()
        msg_refs = result.get("messages", [])
        messages = []
        for ref in msg_refs[:10]:
            msg = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
            parsed = _parse_message(msg)
            messages.append({
                "id": parsed.id,
                "subject": parsed.subject,
                "from": parsed.sender,
                "date": parsed.date,
                "snippet": parsed.snippet,
            })
        return messages
    except Exception:
        return []


# ---------------------------------------------------------------------------
# ChatPipeline — ADK SequentialAgent orchestration
# ---------------------------------------------------------------------------


class ChatPipeline:
    """ADK-based chat pipeline using SequentialAgent.

    Wires context, reasoning, and response agents into an ADK SequentialAgent,
    centralizing the orchestration that was previously spread across chat.py
    endpoint functions.
    """

    def __init__(
        self,
        user_id: str,
        user_api_key: str | None = None,
        user_models: Mapping[str, str | None] | None = None,
        context_window: int = 10,
    ):
        self.user_id = user_id
        self.user_api_key = user_api_key
        self.user_models: Mapping[str, str | None] = user_models or {}
        self.context_window = context_window

        # Create ADK LlmAgent instances for each pipeline stage
        context_model = _make_litellm_model(
            model=self.user_models.get("context"), api_key=user_api_key,
        )
        reasoning_model = _make_litellm_model(
            model=self.user_models.get("reasoning") or REQUESTY_REASONING_MODEL,
            api_key=user_api_key,
        )
        response_model = _make_litellm_model(
            model=self.user_models.get("response") or REQUESTY_RESPONSE_MODEL,
            api_key=user_api_key,
        )

        self._context_agent = LlmAgent(
            name="context_agent",
            description="Generates search parameters to find relevant Things in the database.",
            model=context_model,
            instruction=CONTEXT_AGENT_SYSTEM,
        )
        self._reasoning_agent = LlmAgent(
            name="reasoning_agent",
            description="Reasons about user requests and executes storage changes via tools.",
            model=reasoning_model,
            instruction=REASONING_AGENT_TOOL_SYSTEM,
        )
        self._response_agent = LlmAgent(
            name="response_agent",
            description="Generates friendly, conversational responses to the user.",
            model=response_model,
            instruction=RESPONSE_AGENT_SYSTEM,
        )

        # Wire all 3 agents into a SequentialAgent defining the pipeline structure.
        # The pipeline is executed stage-by-stage via run()/run_stream() because
        # inter-agent processing (DB retrieval, refinement loops, web search)
        # requires custom logic between stages that goes beyond simple sequential
        # conversation flow.
        self.pipeline = SequentialAgent(
            name="reli_chat_pipeline",
            description="Context → Reasoning → Response chat pipeline for Reli.",
            sub_agents=[
                self._context_agent,
                self._reasoning_agent,
                self._response_agent,
            ],
        )

    # ------------------------------------------------------------------
    # Context gathering (Stage 1)
    # ------------------------------------------------------------------

    async def _run_context_stage(
        self,
        message: str,
        history: list[dict[str, Any]],
        usage: UsageStats,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Run context agent with iterative refinement and data gathering.

        Returns (context_result, relevant_things, context_relationships).
        """
        context_result = await run_context_agent(
            message, history, usage_stats=usage, context_window=self.context_window,
            api_key=self.user_api_key, model=self.user_models.get("context"),
        )
        search_queries = context_result.get("search_queries", [message])
        fetch_ids = context_result.get("fetch_ids", [])
        filter_params = context_result.get("filter_params", {})

        logger.info(
            "Context agent result — search_queries=%r, fetch_ids=%r, filter_params=%r, gmail_query=%r, "
            "needs_web_search=%r, include_calendar=%r",
            search_queries, fetch_ids, filter_params,
            context_result.get("gmail_query"),
            context_result.get("needs_web_search"),
            context_result.get("include_calendar"),
        )

        # Iterative context gathering
        all_queries: list[str] = list(search_queries)
        seen_thing_ids: set[str] = set()
        relevant_things: list[dict[str, Any]] = []

        # Initial fetch
        with db() as conn:
            initial_things = _fetch_relevant_things(conn, search_queries, filter_params, user_id=self.user_id)
            for t in initial_things:
                if t["id"] not in seen_thing_ids:
                    seen_thing_ids.add(t["id"])
                    relevant_things.append(t)

            if fetch_ids:
                id_things = _fetch_with_family(conn, [
                    tid for tid in fetch_ids if tid not in seen_thing_ids
                ])
                for t in id_things:
                    if t["id"] not in seen_thing_ids:
                        seen_thing_ids.add(t["id"])
                        relevant_things.append(t)

        logger.info(
            "Initial retrieval: %d Things for queries %r",
            len(relevant_things), search_queries,
        )

        # Refinement loop
        for iteration in range(1, MAX_CONTEXT_ITERATIONS):
            if not relevant_things:
                break

            thing_relationships: list[dict[str, Any]] = []
            with db() as conn:
                thing_id_list = list(seen_thing_ids)
                if thing_id_list:
                    ph = ",".join("?" for _ in thing_id_list)
                    rel_rows = conn.execute(
                        f"SELECT from_thing_id, to_thing_id, relationship_type FROM thing_relationships "
                        f"WHERE from_thing_id IN ({ph}) OR to_thing_id IN ({ph})",
                        thing_id_list + thing_id_list,
                    ).fetchall()
                    thing_relationships = [dict(r) for r in rel_rows]

            refinement = await run_context_refinement(
                message, history, relevant_things, all_queries,
                relationships=thing_relationships,
                usage_stats=usage, context_window=self.context_window,
                api_key=self.user_api_key, model=self.user_models.get("context"),
            )

            if refinement.get("done", True):
                logger.info("Context refinement done after %d iteration(s)", iteration)
                break

            new_queries = refinement.get("search_queries", [])
            thing_ids_to_fetch = refinement.get("thing_ids", [])
            refinement_filter = refinement.get("filter_params", filter_params)

            if not new_queries and not thing_ids_to_fetch:
                logger.info("Context refinement returned no new queries or IDs, stopping")
                break

            prev_count = len(relevant_things)

            if new_queries:
                all_queries.extend(new_queries)
                with db() as conn:
                    new_things = _fetch_relevant_things(conn, new_queries, refinement_filter, user_id=self.user_id)
                    for t in new_things:
                        if t["id"] not in seen_thing_ids:
                            seen_thing_ids.add(t["id"])
                            relevant_things.append(t)

            if thing_ids_to_fetch:
                with db() as conn:
                    new_from_ids = _fetch_with_family(conn, [
                        tid for tid in thing_ids_to_fetch if tid not in seen_thing_ids
                    ])
                    for t in new_from_ids:
                        if t["id"] not in seen_thing_ids:
                            seen_thing_ids.add(t["id"])
                            relevant_things.append(t)

            new_count = len(relevant_things) - prev_count
            logger.info(
                "Context refinement iteration %d: +%d new Things (total %d), queries=%r, ids=%r",
                iteration, new_count, len(relevant_things), new_queries, thing_ids_to_fetch,
            )

            if new_count == 0:
                logger.info("Context refinement found nothing new, stopping")
                break

        # Fetch relationships for all relevant things and update last_referenced
        context_relationships: list[dict[str, Any]] = []
        if relevant_things:
            with db() as conn:
                now = datetime.now(timezone.utc).isoformat()
                ids = [t["id"] for t in relevant_things]
                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"UPDATE things SET last_referenced = ? WHERE id IN ({placeholders})",
                    [now] + ids,
                )
                rel_rows = conn.execute(
                    f"SELECT from_thing_id, to_thing_id, relationship_type "
                    f"FROM thing_relationships "
                    f"WHERE from_thing_id IN ({placeholders}) OR to_thing_id IN ({placeholders})",
                    ids + ids,
                ).fetchall()
                context_relationships = [dict(r) for r in rel_rows]

        logger.info(
            "Final context: %d Things, %d relationships after up to %d iterations",
            len(relevant_things), len(context_relationships), MAX_CONTEXT_ITERATIONS,
        )

        return context_result, relevant_things, context_relationships

    # ------------------------------------------------------------------
    # External data fetching
    # ------------------------------------------------------------------

    async def _fetch_external_data(
        self,
        message: str,
        context_result: dict[str, Any],
    ) -> tuple[list[dict] | None, list[dict[str, Any]], list[dict] | None]:
        """Fetch web search results, Gmail context, and calendar events.

        Returns (web_results, gmail_context, calendar_events).
        """
        # Web search
        web_results: list[dict] | None = None
        if context_result.get("needs_web_search") and is_search_configured():
            web_query = context_result.get("web_search_query") or message
            results = await google_search(web_query)
            if results:
                web_results = [r.to_dict() for r in results]

        # Gmail
        gmail_query = context_result.get("gmail_query")
        gmail_context = _fetch_gmail_context(gmail_query, user_id=self.user_id) if gmail_query else []

        # Calendar
        calendar_events: list[dict] | None = None
        if context_result.get("include_calendar") and gcal_connected(user_id=self.user_id):
            try:
                calendar_events = fetch_upcoming_events(max_results=15, days_ahead=7, user_id=self.user_id)
            except Exception:
                calendar_events = None

        return web_results, gmail_context, calendar_events

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

    async def run(
        self,
        message: str,
        history: list[dict[str, Any]],
    ) -> PipelineResult:
        """Run the full chat pipeline: context → reasoning → response.

        Executes each sub-agent of the SequentialAgent in order, with
        inter-agent data gathering (DB retrieval, web search, etc.)
        between stages.
        """
        usage = UsageStats()

        # Stage 1: Context Agent (iterative loop)
        context_result, relevant_things, context_relationships = (
            await self._run_context_stage(message, history, usage)
        )

        # External data
        web_results, gmail_context, calendar_events = (
            await self._fetch_external_data(message, context_result)
        )

        # Stage 2: Reasoning Agent
        reasoning_result = await run_reasoning_agent(
            message, history, relevant_things, web_results, gmail_context,
            calendar_events, relationships=context_relationships,
            usage_stats=usage, context_window=self.context_window,
            api_key=self.user_api_key, model=self.user_models.get("reasoning"),
            user_id=self.user_id,
        )
        questions_for_user = reasoning_result.get("questions_for_user", [])
        priority_question = reasoning_result.get("priority_question", "")
        reasoning_summary = reasoning_result.get("reasoning_summary", "")
        briefing_mode = reasoning_result.get("briefing_mode", False)
        applied_changes = reasoning_result.get("applied_changes", {
            "created": [], "updated": [], "deleted": [], "merged": [], "relationships_created": [],
        })

        open_questions_by_thing = self._collect_open_questions(relevant_things, applied_changes)

        # Stage 3: Response Agent
        reply = await run_response_agent(
            message, reasoning_summary, questions_for_user, applied_changes,
            web_results, usage_stats=usage,
            open_questions_by_thing=open_questions_by_thing or None,
            api_key=self.user_api_key, model=self.user_models.get("response"),
            priority_question=priority_question, briefing_mode=briefing_mode,
        )

        return PipelineResult(
            reply=reply,
            applied_changes=applied_changes,
            questions_for_user=questions_for_user,
            priority_question=priority_question,
            reasoning_summary=reasoning_summary,
            briefing_mode=briefing_mode,
            relevant_things=relevant_things,
            context_relationships=context_relationships,
            web_results=web_results,
            gmail_context=gmail_context,
            calendar_events=calendar_events,
            open_questions_by_thing=open_questions_by_thing,
            usage=usage,
        )

    async def run_stream(
        self,
        message: str,
        history: list[dict[str, Any]],
    ) -> AsyncIterator[PipelineEvent]:
        """Run the pipeline with streaming, yielding events for SSE delivery.

        Yields PipelineEvent objects for stage transitions and response tokens.
        The final PipelineEvent with type="complete" contains the full
        PipelineResult.
        """
        usage = UsageStats()

        # Stage 1: Context Agent
        yield PipelineEvent(type="stage_start", stage="context")

        context_result, relevant_things, context_relationships = (
            await self._run_context_stage(message, history, usage)
        )

        # External data
        web_results, gmail_context, calendar_events = (
            await self._fetch_external_data(message, context_result)
        )

        yield PipelineEvent(type="stage_complete", stage="context")

        # Stage 2: Reasoning Agent
        yield PipelineEvent(type="stage_start", stage="reasoning")

        reasoning_result = await run_reasoning_agent(
            message, history, relevant_things, web_results, gmail_context,
            calendar_events, relationships=context_relationships,
            usage_stats=usage, context_window=self.context_window,
            api_key=self.user_api_key, model=self.user_models.get("reasoning"),
            user_id=self.user_id,
        )
        questions_for_user = reasoning_result.get("questions_for_user", [])
        priority_question = reasoning_result.get("priority_question", "")
        reasoning_summary = reasoning_result.get("reasoning_summary", "")
        briefing_mode = reasoning_result.get("briefing_mode", False)
        applied_changes = reasoning_result.get("applied_changes", {
            "created": [], "updated": [], "deleted": [], "merged": [], "relationships_created": [],
        })

        open_questions_by_thing = self._collect_open_questions(relevant_things, applied_changes)

        yield PipelineEvent(type="stage_complete", stage="reasoning")

        # Stage 3: Response Agent (streaming)
        yield PipelineEvent(type="stage_start", stage="response")

        reply_parts: list[str] = []
        async for token in run_response_agent_stream(
            message, reasoning_summary, questions_for_user, applied_changes,
            web_results, usage_stats=usage,
            open_questions_by_thing=open_questions_by_thing or None,
            api_key=self.user_api_key, model=self.user_models.get("response"),
            priority_question=priority_question, briefing_mode=briefing_mode,
        ):
            reply_parts.append(token)
            yield PipelineEvent(type="token", data=token)

        reply = "".join(reply_parts)

        yield PipelineEvent(type="stage_complete", stage="response")

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
                web_results=web_results,
                gmail_context=gmail_context,
                calendar_events=calendar_events,
                open_questions_by_thing=open_questions_by_thing,
                usage=usage,
            ),
        )
