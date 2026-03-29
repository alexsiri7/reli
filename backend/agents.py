"""Multi-agent chat pipeline using Requesty as LLM gateway (via LiteLLM)."""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from openai import AsyncOpenAI

from .config import settings
from .llm import acomplete

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config — load from config.yaml
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    """Load a prompt from the prompts/ directory. The name should not include .md."""
    return (_PROMPTS_DIR / f"{name}.md").read_text()


def _load_config() -> dict[str, Any]:
    """Load config from config.yaml. Errors if the file is missing."""
    try:
        with open(_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise FileNotFoundError(
            f"config.yaml not found at {_CONFIG_PATH}. "
            "Copy config.yaml.example to config.yaml and set your models."
        )

    # Validate required keys
    if "llm" not in cfg or "models" not in cfg.get("llm", {}):
        raise ValueError("config.yaml must contain llm.models with context, reasoning, and response entries")

    models = cfg["llm"]["models"]
    for key in ("context", "reasoning", "response"):
        if key not in models:
            raise ValueError(f"config.yaml llm.models.{key} is required")

    return cfg


_config = _load_config()

# ---------------------------------------------------------------------------
# LLM client — Requesty OpenAI-compatible gateway
# ---------------------------------------------------------------------------

REQUESTY_BASE_URL = settings.REQUESTY_BASE_URL or _config["llm"]["base_url"]
REQUESTY_API_KEY = settings.REQUESTY_API_KEY
_models = _config["llm"]["models"]
REQUESTY_MODEL = settings.REQUESTY_MODEL or _models["context"]
REQUESTY_REASONING_MODEL = settings.REQUESTY_REASONING_MODEL or _models["reasoning"]
REQUESTY_RESPONSE_MODEL = settings.REQUESTY_RESPONSE_MODEL or _models["response"]

# ---------------------------------------------------------------------------
# Ollama — optional local LLM for context agent
# ---------------------------------------------------------------------------

OLLAMA_BASE_URL = settings.OLLAMA_BASE_URL or _config["ollama"]["base_url"]
OLLAMA_MODEL = settings.OLLAMA_MODEL or _config["ollama"].get("model", "")


def _ollama_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key="ollama", base_url=f"{OLLAMA_BASE_URL}/v1")


# Per-model pricing: (input_cost_per_million, output_cost_per_million)
_DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (2.50, 10.00),
    "anthropic/claude-sonnet-4-20250514": (3.00, 15.00),
    "google/gemini-2.0-flash-001": (0.10, 0.40),
    "google/gemini-2.5-flash-preview-05-20": (0.15, 0.60),
    "google/gemini-2.5-flash-lite": (0.10, 0.40),
    "google/gemini-2.5-flash": (0.15, 0.60),
    "google/gemini-3.1-flash-lite-preview": (0.10, 0.40),
    "google/gemini-3-flash-preview": (0.15, 0.60),
}


def _fetch_requesty_pricing() -> dict[str, tuple[float, float]]:
    """Fetch model pricing from Requesty API, merging with defaults.

    Config.yaml ``pricing:`` section overrides API prices.
    Falls back to hardcoded defaults if the API is unreachable.
    """
    pricing = dict(_DEFAULT_PRICING)

    # Try fetching from Requesty API
    try:
        import httpx

        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{REQUESTY_BASE_URL}/models")
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                for model_info in data:
                    model_id = model_info.get("id", "")
                    input_price = model_info.get("input_price")
                    output_price = model_info.get("output_price")
                    if model_id and input_price is not None and output_price is not None:
                        # API returns per-token; multiply by 1M for per-million
                        pricing[model_id] = (
                            float(input_price) * 1_000_000,
                            float(output_price) * 1_000_000,
                        )
    except Exception as exc:
        logger.warning("Failed to fetch Requesty pricing, using defaults: %s", exc)

    # Config.yaml pricing overrides take highest priority
    config_pricing = _config.get("pricing", {})
    for model_id, prices in config_pricing.items():
        if isinstance(prices, dict):
            inp = prices.get("input", prices.get("input_per_million"))
            out = prices.get("output", prices.get("output_per_million"))
            if inp is not None and out is not None:
                pricing[model_id] = (float(inp), float(out))
        elif isinstance(prices, (list, tuple)) and len(prices) == 2:
            pricing[model_id] = (float(prices[0]), float(prices[1]))

    return pricing


