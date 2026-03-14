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

Respond with ONLY valid JSON matching this schema (no markdown, no explanation):
{
  "search_queries": ["query 1", "query 2"],
  "filter_params": {
    "active_only": true,
    "type_hint": null
  }
}
- search_queries: 1-3 short text fragments to match against Thing titles/data
- filter_params.active_only: true unless user asks about archived/all items
- filter_params.type_hint: null or one of task|note|idea|project|goal|journal
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
- If the user's intent is ambiguous, add a clarifying question and make NO changes
- Use ISO-8601 for all dates (e.g. 2026-03-15T00:00:00)
- If no changes are needed, return empty lists and an empty reasoning_summary
"""


async def run_reasoning_agent(
    message: str, history: list[dict], relevant_things: list[dict]
) -> dict:
    """Stage 2: decide what changes to make."""
    things_json = json.dumps(relevant_things, default=str)
    user_content = (
        f"User message: {message}\n\n"
        f"Relevant Things from database:\n{things_json}"
    )
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

    # ── Deletes ──────────────────────────────────────────────────────────────
    for thing_id in storage_changes.get("delete", []):
        thing_id = str(thing_id).strip()
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
        if not row:
            continue
        conn.execute("DELETE FROM things WHERE id = ?", (thing_id,))
        applied["deleted"].append(thing_id)

    return applied


# ---------------------------------------------------------------------------
# Stage 4: Response Agent
# ---------------------------------------------------------------------------

RESPONSE_AGENT_SYSTEM = """\
You are the Voice of Reli, an AI personal information manager.
Given the reasoning summary and the actual changes applied to the database,
provide a friendly, concise confirmation to the user.

Rules:
- If there are questions_for_user, prioritize asking them (one at a time).
- Only mention changes that ACTUALLY occurred (from applied_changes).
- Do not hallucinate changes that didn't happen.
- Keep the response brief (1-3 sentences).
- Tone: helpful, calm, senior assistant.
"""


async def run_response_agent(
    message: str,
    reasoning_summary: str,
    questions_for_user: list[str],
    applied_changes: dict,
) -> str:
    """Stage 4: generate friendly user-facing response."""
    context = (
        f"Original user message: {message}\n\n"
        f"Reasoning summary: {reasoning_summary}\n\n"
        f"Applied changes: {json.dumps(applied_changes, default=str)}\n\n"
        f"Questions for user (if any): {json.dumps(questions_for_user)}"
    )
    messages = [
        {"role": "system", "content": RESPONSE_AGENT_SYSTEM},
        {"role": "user", "content": context},
    ]
    return await _chat(messages)
