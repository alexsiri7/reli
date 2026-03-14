"""Multi-agent chat pipeline using Requesty as LLM gateway."""

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM client — Requesty OpenAI-compatible gateway
# ---------------------------------------------------------------------------

REQUESTY_BASE_URL = os.environ.get("REQUESTY_BASE_URL", "https://router.requesty.ai/v1")
REQUESTY_API_KEY = os.environ.get("REQUESTY_API_KEY", "")
REQUESTY_MODEL = os.environ.get("REQUESTY_MODEL", "google/gemini-2.0-flash-001")

# ---------------------------------------------------------------------------
# Ollama — optional local LLM for context agent
# ---------------------------------------------------------------------------

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "")


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=REQUESTY_API_KEY, base_url=REQUESTY_BASE_URL)


def _ollama_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key="ollama", base_url=f"{OLLAMA_BASE_URL}/v1")


# Per-model pricing: (input_cost_per_million, output_cost_per_million)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (2.50, 10.00),
    "anthropic/claude-sonnet-4-20250514": (3.00, 15.00),
    "google/gemini-2.0-flash-001": (0.10, 0.40),
    "google/gemini-2.5-flash-preview-05-20": (0.15, 0.60),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost from token counts using per-model pricing."""
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        # Try partial match (model name without version suffix)
        for key, val in MODEL_PRICING.items():
            if model.startswith(key.split("-")[0]) or key.startswith(model.split("-")[0]):
                pricing = val
                break
    if not pricing:
        return 0.0
    input_cost, output_cost = pricing
    return (prompt_tokens * input_cost + completion_tokens * output_cost) / 1_000_000


@dataclass
class UsageStats:
    """Accumulated LLM usage statistics across pipeline stages."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    api_calls: int = 0
    model: str = ""

    def accumulate(self, prompt: int, completion: int, total: int, cost: float, model: str) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total
        # Use provided cost if available, otherwise estimate from model pricing
        if cost > 0:
            self.cost_usd += cost
        else:
            self.cost_usd += estimate_cost(model, prompt, completion)
        self.api_calls += 1
        if model:
            self.model = model

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "api_calls": self.api_calls,
            "model": self.model,
        }


async def _chat(
    messages: list[dict[str, Any]],
    model: str | None = None,
    usage_stats: UsageStats | None = None,
    **kwargs: Any,
) -> str:
    """Call the LLM and return the response text."""
    client = _client()
    used_model = model or REQUESTY_MODEL
    response = await client.chat.completions.create(
        model=used_model,
        messages=messages,  # type: ignore[arg-type]
        **kwargs,
    )
    if usage_stats is not None and response.usage:
        # Requesty returns cost in x-request-cost header, but the OpenAI SDK
        # doesn't expose headers. We can check for cost in the response model
        # or compute from usage. For now, use 0 and let the frontend show tokens.
        cost = 0.0
        # Some Requesty responses include cost info in the response object
        if hasattr(response, "x_request_cost"):
            cost = float(getattr(response, "x_request_cost", 0))
        usage_stats.accumulate(
            prompt=response.usage.prompt_tokens or 0,
            completion=response.usage.completion_tokens or 0,
            total=response.usage.total_tokens or 0,
            cost=cost,
            model=response.model or used_model,
        )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Stage 1: Context Agent
# ---------------------------------------------------------------------------

