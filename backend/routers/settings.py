"""Settings endpoints: model configuration via Requesty, per-user settings."""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import require_user
from ..database import db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config.yaml"


# ── Request/Response models ──────────────────────────────────────────────────


class ModelSettings(BaseModel):
    context: str
    reasoning: str
    response: str
    chat_context_window: int = 3


class ModelSettingsUpdate(BaseModel):
    context: str | None = None
    reasoning: str | None = None
    response: str | None = None
    chat_context_window: int | None = None


class RequestyModel(BaseModel):
    id: str
    name: str | None = None


class UserSettings(BaseModel):
    display_name: str = ""
    api_key: str = ""  # masked on read
    context_model: str = ""
    reasoning_model: str = ""
    response_model: str = ""


class UserSettingsUpdate(BaseModel):
    display_name: str | None = None
    api_key: str | None = None
    context_model: str | None = None
    reasoning_model: str | None = None
    response_model: str | None = None


class SetupStatus(BaseModel):
    needs_setup: bool
    has_api_key: bool
    has_display_name: bool


# ── Cost estimates for popular models ─────────────────────────────────────────

MODEL_COST_ESTIMATES: list[dict[str, Any]] = [
    {"id": "google/gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash Lite", "cost_per_conversation": 0.01, "tier": "budget"},
    {"id": "google/gemini-2.0-flash-001", "name": "Gemini 2.0 Flash", "cost_per_conversation": 0.01, "tier": "budget"},
    {"id": "google/gemini-3-flash-preview", "name": "Gemini 3 Flash", "cost_per_conversation": 0.03, "tier": "standard"},
    {"id": "google/gemini-2.5-flash-preview-05-20", "name": "Gemini 2.5 Flash", "cost_per_conversation": 0.02, "tier": "standard"},
    {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "cost_per_conversation": 0.01, "tier": "budget"},
    {"id": "openai/gpt-4o", "name": "GPT-4o", "cost_per_conversation": 0.05, "tier": "premium"},
    {"id": "anthropic/claude-sonnet-4-20250514", "name": "Claude Sonnet 4", "cost_per_conversation": 0.08, "tier": "premium"},
]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _read_config() -> dict[str, Any]:
    try:
        with open(_CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _write_config(cfg: dict[str, Any]) -> None:
    with open(_CONFIG_PATH, "w") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)


def _reload_agent_vars(models: dict[str, str]) -> None:
    """Update the in-memory module-level model variables in agents.py."""
    import backend.agents as agents_mod

    if "context" in models:
        agents_mod.REQUESTY_MODEL = models["context"]
    if "reasoning" in models:
        agents_mod.REQUESTY_REASONING_MODEL = models["reasoning"]
    if "response" in models:
        agents_mod.REQUESTY_RESPONSE_MODEL = models["response"]


def get_chat_context_window() -> int:
    """Return the configured chat context window size."""
    cfg = _read_config()
    val: int = cfg.get("chat", {}).get("context_window", 3)
    return val


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/models", response_model=list[RequestyModel], summary="List available LLM models")
def list_models(_user_id: str = Depends(require_user)) -> list[RequestyModel]:
    """Proxy the Requesty /v1/models endpoint and return available model IDs."""
    cfg = _read_config()
    base_url = cfg.get("llm", {}).get("base_url", "https://router.requesty.ai/v1")

    try:
        resp = httpx.get(f"{base_url}/models", timeout=10.0)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return [RequestyModel(id=m["id"], name=m.get("name")) for m in data if m.get("id")]
    except Exception as exc:
        logger.warning("Failed to fetch models from Requesty: %s", exc)
        raise HTTPException(status_code=502, detail="Could not fetch models from Requesty API") from exc


@router.get("", response_model=ModelSettings, summary="Get current model settings")
def get_settings(_user_id: str = Depends(require_user)) -> ModelSettings:
    """Return current model configuration for the context, reasoning, and response agents."""
    cfg = _read_config()
    models = cfg.get("llm", {}).get("models", {})
    return ModelSettings(
        context=models.get("context", "google/gemini-2.5-flash-lite"),
        reasoning=models.get("reasoning", "google/gemini-3-flash-preview"),
        response=models.get("response", "google/gemini-2.5-flash-lite"),
        chat_context_window=cfg.get("chat", {}).get("context_window", 3),
    )


@router.put("", response_model=ModelSettings, summary="Update model settings")
def update_settings(
    body: ModelSettingsUpdate,
    _user_id: str = Depends(require_user),
) -> ModelSettings:
    """Update model configuration in config.yaml and reload in-memory vars. Only provided fields are changed."""
    cfg = _read_config()

    if "llm" not in cfg:
        cfg["llm"] = {}
    if "models" not in cfg["llm"]:
        cfg["llm"]["models"] = {}

    updates: dict[str, str] = {}
    if body.context is not None:
        cfg["llm"]["models"]["context"] = body.context
        updates["context"] = body.context
    if body.reasoning is not None:
        cfg["llm"]["models"]["reasoning"] = body.reasoning
        updates["reasoning"] = body.reasoning
    if body.response is not None:
        cfg["llm"]["models"]["response"] = body.response
        updates["response"] = body.response

    if body.chat_context_window is not None:
        if "chat" not in cfg:
            cfg["chat"] = {}
        cfg["chat"]["context_window"] = max(1, min(body.chat_context_window, 50))

    _write_config(cfg)
    _reload_agent_vars(updates)

    models = cfg["llm"]["models"]
    return ModelSettings(
        context=models.get("context", "google/gemini-2.5-flash-lite"),
        reasoning=models.get("reasoning", "google/gemini-3-flash-preview"),
        response=models.get("response", "google/gemini-2.5-flash-lite"),
        chat_context_window=cfg.get("chat", {}).get("context_window", 3),
    )


