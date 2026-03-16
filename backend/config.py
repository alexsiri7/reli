"""Centralized environment configuration using pydantic-settings.

All environment variables are defined here as typed fields with defaults.
Misnamed or missing vars fail fast at startup instead of silently falling back.

Usage::

    from backend.config import settings

    base_url = settings.requesty_base_url
    api_key = settings.requesty_api_key
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _BACKEND_DIR.parent

# ---------------------------------------------------------------------------
# config.yaml loading — provides defaults for LLM model fields
# ---------------------------------------------------------------------------

_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"


def _load_yaml_config() -> dict[str, Any]:
    """Load config from config.yaml, falling back to defaults."""
    defaults: dict[str, Any] = {
        "llm": {
            "base_url": "https://router.requesty.ai/v1",
            "models": {
                "context": "google/gemini-2.5-flash-lite",
                "reasoning": "google/gemini-3-flash-preview",
                "response": "google/gemini-2.5-flash-lite",
            },
        },
        "ollama": {"base_url": "http://localhost:11434", "model": ""},
        "embedding": {"model": "text-embedding-3-small"},
    }
    try:
        with open(_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        for key in defaults:
            if key in cfg:
                if isinstance(defaults[key], dict) and isinstance(cfg[key], dict):
                    defaults[key] = {**defaults[key], **cfg[key]}
                else:
                    defaults[key] = cfg[key]
        if "pricing" in cfg:
            defaults["pricing"] = cfg["pricing"]
        return defaults
    except FileNotFoundError:
        logger.warning("config.yaml not found at %s, using defaults", _CONFIG_PATH)
        return defaults


yaml_config = _load_yaml_config()
_models = yaml_config["llm"]["models"]

# ---------------------------------------------------------------------------
# Settings class — single source of truth for all env vars
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file.

    Field names map to UPPER_CASE env var names automatically
    (e.g. ``requesty_api_key`` reads ``REQUESTY_API_KEY``).
    """

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- Logging -------------------------------------------------------------
    log_level: str = "INFO"

    # -- Data directory -------------------------------------------------------
    data_dir: str = str(_BACKEND_DIR)

    # -- Auth / JWT -----------------------------------------------------------
    secret_key: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_auth_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"
    google_redirect_uri: str = "http://localhost:8000/api/calendar/callback"

    # -- Requesty (LLM gateway) ----------------------------------------------
    requesty_base_url: str = yaml_config["llm"]["base_url"]
    requesty_api_key: str = ""
    requesty_model: str = _models.get("context", "google/gemini-2.5-flash-lite")
    requesty_reasoning_model: str = _models.get("reasoning", "google/gemini-3-flash-preview")
    requesty_response_model: str = _models.get("response", "google/gemini-2.5-flash-lite")

    # -- Embedding ------------------------------------------------------------
    embedding_model: str = yaml_config.get("embedding", {}).get("model", "text-embedding-3-small")

    # -- Ollama (optional local LLM) -----------------------------------------
    ollama_base_url: str = yaml_config["ollama"]["base_url"]
    ollama_model: str = yaml_config["ollama"].get("model", "")
    ollama_embed_model: str = "nomic-embed-text"

    # -- Google Search --------------------------------------------------------
    google_search_api_key: str = ""
    google_search_cx: str = ""

    # -- Rate limiting --------------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_llm_rpm: int = 10
    rate_limit_api_rpm: int = 60

    # -- Sweep scheduler ------------------------------------------------------
    sweep_enabled: bool = True
    sweep_hour: int = 3
    sweep_minute: int = 0

    # -- Token encryption -----------------------------------------------------
    token_encryption_key: str = ""

    # -- Validators -----------------------------------------------------------

    @field_validator("sweep_hour")
    @classmethod
    def clamp_hour(cls, v: int) -> int:
        return max(0, min(23, v))

    @field_validator("sweep_minute")
    @classmethod
    def clamp_minute(cls, v: int) -> int:
        return max(0, min(59, v))

    @field_validator("rate_limit_llm_rpm", "rate_limit_api_rpm")
    @classmethod
    def min_one_rpm(cls, v: int) -> int:
        return max(1, v)


settings = Settings()