CONTEXT_AGENT_SYSTEM = """\
You are the Librarian for Reli, an AI personal information manager.
Based on the user's current message and conversation history, generate search
parameters to find relevant "Things" in the database.

Be thorough: if the user asks about a project, also search for related tasks.
If they mention completing something, search for that item AND its parent project
so we can provide full context.

Respond with ONLY valid JSON matching this schema (no markdown, no explanation):
{
  "search_queries": ["query 1", "query 2"],
  "filter_params": {
    "active_only": true,
    "type_hint": null
  },
  "needs_web_search": false,
  "web_search_query": null,
  "gmail_query": null,
  "include_calendar": false
}
- search_queries: 1-3 short text fragments to match against Thing titles/data
- filter_params.active_only: true unless user asks about archived/all items
- filter_params.type_hint: null or one of task|note|idea|project|goal|journal|person|place|event|concept|reference
- needs_web_search: true if the user is asking about external/real-world info
  that would benefit from a web search (current events, facts, how-to questions,
  product info, documentation, etc.). false for personal task management requests
  (creating, updating, listing things).
- web_search_query: a concise, effective Google search query when needs_web_search
  is true; null otherwise.
- gmail_query: If the user is asking about emails/messages/inbox, set this to a Gmail
  search query string (e.g. "from:boss", "subject:report", "is:unread"). Otherwise null.
  Examples of user intents that need gmail_query:
  - "what emails did I get today" → "newer_than:1d"
  - "any emails from John" → "from:John"
  - "check my inbox for project updates" → "subject:project update"
  - "summarize my unread emails" → "is:unread"
- include_calendar: true if the user asks about their schedule, calendar, meetings,
  events, availability, free time, what's coming up today/this week, or anything
  time/schedule related. Default false.
"""


async def _chat_ollama(
    messages: list[dict[str, Any]],
    usage_stats: UsageStats | None = None,
    **kwargs: Any,
) -> str:
    """Call local Ollama and return the response text."""
    client = _ollama_client()
    response = await client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=messages,  # type: ignore[arg-type]
        **kwargs,
    )
    if usage_stats is not None and response.usage:
        usage_stats.accumulate(
            prompt=response.usage.prompt_tokens or 0,
            completion=response.usage.completion_tokens or 0,
            total=response.usage.total_tokens or 0,
            cost=0.0,  # local model, no cost
            model=OLLAMA_MODEL,
        )
    return response.choices[0].message.content or ""


