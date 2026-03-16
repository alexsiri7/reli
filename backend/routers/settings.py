"""Settings endpoints: per-user model configuration and API keys."""

import logging
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

# Valid setting keys that can be stored per-user
_VALID_KEYS = frozenset({
    "requesty_api_key",
    "openai_api_key",
    "context_model",
    "reasoning_model",
    "response_model",
    "embedding_model",
    "chat_context_window",
})


# ── Request/Response models ──────────────────────────────────────────────────


class ModelSettings(BaseModel):
    context: str
    reasoning: str
    response: str
    chat_context_window: int = 3
    has_api_key: bool = False


class ModelSettingsUpdate(BaseModel):
    context: str | None = None
    reasoning: str | None = None
    response: str | None = None
    chat_context_window: int | None = None
    requesty_api_key: str | None = None


class RequestyModel(BaseModel):
    id: str
    name: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _read_config() -> dict[str, Any]:
    try:
        with open(_CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _get_user_settings(user_id: str) -> dict[str, str]:
    """Load all settings for a user from the DB."""
    if not user_id:
        return {}
    with db() as conn:
        rows = conn.execute(
            "SELECT setting_key, setting_value FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return {row["setting_key"]: row["setting_value"] for row in rows}


def _set_user_setting(user_id: str, key: str, value: str | None, conn: Any = None) -> None:
    """Upsert a single user setting."""
    if not user_id or key not in _VALID_KEYS:
        return
    if value is None or value == "":
        # Delete the setting to fall back to defaults
        if conn:
            conn.execute(
                "DELETE FROM user_settings WHERE user_id = ? AND setting_key = ?",
                (user_id, key),
            )
        else:
            with db() as c:
                c.execute(
                    "DELETE FROM user_settings WHERE user_id = ? AND setting_key = ?",
                    (user_id, key),
                )
        return
    if conn:
        conn.execute(
            "INSERT INTO user_settings (user_id, setting_key, setting_value, updated_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(user_id, setting_key) DO UPDATE SET setting_value = excluded.setting_value, updated_at = CURRENT_TIMESTAMP",
            (user_id, key, value),
        )
    else:
        with db() as c:
            c.execute(
                "INSERT INTO user_settings (user_id, setting_key, setting_value, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id, setting_key) DO UPDATE SET setting_value = excluded.setting_value, updated_at = CURRENT_TIMESTAMP",
                (user_id, key, value),
            )


def get_user_llm_config(user_id: str) -> dict[str, str]:
    """Return resolved LLM config for a user: per-user settings with config.yaml fallback.

    Used by the chat pipeline to get the correct API key and models per request.
    """
    import os

    cfg = _read_config()
    models = cfg.get("llm", {}).get("models", {})

    # Defaults from config.yaml / env
    result = {
        "api_key": os.environ.get("REQUESTY_API_KEY", ""),
        "base_url": os.environ.get("REQUESTY_BASE_URL", cfg.get("llm", {}).get("base_url", "https://router.requesty.ai/v1")),
        "context_model": os.environ.get("REQUESTY_MODEL", models.get("context", "google/gemini-2.5-flash-lite")),
        "reasoning_model": os.environ.get("REQUESTY_REASONING_MODEL", models.get("reasoning", "google/gemini-3-flash-preview")),
        "response_model": os.environ.get("REQUESTY_RESPONSE_MODEL", models.get("response", "google/gemini-2.5-flash-lite")),
        "chat_context_window": str(cfg.get("chat", {}).get("context_window", 3)),
    }

    # Override with per-user settings from DB
    user_settings = _get_user_settings(user_id)
    if user_settings.get("requesty_api_key"):
        result["api_key"] = user_settings["requesty_api_key"]
    if user_settings.get("context_model"):
        result["context_model"] = user_settings["context_model"]
    if user_settings.get("reasoning_model"):
        result["reasoning_model"] = user_settings["reasoning_model"]
    if user_settings.get("response_model"):
        result["response_model"] = user_settings["response_model"]
    if user_settings.get("chat_context_window"):
        result["chat_context_window"] = user_settings["chat_context_window"]

    return result


def get_chat_context_window(user_id: str = "") -> int:
    """Return the configured chat context window size for a user."""
    if user_id:
        user_settings = _get_user_settings(user_id)
        if user_settings.get("chat_context_window"):
            try:
                return int(user_settings["chat_context_window"])
            except ValueError:
                pass
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
def get_settings(user_id: str = Depends(require_user)) -> ModelSettings:
    """Return current model configuration for the user (per-user overrides with config.yaml fallback)."""
    llm_config = get_user_llm_config(user_id)
    user_settings = _get_user_settings(user_id)
    return ModelSettings(
        context=llm_config["context_model"],
        reasoning=llm_config["reasoning_model"],
        response=llm_config["response_model"],
        chat_context_window=int(llm_config["chat_context_window"]),
        has_api_key=bool(user_settings.get("requesty_api_key")),
    )


@router.put("", response_model=ModelSettings, summary="Update model settings")
def update_settings(
    body: ModelSettingsUpdate,
    user_id: str = Depends(require_user),
) -> ModelSettings:
    """Update per-user model configuration. Only provided fields are changed."""
    with db() as conn:
        if body.context is not None:
            _set_user_setting(user_id, "context_model", body.context, conn)
        if body.reasoning is not None:
            _set_user_setting(user_id, "reasoning_model", body.reasoning, conn)
        if body.response is not None:
            _set_user_setting(user_id, "response_model", body.response, conn)
        if body.chat_context_window is not None:
            clamped = max(1, min(body.chat_context_window, 50))
            _set_user_setting(user_id, "chat_context_window", str(clamped), conn)
        if body.requesty_api_key is not None:
            # Empty string clears the key (falls back to env var)
            _set_user_setting(user_id, "requesty_api_key", body.requesty_api_key or None, conn)

    # Return updated settings
    llm_config = get_user_llm_config(user_id)
    user_settings = _get_user_settings(user_id)
    return ModelSettings(
        context=llm_config["context_model"],
        reasoning=llm_config["reasoning_model"],
        response=llm_config["response_model"],
        chat_context_window=int(llm_config["chat_context_window"]),
        has_api_key=bool(user_settings.get("requesty_api_key")),
    )