MODEL_PRICING: dict[str, tuple[float, float]] = _fetch_requesty_pricing()


def _strip_provider(model: str) -> str:
    """Strip provider prefix (e.g. 'google/gemini-2.5-flash' -> 'gemini-2.5-flash')."""
    return model.split("/", 1)[-1]


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost from token counts using per-model pricing."""
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        # Try matching with/without provider prefix (e.g. "gemini-2.5-flash-lite"
        # should match "google/gemini-2.5-flash-lite" and vice versa)
        model_bare = _strip_provider(model)
        for key, val in MODEL_PRICING.items():
            key_bare = _strip_provider(key)
            if model_bare == key_bare or model == key_bare or model_bare == key:
                pricing = val
                break
    if not pricing:
        return 0.0
    input_cost, output_cost = pricing
    return (prompt_tokens * input_cost + completion_tokens * output_cost) / 1_000_000


@dataclass
class UsageRecord:
    """A single LLM API call's usage."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


@dataclass
class UsageStats:
    """Accumulated LLM usage statistics across pipeline stages."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    api_calls: int = 0
    model: str = ""
    calls: list[UsageRecord] = field(default_factory=list)

    def accumulate(self, prompt: int, completion: int, total: int, cost: float, model: str) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total
        # Use provided cost if available, otherwise estimate from model pricing
        actual_cost = cost if cost > 0 else estimate_cost(model, prompt, completion)
        self.cost_usd += actual_cost
        self.api_calls += 1
        if model:
            self.model = model
        self.calls.append(
            UsageRecord(
                model=model or "unknown",
                prompt_tokens=prompt,
                completion_tokens=completion,
                cost_usd=actual_cost,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "api_calls": self.api_calls,
            "model": self.model,
            "per_call_usage": [
                {
                    "model": c.model,
                    "prompt_tokens": c.prompt_tokens,
                    "completion_tokens": c.completion_tokens,
                    "cost_usd": round(c.cost_usd, 6),
                }
                for c in self.calls
            ],
        }


async def _chat(
    messages: list[dict[str, Any]],
    model: str | None = None,
    usage_stats: UsageStats | None = None,
    api_key: str | None = None,
    **kwargs: Any,
) -> str:
    """Call the LLM via LiteLLM and return the response text."""
    used_model = model or REQUESTY_MODEL
    response = await acomplete(messages, used_model, api_key=api_key, **kwargs)
    if usage_stats is not None and response.usage:
        cost = 0.0
        if hasattr(response, "x_request_cost"):
            cost = float(getattr(response, "x_request_cost", 0))
        usage_stats.accumulate(
            prompt=response.usage.prompt_tokens or 0,
            completion=response.usage.completion_tokens or 0,
            total=response.usage.total_tokens or 0,
            cost=cost,
            model=getattr(response, "model", None) or used_model,
        )
    return response.choices[0].message.content or ""


def _with_current_date(prompt: str) -> str:
    """Prepend the current date to a system prompt so the LLM knows 'today'."""
    today = date.today().strftime("%A, %B %-d, %Y")  # e.g. "Saturday, March 22, 2026"
    return f"Current date: {today}\n\n{prompt}"


# ---------------------------------------------------------------------------
# Stage 1: Context Agent
# ---------------------------------------------------------------------------

CONTEXT_AGENT_SYSTEM = _load_prompt("context")


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


# ---------------------------------------------------------------------------
# Stage 1b: Context Agent Refinement (iterative loop)
# ---------------------------------------------------------------------------

CONTEXT_REFINEMENT_SYSTEM = _load_prompt("context-refinement")


# ---------------------------------------------------------------------------
# Stage 2: Reasoning Agent (uses thinking model via REQUESTY_REASONING_MODEL)
# ---------------------------------------------------------------------------

REASONING_AGENT_SYSTEM = _load_prompt("reasoning")


# ---------------------------------------------------------------------------
# Stage 3: Validator — applies changes to SQLite
# ---------------------------------------------------------------------------


def apply_storage_changes(
    storage_changes: dict[str, Any], conn: sqlite3.Connection, user_id: str = ""
) -> dict[str, list[Any]]:
    """Stage 3: validate and apply changes; return what was actually applied."""
    import json as _json
    import uuid
    from datetime import datetime, timezone

    from .vector_store import delete_thing as vs_delete
    from .vector_store import upsert_thing

    applied: dict[str, list] = {"created": [], "updated": [], "deleted": [], "merged": [], "relationships_created": [], "scheduled_tasks_created": []}

    now = datetime.now(timezone.utc).isoformat()

    # Entity type_hints default to surface=false
    ENTITY_TYPES = {"person", "place", "event", "concept", "reference", "preference"}

    # Map from create-array index to resolved Thing ID (for NEW:<index> placeholders)
    create_index_to_id: dict[int, str] = {}

    # Pre-index relationships by NEW:<index> target for possessive dedup.
    # This lets us check if a create has a companion relationship from the user
    # and whether the user already has that relationship type to an existing entity.
    _rels_by_new_target: dict[int, list[dict[str, Any]]] = {}
    for rel in storage_changes.get("relationships", []):
        to_id = rel.get("to_thing_id", "")
        if to_id.startswith("NEW:"):
            try:
                idx = int(to_id.split(":")[1])
                _rels_by_new_target.setdefault(idx, []).append(rel)
            except (ValueError, IndexError):
                pass

    # ── Creates ──────────────────────────────────────────────────────────────
    for create_idx, item in enumerate(storage_changes.get("create", [])):
        title = item.get("title", "").strip()
        if not title:
            continue
        # Deduplicate: if an active Thing with the same title already exists (case-insensitive),
        # convert the create into an update on the existing Thing instead of silently skipping.
        existing = conn.execute(
            "SELECT * FROM things WHERE LOWER(title) = LOWER(?) AND active = 1 LIMIT 1", (title,)
        ).fetchone()

        # Possessive dedup: if no exact title match, check whether the user already
        # has a relationship of the same type (e.g. "sister") to an existing entity.
        # This catches cases like: user has Thing "Sister", now LLM creates "Sarah"
        # with relationship_type="sister" — we should reuse the existing entity.
        if not existing:
            type_hint = item.get("type_hint")
            if type_hint in ENTITY_TYPES:
                companion_rels = _rels_by_new_target.get(create_idx, [])
                for crel in companion_rels:
                    rel_type = crel.get("relationship_type", "").strip()
                    from_id = crel.get("from_thing_id", "").strip()
                    if not rel_type or not from_id:
                        continue
                    # Resolve NEW:<index> placeholders for compound possessives
                    # (e.g. "my sister's husband" — sister is NEW:0, already resolved)
                    if from_id.startswith("NEW:"):
                        try:
                            from_idx = int(from_id.split(":")[1])
                            resolved = create_index_to_id.get(from_idx)
                            if resolved:
                                from_id = resolved
                            else:
                                continue  # not yet resolved, skip
                        except (ValueError, IndexError):
                            continue
                    # Check if from_id already has a relationship of this type
                    match = conn.execute(
                        "SELECT t.* FROM things t"
                        " JOIN thing_relationships r ON r.to_thing_id = t.id"
                        " WHERE r.from_thing_id = ? AND r.relationship_type = ?"
                        " AND t.active = 1 LIMIT 1",
                        (from_id, rel_type),
                    ).fetchone()
                    if match:
                        logger.info(
                            "Possessive dedup: reusing existing '%s' (id=%s) for relationship '%s'"
                            " instead of creating '%s'",
                            match["title"],
                            match["id"],
                            rel_type,
                            title,
                        )
                        existing = match
                        # Update the title if the new one is more specific (a name vs a role)
                        if title.lower() != match["title"].lower():
                            conn.execute(
                                "UPDATE things SET title = ?, updated_at = ? WHERE id = ?",
                                (title, now, match["id"]),
                            )
                        break

        if existing:
            logger.info("Dedup: converting create for '%s' into update on %s", title, existing["id"])
            # Merge any new data from the create intent into the existing Thing
            merge_fields: dict[str, Any] = {}
            raw_data = item.get("data")
            if raw_data:
                existing_data = existing["data"]
                if existing_data:
                    try:
                        old = _json.loads(existing_data) if isinstance(existing_data, str) else existing_data
                    except (ValueError, TypeError):
                        old = {}
                else:
                    old = {}
                new_data = raw_data if isinstance(raw_data, dict) else {}
                if new_data:
                    merged = {**old, **new_data}
                    merge_fields["data"] = _json.dumps(merged)
            if item.get("open_questions"):
                merge_fields["open_questions"] = _json.dumps(item["open_questions"])
            if item.get("checkin_date") and not existing["checkin_date"]:
                merge_fields["checkin_date"] = item["checkin_date"]
            if merge_fields:
                merge_fields["updated_at"] = now
                set_clause = ", ".join(f"{k} = ?" for k in merge_fields)
                values = list(merge_fields.values()) + [existing["id"]]
                conn.execute(f"UPDATE things SET {set_clause} WHERE id = ?", values)
            updated_row = conn.execute("SELECT * FROM things WHERE id = ?", (existing["id"],)).fetchone()
            if updated_row:
                applied["updated"].append(dict(updated_row))
                upsert_thing(dict(updated_row))
            create_index_to_id[create_idx] = existing["id"]
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
        open_questions = item.get("open_questions")
        oq_json = _json.dumps(open_questions) if open_questions else None
        conn.execute(
            """INSERT INTO things
               (id, title, type_hint, parent_id, checkin_date, priority, active, surface, data,
                open_questions, created_at, updated_at, user_id)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)""",
            (
                thing_id,
                title,
                type_hint,
                item.get("parent_id"),
                checkin,
                item.get("priority", 3),
                surface,
                data_json,
                oq_json,
                now,
                now,
                user_id or None,
            ),
        )
        row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
        if row:
            applied["created"].append(dict(row))
            upsert_thing(dict(row))
            create_index_to_id[create_idx] = thing_id

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
        if "open_questions" in changes:
            oq = changes["open_questions"]
            fields["open_questions"] = _json.dumps(oq) if oq else None
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

    # ── Merges ────────────────────────────────────────────────────────────
    for merge_item in storage_changes.get("merge", []):
        keep_id = str(merge_item.get("keep_id", "")).strip()
        remove_id = str(merge_item.get("remove_id", "")).strip()
        merged_data = merge_item.get("merged_data") or {}
        if not keep_id or not remove_id or keep_id == remove_id:
            continue

        keep_row = conn.execute("SELECT * FROM things WHERE id = ?", (keep_id,)).fetchone()
        remove_row = conn.execute("SELECT * FROM things WHERE id = ?", (remove_id,)).fetchone()
        if not keep_row or not remove_row:
            logger.warning(
                "Skipping merge: keep_id=%s exists=%s, remove_id=%s exists=%s",
                keep_id,
                bool(keep_row),
                remove_id,
                bool(remove_row),
            )
            continue

        # 1. Merge data into the primary Thing
        mf: dict[str, Any] = {}
        existing_data = keep_row["data"]
        try:
            old_data = _json.loads(existing_data) if isinstance(existing_data, str) and existing_data else {}
        except (ValueError, TypeError):
            old_data = {}
        new_data = merged_data if isinstance(merged_data, dict) else {}
        if new_data or old_data:
            combined = {**old_data, **new_data}
            mf["data"] = _json.dumps(combined)

        # 2. Transfer open_questions from removed Thing (skip duplicates)
        keep_oq_raw = keep_row["open_questions"]
        remove_oq_raw = remove_row["open_questions"]
        try:
            keep_oq = _json.loads(keep_oq_raw) if isinstance(keep_oq_raw, str) and keep_oq_raw else []
        except (ValueError, TypeError):
            keep_oq = []
        try:
            remove_oq = _json.loads(remove_oq_raw) if isinstance(remove_oq_raw, str) and remove_oq_raw else []
        except (ValueError, TypeError):
            remove_oq = []
        if remove_oq:
            existing_set = set(keep_oq)
            for q in remove_oq:
                if q not in existing_set:
                    keep_oq.append(q)
                    existing_set.add(q)
            mf["open_questions"] = _json.dumps(keep_oq)

        # Update the primary Thing
        if mf:
            mf["updated_at"] = now
            set_clause = ", ".join(f"{k} = ?" for k in mf)
            values = list(mf.values()) + [keep_id]
            conn.execute(f"UPDATE things SET {set_clause} WHERE id = ?", values)

        # 3. Re-point all relationships from remove_id → keep_id
        conn.execute(
            "UPDATE thing_relationships SET from_thing_id = ? WHERE from_thing_id = ?",
            (keep_id, remove_id),
        )
        conn.execute(
            "UPDATE thing_relationships SET to_thing_id = ? WHERE to_thing_id = ?",
            (keep_id, remove_id),
        )
        # Clean up any self-referential relationships created by the re-pointing
        conn.execute(
            "DELETE FROM thing_relationships WHERE from_thing_id = ? AND to_thing_id = ?",
            (keep_id, keep_id),
        )

        # 4. Delete the duplicate Thing
        conn.execute("DELETE FROM things WHERE id = ?", (remove_id,))
        vs_delete(remove_id)

        # 5. Record merge history
        existing_data_raw = keep_row["data"]
        try:
            _keep_data = (
                _json.loads(existing_data_raw) if isinstance(existing_data_raw, str) and existing_data_raw else {}
            )
        except (ValueError, TypeError):
            _keep_data = {}
        _remove_data_raw = remove_row["data"]
        try:
            _rem_data = _json.loads(_remove_data_raw) if isinstance(_remove_data_raw, str) and _remove_data_raw else {}
        except (ValueError, TypeError):
            _rem_data = {}
        _merged_snapshot = {**_rem_data, **new_data} if (new_data or _rem_data) else None
        conn.execute(
            "INSERT INTO merge_history (id, keep_id, remove_id, keep_title, remove_title,"
            " merged_data, triggered_by, user_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                keep_id,
                remove_id,
                keep_row["title"],
                remove_row["title"],
                _json.dumps(_merged_snapshot) if _merged_snapshot else None,
                "agent",
                user_id or None,
                now,
            ),
        )

        # 6. Re-embed the updated primary Thing
        updated_keep = conn.execute("SELECT * FROM things WHERE id = ?", (keep_id,)).fetchone()
        if updated_keep:
            upsert_thing(dict(updated_keep))
            applied["merged"].append(
                {
                    "keep_id": keep_id,
                    "remove_id": remove_id,
                    "keep_title": updated_keep["title"],
                    "remove_title": remove_row["title"],
                }
            )

    # Build lookup for NEW:<index> placeholders — covers both genuinely created
    # Things and deduped creates that were converted to updates.
    created_id_map: dict[str, str] = {}
    for idx, resolved_id in create_index_to_id.items():
        created_id_map[f"NEW:{idx}"] = resolved_id

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
        # Skip duplicate relationships (same from, to, and type already exists)
        dup = conn.execute(
            "SELECT id FROM thing_relationships"
            " WHERE from_thing_id = ? AND to_thing_id = ? AND relationship_type = ? LIMIT 1",
            (from_id, to_id, rel_type),
        ).fetchone()
        if dup:
            logger.info(
                "Skipping duplicate relationship: %s -> %s (%s)",
                from_id,
                to_id,
                rel_type,
            )
            continue
        # Verify both things exist
        from_row = conn.execute("SELECT id FROM things WHERE id = ?", (from_id,)).fetchone()
        to_row = conn.execute("SELECT id FROM things WHERE id = ?", (to_id,)).fetchone()
        if not from_row or not to_row:
            missing = []
            if not from_row:
                missing.append(f"from_thing_id={from_id}")
            if not to_row:
                missing.append(f"to_thing_id={to_id}")
            logger.warning(
                "Skipping relationship '%s': referenced thing(s) not found (%s)",
                rel_type,
                ", ".join(missing),
            )
            continue
        rel_id = str(uuid.uuid4())
        meta = rel.get("metadata")
        meta_json = _json.dumps(meta) if meta else None
        conn.execute(
            "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type, metadata)"
            " VALUES (?, ?, ?, ?, ?)",
            (rel_id, from_id, to_id, rel_type, meta_json),
        )
        # Verify the row was actually created
        verify = conn.execute("SELECT id FROM thing_relationships WHERE id = ?", (rel_id,)).fetchone()
        if not verify:
            logger.error(
                "Relationship INSERT succeeded but row not found: id=%s, %s -> %s (%s)",
                rel_id,
                from_id,
                to_id,
                rel_type,
            )
            continue
        applied["relationships_created"].append(
            {
                "id": rel_id,
                "from_thing_id": from_id,
                "to_thing_id": to_id,
                "relationship_type": rel_type,
            }
        )

    # ── Scheduled Tasks ───────────────────────────────────────────────────
    from .tools import create_scheduled_task

    for task_spec in storage_changes.get("scheduled_tasks", []):
        task_type = str(task_spec.get("task_type", "")).strip()
        scheduled_at = str(task_spec.get("scheduled_at", "")).strip()
        if not task_type or not scheduled_at:
            continue
        payload = task_spec.get("payload") or {}
        thing_id = task_spec.get("thing_id") or None
        try:
            created = create_scheduled_task(
                task_type=task_type,
                scheduled_at=scheduled_at,
                payload=payload,
                thing_id=thing_id,
                user_id=user_id,
            )
            applied["scheduled_tasks_created"].append(created)
        except Exception:
            logger.exception("Failed to create scheduled task: %s at %s", task_type, scheduled_at)

    # ── Update last_referenced on all retrieved things ────────────────────
    # This is called after reasoning runs; mark all referenced things
    # (handled by the caller for relevant_things)

    return applied


# ---------------------------------------------------------------------------
# Stage 4: Response Agent
# ---------------------------------------------------------------------------

RESPONSE_AGENT_SYSTEM = _load_prompt("response")


_RESPONSE_COACH_OVERLAY = """
Interaction Style — COACHING:
Frame your responses to guide the user toward their own insights. When
presenting questions from the reasoning agent, make them feel like a natural
conversation that empowers the user to reflect. Use language like "What do you
think about...", "How does that feel?", "What would make this even better?"
Celebrate the user's own thinking. When they answer a question well, acknowledge
their insight: "Great thinking!" Be a supportive thought partner, not a
directive assistant.
"""

_RESPONSE_CONSULTANT_OVERLAY = """
Interaction Style — CONSULTING:
Frame your responses as expert recommendations. Be crisp, decisive, and
action-oriented. When changes were made, present them as confident
recommendations: "Here's what I've set up for you..." When there are questions,
frame them as the minimum info you need to proceed: "Just need one thing from
you to lock this in." Minimize back-and-forth. Show competence through
efficiency.
"""

_RESPONSE_AUTO_OVERLAY = """
Interaction Style — DYNAMIC:
Match the user's energy. If the reasoning_summary suggests coaching questions
were asked, frame your response supportively and reflectively. If direct changes
were made with few questions, be crisp and action-oriented. Read the room from
the user's message tone — short and direct gets consultant energy, exploratory
and reflective gets coaching warmth.
"""


def load_personality_preferences(user_id: str) -> list[dict[str, Any]]:
    """Load personality preference patterns from Things with type_hint='preference'.

    Returns a list of pattern dicts with keys: pattern, confidence, observations.
    Filters to active Things owned by the given user.
    """
    if not user_id:
        return []

    from .auth import user_filter
    from .database import db

    patterns: list[dict[str, Any]] = []
    with db() as conn:
        filter_sql, filter_params = user_filter(user_id)
        query = "SELECT data FROM things WHERE type_hint = 'preference' AND active = 1"
        if filter_sql:
            query += f" {filter_sql}"
        rows = conn.execute(query, filter_params).fetchall()

    for row in rows:
        raw = row["data"] if isinstance(row, sqlite3.Row) else row[0]
        if not raw:
            continue
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and "patterns" in data:
            for p in data["patterns"]:
                if isinstance(p, dict) and "pattern" in p:
                    patterns.append(
                        {
                            "pattern": p["pattern"],
                            "confidence": p.get("confidence", "emerging"),
                            "observations": p.get("observations", 1),
                        }
                    )
    return patterns


def _build_personality_overlay(patterns: list[dict[str, Any]]) -> str:
    """Format personality patterns as a prompt overlay section."""
    if not patterns:
        return ""

    lines = ["\n\nLearned Personality Preferences (override static defaults):"]
    for p in patterns:
        confidence = p.get("confidence", "emerging")
        lines.append(f"- [{confidence}] {p['pattern']}")
    return "\n".join(lines)


def get_response_system_prompt(
    interaction_style: str = "auto",
    personality_patterns: list[dict[str, Any]] | None = None,
) -> str:
    """Return the response agent system prompt with the appropriate style overlay."""
    if interaction_style == "coach":
        prompt = RESPONSE_AGENT_SYSTEM + _RESPONSE_COACH_OVERLAY
    elif interaction_style == "consultant":
        prompt = RESPONSE_AGENT_SYSTEM + _RESPONSE_CONSULTANT_OVERLAY
    else:
        prompt = RESPONSE_AGENT_SYSTEM + _RESPONSE_AUTO_OVERLAY

    if personality_patterns:
        prompt += _build_personality_overlay(personality_patterns)

    return _with_current_date(prompt)


def _build_response_messages(
    message: str,
    reasoning_summary: str,
    questions_for_user: list[str],
    applied_changes: dict[str, Any],
    web_results: list[dict[str, Any]] | None = None,
    open_questions_by_thing: dict[str, list[str]] | None = None,
    priority_question: str = "",
    briefing_mode: bool = False,
    interaction_style: str = "auto",
) -> list[dict[str, Any]]:
    """Build the message list for the response agent (shared by streaming and non-streaming)."""
    context = (
        f"<user_message>\n{message}\n</user_message>\n\n"
        f"<reasoning_summary>\n{reasoning_summary}\n</reasoning_summary>\n\n"
        f"Applied changes: {json.dumps(applied_changes, default=str)}\n\n"
        f"Questions for user (if any): {json.dumps(questions_for_user)}\n\n"
        f"Priority question (ask THIS one): {json.dumps(priority_question)}\n\n"
        f"Briefing mode: {json.dumps(briefing_mode)}"
    )
    if open_questions_by_thing:
        context += (
            f"\n\nOpen questions on Things (knowledge gaps to ask about conversationally):\n"
            f"{json.dumps(open_questions_by_thing, default=str)}"
        )
    if web_results:
        context += (
            f"\n\nWeb search results (cite relevant sources in your response):\n{json.dumps(web_results, default=str)}"
        )
    system_prompt = get_response_system_prompt(interaction_style)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": context},
    ]