async def run_context_agent(
    message: str, history: list[dict[str, Any]], usage_stats: UsageStats | None = None
) -> dict[str, Any]:
    """Stage 1: decide what to search for.

    Uses local Ollama when OLLAMA_MODEL is configured, with graceful fallback
    to Requesty if Ollama is unavailable.
    """
    messages = [{"role": "system", "content": CONTEXT_AGENT_SYSTEM}]
    for h in history[-10:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    raw = None

    # Try Ollama first if configured
    if OLLAMA_MODEL:
        try:
            raw = await _chat_ollama(
                messages, response_format={"type": "json_object"}, usage_stats=usage_stats
            )
        except Exception as exc:
            logger.warning("Ollama context agent failed, falling back to Requesty: %s", exc)

    # Fall back to Requesty
    if raw is None:
        raw = await _chat(messages, response_format={"type": "json_object"}, usage_stats=usage_stats)

    try:
        result: dict[str, Any] = json.loads(raw)
        return result
    except json.JSONDecodeError:
        return {"search_queries": [message], "filter_params": {"active_only": True, "type_hint": None}}


# ---------------------------------------------------------------------------
# Stage 2: Reasoning Agent
# ---------------------------------------------------------------------------

REASONING_AGENT_SYSTEM = """\
You are the Reasoning Agent for Reli, an AI personal information manager.
Given the user's request, conversation history, and a list of relevant Things,
decide what storage changes are needed.

You MUST only output JSON — no natural language, no markdown fences.

Output schema:
{
  "storage_changes": {
    "create": [{"title": "...", "type_hint": "...", "priority": 3, "checkin_date": null, "surface": true, "data": {}}],
    "update": [{"id": "...", "changes": {"title": "...", "checkin_date": "...", "active": true}}],
    "delete": ["id1"],
    "relationships": [{"from_thing_id": "...", "to_thing_id": "...", "relationship_type": "..."}]
  },
  "questions_for_user": [],
  "reasoning_summary": "Brief internal note explaining intent."
}

Rules:
- "create" items: title required; type_hint optional; checkin_date ISO-8601 or null
- "update" items: id required; changes = only the fields to change
- "delete" items: list of UUIDs to hard-delete
- "relationships": create typed links between Things (see below)
- If the user's intent is ambiguous, add ONE clarifying question and make NO changes.
  Focus on what would make the task actionable: "What's the specific deliverable?"
  or "Can we break this into smaller steps?"
- Use ISO-8601 for all dates (e.g. 2026-03-15T00:00:00)
- If no changes are needed, return empty lists and an empty reasoning_summary.
- When creating tasks, prefer specific actionable titles over vague ones.
  "Draft Q1 budget spreadsheet" is better than "Work on budget".
- If a task seems broad (multiple distinct steps), suggest breaking it down via
  questions_for_user rather than creating one large item.
- Include relevant context in data.notes when the user provides background info.
- When the user completes a task (marks done, says "finished X"), set active=false
  on the matching Thing. Note what was accomplished in reasoning_summary.

Entity Types:
When the user mentions people, places, events, concepts, or references, create
entity Things to build a knowledge graph:
- type_hint "person" — people the user interacts with (e.g. "Sarah Chen", "Dr. Rodriguez")
- type_hint "place" — locations (e.g. "Office HQ", "Tokyo")
- type_hint "event" — specific occurrences (e.g. "Q1 Review Meeting", "Sarah's birthday")
- type_hint "concept" — abstract ideas (e.g. "Microservices migration", "OKR framework")
- type_hint "reference" — external resources (e.g. "RFC 2616", "Design spec v2")

Entity Things default to surface=false (they exist in the graph but don't clutter
the sidebar). Use surface=true only for entities the user explicitly wants to track.

Relationships:
Create relationships to link Things together. Use from_thing_id and to_thing_id
(both must be existing Thing IDs or IDs of Things being created in this same batch).

Relationship types:
- Structural: "parent-of", "child-of", "depends-on", "blocks", "part-of"
- Associative: "related-to", "involves", "tagged-with"
- Temporal: "followed-by", "preceded-by", "spawned-from"

For example, if user says "Meeting with Sarah about the budget project":
1. Create entity "Sarah" (type_hint: person, surface: false) if not already known
2. Create relationship: Sarah → "Budget project" with type "involves"
3. Create the meeting Thing if needed

When referencing existing Things for relationships, use their IDs from the
relevant Things list. For newly created Things, use the placeholder "NEW:<index>"
where <index> is the 0-based position in the create array (e.g. "NEW:0" for the
first created item).
"""


async def run_reasoning_agent(
    message: str,
    history: list[dict[str, Any]],
    relevant_things: list[dict[str, Any]],
    web_results: list[dict[str, Any]] | None = None,
    gmail_context: list[dict[str, Any]] | None = None,
    calendar_events: list[dict[str, Any]] | None = None,
    usage_stats: UsageStats | None = None,
) -> dict[str, Any]:
    """Stage 2: decide what changes to make."""
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d (%A)")
    things_json = json.dumps(relevant_things, default=str)
    user_content = f"Today's date: {today}\n\nUser message: {message}\n\nRelevant Things from database:\n{things_json}"
    if web_results:
        user_content += f"\n\nWeb search results:\n{json.dumps(web_results, default=str)}"
    if gmail_context:
        user_content += f"\n\nRecent Gmail messages matching user's query:\n{json.dumps(gmail_context, default=str)}"
    if calendar_events:
        cal_json = json.dumps(calendar_events, default=str)
        user_content += f"\n\nUpcoming Google Calendar events:\n{cal_json}"
    messages = [{"role": "system", "content": REASONING_AGENT_SYSTEM}]
    for h in history[-10:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_content})

    raw = await _chat(messages, response_format={"type": "json_object"}, usage_stats=usage_stats)
    try:
        result: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        result = {}

    # Ensure required keys are present
    result.setdefault("storage_changes", {"create": [], "update": [], "delete": []})
    result["storage_changes"].setdefault("create", [])
    result["storage_changes"].setdefault("update", [])
    result["storage_changes"].setdefault("delete", [])
    result.setdefault("questions_for_user", [])
    result.setdefault("reasoning_summary", "")
    return result


