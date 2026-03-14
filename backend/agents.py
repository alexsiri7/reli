"""Multi-agent chat pipeline using Requesty as LLM gateway."""

import json
import os
from typing import Any

from openai import AsyncOpenAI

# ---------------------------------------------------------------------------
# LLM client — Requesty OpenAI-compatible gateway
# ---------------------------------------------------------------------------

REQUESTY_BASE_URL = os.environ.get("REQUESTY_BASE_URL", "https://router.requesty.ai/v1")
REQUESTY_API_KEY = os.environ.get("REQUESTY_API_KEY", "")
REQUESTY_MODEL = os.environ.get("REQUESTY_MODEL", "google/gemini-2.0-flash-001")


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=REQUESTY_API_KEY, base_url=REQUESTY_BASE_URL)


async def _chat(messages: list[dict], model: str | None = None, **kwargs) -> str:
    """Call the LLM and return the response text."""
    client = _client()
    response = await client.chat.completions.create(
        model=model or REQUESTY_MODEL,
        messages=messages,
        **kwargs,
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
- filter_params.type_hint: null or one of task|note|idea|project|goal|journal
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


async def run_context_agent(message: str, history: list[dict]) -> dict:
    """Stage 1: decide what to search for."""
    messages = [{"role": "system", "content": CONTEXT_AGENT_SYSTEM}]
    for h in history[-10:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    raw = await _chat(messages, response_format={"type": "json_object"})
    try:
        return json.loads(raw)
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
    "create": [{"title": "...", "type_hint": "...", "priority": 3, "checkin_date": null, "data": {}}],
    "update": [{"id": "...", "changes": {"title": "...", "checkin_date": "...", "active": true}}],
    "delete": ["id1"]
  },
  "questions_for_user": [],
  "reasoning_summary": "Brief internal note explaining intent."
}

Rules:
- "create" items: title required; type_hint optional; checkin_date ISO-8601 or null
- "update" items: id required; changes = only the fields to change
- "delete" items: list of UUIDs to hard-delete
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
"""


async def run_reasoning_agent(
    message: str,
    history: list[dict],
    relevant_things: list[dict],
    web_results: list[dict] | None = None,
    gmail_context: list[dict] | None = None,
    calendar_events: list[dict] | None = None,
) -> dict:
    """Stage 2: decide what changes to make."""
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d (%A)")
    things_json = json.dumps(relevant_things, default=str)
    user_content = (
        f"Today's date: {today}\n\n"
        f"User message: {message}\n\n"
        f"Relevant Things from database:\n{things_json}"
    )
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

    raw = await _chat(messages, response_format={"type": "json_object"})
    try:
        result = json.loads(raw)
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

def apply_storage_changes(
    storage_changes: dict, conn
) -> dict[str, list[dict]]:
    """Stage 3: validate and apply changes; return what was actually applied."""
    import json as _json
    import uuid
    from datetime import datetime, timezone

    from .vector_store import delete_thing as vs_delete, upsert_thing

    applied: dict[str, list] = {"created": [], "updated": [], "deleted": []}

    now = datetime.now(timezone.utc).isoformat()

    # ── Creates ──────────────────────────────────────────────────────────────
    for item in storage_changes.get("create", []):
        title = item.get("title", "").strip()
        if not title:
            continue
        thing_id = str(uuid.uuid4())
        checkin = item.get("checkin_date")
        data_json = _json.dumps(item.get("data") or {})
        conn.execute(
            """INSERT INTO things
               (id, title, type_hint, parent_id, checkin_date, priority, active, data, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (
                thing_id,
                title,
                item.get("type_hint"),
                item.get("parent_id"),
                checkin,
                item.get("priority", 3),
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
        if "data" in changes:
            fields["data"] = _json.dumps(changes["data"])
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
    applied_changes: dict,
    web_results: list[dict] | None = None,
) -> str:
    """Stage 4: generate friendly user-facing response."""
    context = (
        f"Original user message: {message}\n\n"
        f"Reasoning summary: {reasoning_summary}\n\n"
        f"Applied changes: {json.dumps(applied_changes, default=str)}\n\n"
        f"Questions for user (if any): {json.dumps(questions_for_user)}"
    )
    if web_results:
        context += f"\n\nWeb search results (cite relevant sources in your response):\n{json.dumps(web_results, default=str)}"
    messages = [
        {"role": "system", "content": RESPONSE_AGENT_SYSTEM},
        {"role": "user", "content": context},
    ]
    return await _chat(messages)