# ── Per-user settings helpers ────────────────────────────────────────────────


def _get_user_setting(user_id: str, key: str) -> str | None:
    """Get a single user setting value."""
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = ?",
            (user_id, key),
        ).fetchone()
    return row["value"] if row else None


def _set_user_setting(user_id: str, key: str, value: str) -> None:
    """Set a single user setting (upsert)."""
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """INSERT INTO user_settings (user_id, key, value, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, key) DO UPDATE SET value = ?, updated_at = ?""",
            (user_id, key, value, now, value, now),
        )


def _get_all_user_settings(user_id: str) -> dict[str, str]:
    """Get all settings for a user as a dict."""
    with db() as conn:
        rows = conn.execute(
            "SELECT key, value FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return {row["key"]: row["value"] for row in rows}


def _mask_api_key(key: str) -> str:
    """Mask an API key for display, showing only first 4 and last 4 chars."""
    if not key or len(key) <= 12:
        return "****" if key else ""
    return f"{key[:4]}...{key[-4:]}"


def get_user_api_key(user_id: str) -> str:
    """Return the user's API key, falling back to env var REQUESTY_API_KEY."""
    if user_id:
        key = _get_user_setting(user_id, "api_key")
        if key:
            return key
    return os.environ.get("REQUESTY_API_KEY", "")


def check_setup_complete(user_id: str) -> bool:
    """Check if a user has completed first-run setup (has API key configured)."""
    if not user_id:
        # Auth disabled — check env var fallback
        return bool(os.environ.get("REQUESTY_API_KEY", ""))
    key = _get_user_setting(user_id, "api_key")
    if key:
        return True
    # Allow fallback to env var for backward compatibility
    return bool(os.environ.get("REQUESTY_API_KEY", ""))


# ── Per-user settings endpoints ──────────────────────────────────────────────


@router.get("/user", response_model=UserSettings, summary="Get per-user settings")
def get_user_settings(user_id: str = Depends(require_user)) -> UserSettings:
    """Return the current user's personal settings (API key masked)."""
    settings = _get_all_user_settings(user_id)
    # Get display name from users table as fallback
    display_name = settings.get("display_name", "")
    if not display_name and user_id:
        with db() as conn:
            row = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
            if row:
                display_name = row["name"]
    return UserSettings(
        display_name=display_name,
        api_key=_mask_api_key(settings.get("api_key", "")),
        context_model=settings.get("context_model", ""),
        reasoning_model=settings.get("reasoning_model", ""),
        response_model=settings.get("response_model", ""),
    )


@router.put("/user", response_model=UserSettings, summary="Update per-user settings")
def update_user_settings(
    body: UserSettingsUpdate,
    user_id: str = Depends(require_user),
) -> UserSettings:
    """Update the current user's personal settings. Only provided fields are changed."""
    if not user_id:
        raise HTTPException(status_code=400, detail="Authentication required for user settings")

    if body.display_name is not None:
        _set_user_setting(user_id, "display_name", body.display_name)
        # Also update the users table name
        with db() as conn:
            conn.execute(
                "UPDATE users SET name = ?, updated_at = ? WHERE id = ?",
                (body.display_name, datetime.now(timezone.utc).isoformat(), user_id),
            )
    if body.api_key is not None:
        _set_user_setting(user_id, "api_key", body.api_key)
    if body.context_model is not None:
        _set_user_setting(user_id, "context_model", body.context_model)
    if body.reasoning_model is not None:
        _set_user_setting(user_id, "reasoning_model", body.reasoning_model)
    if body.response_model is not None:
        _set_user_setting(user_id, "response_model", body.response_model)

    return get_user_settings(user_id)


@router.get("/setup-status", response_model=SetupStatus, summary="Check first-run setup status")
def get_setup_status(user_id: str = Depends(require_user)) -> SetupStatus:
    """Check whether the user has completed the first-run setup wizard."""
    has_api_key = check_setup_complete(user_id)
    has_display_name = True  # Google auth always provides a name
    if user_id:
        name = _get_user_setting(user_id, "display_name")
        if not name:
            with db() as conn:
                row = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
                has_display_name = bool(row and row["name"])
    return SetupStatus(
        needs_setup=not has_api_key,
        has_api_key=has_api_key,
        has_display_name=has_display_name,
    )


@router.get("/model-costs", summary="Get model cost estimates")
def get_model_costs(_user_id: str = Depends(require_user)) -> list[dict[str, Any]]:
    """Return cost estimates per conversation for popular models."""
    return MODEL_COST_ESTIMATES