# ---------------------------------------------------------------------------
# Stage 3: Validator — applies changes to SQLite
# ---------------------------------------------------------------------------


def apply_storage_changes(storage_changes: dict[str, Any], conn: sqlite3.Connection) -> dict[str, list[Any]]:
    """Stage 3: validate and apply changes; return what was actually applied."""
    import json as _json
    import uuid
    from datetime import datetime, timezone

    from .vector_store import delete_thing as vs_delete
    from .vector_store import upsert_thing

    applied: dict[str, list] = {"created": [], "updated": [], "deleted": [], "relationships_created": []}

    now = datetime.now(timezone.utc).isoformat()

    # Entity type_hints default to surface=false
    ENTITY_TYPES = {"person", "place", "event", "concept", "reference"}

    # ── Creates ──────────────────────────────────────────────────────────────
    for item in storage_changes.get("create", []):
        title = item.get("title", "").strip()
        if not title:
            continue
        thing_id = str(uuid.uuid4())
        checkin = item.get("checkin_date")
        raw_data = item.get("data") or {}
        data_json = raw_data if isinstance(raw_data, str) else _json.dumps(raw_data)
        type_hint = item.get("type_hint")
        surface = item.get("surface")
        if surface is None:
            surface = 0 if type_hint in ENTITY_TYPES else 1
        else:
            surface = int(bool(surface))
        conn.execute(
            """INSERT INTO things
               (id, title, type_hint, parent_id, checkin_date, priority, active, surface, data, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
            (
                thing_id,
                title,
                type_hint,
                item.get("parent_id"),
                checkin,
                item.get("priority", 3),
                surface,
                data_json,
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
        if row:
            applied["created"].append(dict(row))
            upsert_thing(dict(row))

    # ── Updates ──────────────────────────────────────────────────────────────
    for item in storage_changes.get("update", []):
        thing_id = item.get("id", "").strip()
        changes = item.get("changes", {})
        if not thing_id or not changes:
            continue
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
        if not row:
            continue  # skip unknown IDs

        fields: dict[str, Any] = {}
        for key in ("title", "type_hint", "parent_id", "checkin_date", "priority"):
            if key in changes:
                fields[key] = changes[key]
        if "active" in changes:
            fields["active"] = int(bool(changes["active"]))
        if "surface" in changes:
            fields["surface"] = int(bool(changes["surface"]))
        if "data" in changes:
            raw_data = changes["data"]
            fields["data"] = raw_data if isinstance(raw_data, str) else _json.dumps(raw_data)
        if not fields:
            continue
        fields["updated_at"] = now

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [thing_id]
        conn.execute(f"UPDATE things SET {set_clause} WHERE id = ?", values)
        updated_row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
        if updated_row:
            applied["updated"].append(dict(updated_row))
            upsert_thing(dict(updated_row))

    # ── Deletes ──────────────────────────────────────────────────────────────
    for thing_id in storage_changes.get("delete", []):
        thing_id = str(thing_id).strip()
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
        if not row:
            continue
        conn.execute("DELETE FROM things WHERE id = ?", (thing_id,))
        applied["deleted"].append(thing_id)
        vs_delete(thing_id)

    # Build lookup for NEW:<index> placeholders from created things
    created_id_map: dict[str, str] = {}
    for idx, created_thing in enumerate(applied["created"]):
        created_id_map[f"NEW:{idx}"] = created_thing["id"]

    # ── Relationships ────────────────────────────────────────────────────────
    for rel in storage_changes.get("relationships", []):
        from_id = rel.get("from_thing_id", "").strip()
        to_id = rel.get("to_thing_id", "").strip()
        rel_type = rel.get("relationship_type", "").strip()
        if not from_id or not to_id or not rel_type:
            continue
        # Resolve NEW:<index> placeholders
        from_id = created_id_map.get(from_id, from_id)
        to_id = created_id_map.get(to_id, to_id)
        if from_id == to_id:
            continue
        # Verify both things exist
        from_row = conn.execute("SELECT id FROM things WHERE id = ?", (from_id,)).fetchone()
        to_row = conn.execute("SELECT id FROM things WHERE id = ?", (to_id,)).fetchone()
        if not from_row or not to_row:
            continue
        rel_id = str(uuid.uuid4())
        meta = rel.get("metadata")
        meta_json = _json.dumps(meta) if meta else None
        conn.execute(
            "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type, metadata)"
            " VALUES (?, ?, ?, ?, ?)",
            (rel_id, from_id, to_id, rel_type, meta_json),
        )
        applied["relationships_created"].append(
            {
                "id": rel_id,
                "from_thing_id": from_id,
                "to_thing_id": to_id,
                "relationship_type": rel_type,
            }
        )

    # ── Update last_referenced on all retrieved things ────────────────────
    # This is called after reasoning runs; mark all referenced things
    # (handled by the caller for relevant_things)

    return applied


# ---------------------------------------------------------------------------
# Stage 4: Response Agent
# ---------------------------------------------------------------------------

RESPONSE_AGENT_SYSTEM = """\
You are the Voice of Reli, an AI personal information manager.
Given the reasoning summary and the actual changes applied to the database,
provide a friendly, concise response to the user.

Personality: You are a highly competent, proactive, witty, and warmly supportive
personal assistant (think Donna Paulsen). You anticipate needs, celebrate wins
genuinely, use humor to keep things light, and always keep the user motivated.
Never be generic, neutral, or overly formal.

Rules:
- If there are questions_for_user, ask them ONE at a time. Frame clarifying
  questions supportively: "Love that goal! To make it really actionable, what's
  the specific deliverable we're aiming for?" — not dry interrogation.
- Only mention changes that ACTUALLY occurred (from applied_changes).
  Do not hallucinate changes that didn't happen.
- Keep responses brief (1-3 sentences) but with personality.
- When something was CREATED, confirm with warmth and mention key details:
  "Got it! '[Thing]' is tracked with a check-in on [date]. You're all set."
  or "Done! I've locked in '[Thing]' for you. Anything else?"
- When something was UPDATED, briefly confirm what changed.
- When a task is COMPLETED (marked inactive / deleted), CELEBRATE big:
  "YES! '[Thing]' is DONE! You're on fire. What's next?"
  or "Consider '[Thing]' handled. Seriously impressive. What are we tackling now?"
- IMPORTANT: Do NOT use completion/celebration language for newly created items.
  Creating a reminder is not the same as finishing a task.
- When presenting context about existing Things, briefly summarize what you
  know (title, priority, check-in date, notes) so the user has full context
  before you ask anything.
- If the user seems stuck or has many pending items, be encouraging and help
  prioritize: "We've got a few things in play. Want me to help pick the
  power move for today?"
- Proactively nudge about items with approaching check-in dates when relevant.
- When calendar events are provided, naturally weave them into your response.
  Mention upcoming meetings, conflicts, or free blocks when relevant to the
  user's request. Format times in a human-friendly way (e.g. "2pm" not ISO-8601).
"""


async def run_response_agent(
    message: str,
    reasoning_summary: str,
    questions_for_user: list[str],
    applied_changes: dict[str, Any],
    web_results: list[dict[str, Any]] | None = None,
    usage_stats: UsageStats | None = None,
) -> str:
    """Stage 4: generate friendly user-facing response."""
    context = (
        f"Original user message: {message}\n\n"
        f"Reasoning summary: {reasoning_summary}\n\n"
        f"Applied changes: {json.dumps(applied_changes, default=str)}\n\n"
        f"Questions for user (if any): {json.dumps(questions_for_user)}"
    )
    if web_results:
        context += (
            f"\n\nWeb search results (cite relevant sources in your response):\n{json.dumps(web_results, default=str)}"
        )
    messages = [
        {"role": "system", "content": RESPONSE_AGENT_SYSTEM},
        {"role": "user", "content": context},
    ]
    return await _chat(messages, usage_stats=usage_stats)
