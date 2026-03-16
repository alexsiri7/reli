"""Settings endpoints: per-user settings in DB with config.yaml fallback."""

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

# Keys that are stored per-user in user_settings table
_VALID_KEYS = {
    "requesty_api_key",
    "openai_api_key",
    "embedding_model",
    "context_model",
    "reasoning_model",
    "response_model",
    "chat_context_window",
    "display_name",
    "setup_completed",
}


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


class UserSettings(BaseModel):
    """Per-user settings stored in DB."""

    requesty_api_key: str = ""
    openai_api_key: str = ""
    embedding_model: str = ""
    context_model: str = ""
    reasoning_model: str = ""
    response_model: str = ""
    chat_context_window: int | None = None


class UserSettingsUpdate(BaseModel):
    """Partial update for per-user settings."""

    requesty_api_key: str | None = None
    openai_api_key: str | None = None
    embedding_model: str | None = None
    context_model: str | None = None
    reasoning_model: str | None = None
    response_model: str | None = None
    chat_context_window: int | None = None


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


def get_user_setting(user_id: str, key: str) -> str | None:
    """Read a single user setting from the DB. Returns None if not set."""
    if not user_id:
        return None
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = ?",
            (user_id, key),
        ).fetchone()
    return row["value"] if row else None


def get_user_settings_dict(user_id: str) -> dict[str, str]:
    """Read all settings for a user from the DB."""
    if not user_id:
        return {}
    with db() as conn:
        rows = conn.execute(
            "SELECT key, value FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return {row["key"]: row["value"] for row in rows}


def _set_user_setting(conn: Any, user_id: str, key: str, value: str) -> None:
    """Upsert a single user setting."""
    conn.execute(
        """INSERT INTO user_settings (user_id, key, value, updated_at)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP""",
        (user_id, key, value),
    )


def get_user_chat_context_window(user_id: str) -> int:
    """Return per-user chat context window, falling back to global config."""
    val = get_user_setting(user_id, "chat_context_window")
    if val is not None:
        try:
            return max(1, min(int(val), 50))
        except (ValueError, TypeError):
            pass
    return get_chat_context_window()


def get_user_api_key(user_id: str) -> str:
    """Return user's Requesty API key, falling back to env/global."""
    import os

    key = get_user_setting(user_id, "requesty_api_key")
    if key:
        return key
    return os.environ.get("REQUESTY_API_KEY", "")


def get_user_models(user_id: str) -> dict[str, str]:
    """Return resolved model names for a user (per-user overrides + global fallback)."""
    import backend.agents as agents_mod

    user_settings = get_user_settings_dict(user_id)
    return {
        "context": user_settings.get("context_model") or agents_mod.REQUESTY_MODEL,
        "reasoning": user_settings.get("reasoning_model") or agents_mod.REQUESTY_REASONING_MODEL,
        "response": user_settings.get("response_model") or agents_mod.REQUESTY_RESPONSE_MODEL,
    }


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/models", response_model=list[RequestyModel], summary="List available LLM models")
def list_models(user_id: str = Depends(require_user)) -> list[RequestyModel]:
    """Proxy the Requesty /v1/models endpoint using the user's API key if available."""
    cfg = _read_config()
    base_url = cfg.get("llm", {}).get("base_url", "https://router.requesty.ai/v1")

    # Use user's API key for the models request if they have one
    api_key = get_user_api_key(user_id) if user_id else ""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    try:
        resp = httpx.get(f"{base_url}/models", timeout=10.0, headers=headers)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return [RequestyModel(id=m["id"], name=m.get("name")) for m in data if m.get("id")]
    except Exception as exc:
        logger.warning("Failed to fetch models from Requesty: %s", exc)
        raise HTTPException(status_code=502, detail="Could not fetch models from Requesty API") from exc


@router.get("", response_model=ModelSettings, summary="Get current model settings")
def get_settings(user_id: str = Depends(require_user)) -> ModelSettings:
    """Return model settings: per-user overrides merged with global defaults."""
    cfg = _read_config()
    global_models = cfg.get("llm", {}).get("models", {})
    global_context_window = cfg.get("chat", {}).get("context_window", 3)

    # Per-user overrides
    user_settings = get_user_settings_dict(user_id) if user_id else {}

    return ModelSettings(
        context=user_settings.get("context_model") or global_models.get("context", "google/gemini-2.5-flash-lite"),
        reasoning=user_settings.get("reasoning_model") or global_models.get("reasoning", "google/gemini-3-flash-preview"),
        response=user_settings.get("response_model") or global_models.get("response", "google/gemini-2.5-flash-lite"),
        chat_context_window=int(user_settings["chat_context_window"]) if "chat_context_window" in user_settings else global_context_window,
    )


@router.put("", response_model=ModelSettings, summary="Update model settings")
def update_settings(
    body: ModelSettingsUpdate,
    user_id: str = Depends(require_user),
) -> ModelSettings:
    """Update model settings. With auth: saves per-user. Without auth: writes config.yaml."""
    if user_id:
        # Per-user: save to DB
        with db() as conn:
            if body.context is not None:
                _set_user_setting(conn, user_id, "context_model", body.context)
            if body.reasoning is not None:
                _set_user_setting(conn, user_id, "reasoning_model", body.reasoning)
            if body.response is not None:
                _set_user_setting(conn, user_id, "response_model", body.response)
            if body.chat_context_window is not None:
                clamped = max(1, min(body.chat_context_window, 50))
                _set_user_setting(conn, user_id, "chat_context_window", str(clamped))

        return get_settings(user_id)

    # No auth: legacy config.yaml path
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


@router.get("/user", response_model=UserSettings, summary="Get per-user settings")
def get_user_settings_endpoint(user_id: str = Depends(require_user)) -> UserSettings:
    """Return all per-user settings (API keys masked)."""
    user_settings = get_user_settings_dict(user_id) if user_id else {}

    # Mask API keys — return last 4 chars only
    def _mask(val: str) -> str:
        if not val:
            return ""
        if len(val) <= 4:
            return "****"
        return "*" * (len(val) - 4) + val[-4:]

    return UserSettings(
        requesty_api_key=_mask(user_settings.get("requesty_api_key", "")),
        openai_api_key=_mask(user_settings.get("openai_api_key", "")),
        embedding_model=user_settings.get("embedding_model", ""),
        context_model=user_settings.get("context_model", ""),
        reasoning_model=user_settings.get("reasoning_model", ""),
        response_model=user_settings.get("response_model", ""),
        chat_context_window=int(user_settings["chat_context_window"]) if "chat_context_window" in user_settings else None,
    )


@router.put("/user", response_model=UserSettings, summary="Update per-user settings")
def update_user_settings(
    body: UserSettingsUpdate,
    user_id: str = Depends(require_user),
) -> UserSettings:
    """Update per-user settings (API keys, model overrides)."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required for user settings")

    with db() as conn:
        for field_name in _VALID_KEYS:
            val = getattr(body, field_name, None)
            if val is not None:
                if field_name == "chat_context_window":
                    val = str(max(1, min(int(val), 50)))
                _set_user_setting(conn, user_id, field_name, str(val))

    return get_user_settings_endpoint(user_id)


# ── Setup wizard endpoints ────────────────────────────────────────────────────


class SetupStatus(BaseModel):
    needs_setup: bool
    display_name: str


class SetupComplete(BaseModel):
    display_name: str
    requesty_api_key: str
    context_model: str | None = None
    reasoning_model: str | None = None
    response_model: str | None = None


@router.get("/setup-status", response_model=SetupStatus, summary="Check if first-run setup is needed")
def get_setup_status(user_id: str = Depends(require_user)) -> SetupStatus:
    """Return whether the user needs to complete first-run setup."""
    if not user_id:
        return SetupStatus(needs_setup=True, display_name="")

    user_settings = get_user_settings_dict(user_id)

    # Setup is complete if the user has explicitly completed it
    setup_done = user_settings.get("setup_completed") == "true"

    # Also check if they already have an API key (env or per-user) — skip wizard
    if not setup_done:
        has_key = bool(get_user_api_key(user_id))
        if has_key:
            setup_done = True

    # Get display name from settings, fallback to user profile name
    display_name = user_settings.get("display_name", "")
    if not display_name:
        with db() as conn:
            row = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
        display_name = row["name"] if row else ""

    return SetupStatus(needs_setup=not setup_done, display_name=display_name)


@router.post("/complete-setup", response_model=SetupStatus, summary="Complete first-run setup")
def complete_setup(
    body: SetupComplete,
    user_id: str = Depends(require_user),
) -> SetupStatus:
    """Save all setup wizard data and mark setup as complete."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    with db() as conn:
        if body.display_name:
            _set_user_setting(conn, user_id, "display_name", body.display_name)
            # Also update the users table name
            conn.execute(
                "UPDATE users SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (body.display_name, user_id),
            )
        if body.requesty_api_key:
            _set_user_setting(conn, user_id, "requesty_api_key", body.requesty_api_key)
        if body.context_model:
            _set_user_setting(conn, user_id, "context_model", body.context_model)
        if body.reasoning_model:
            _set_user_setting(conn, user_id, "reasoning_model", body.reasoning_model)
        if body.response_model:
            _set_user_setting(conn, user_id, "response_model", body.response_model)
        _set_user_setting(conn, user_id, "setup_completed", "true")

    return SetupStatus(needs_setup=False, display_name=body.display_name)
