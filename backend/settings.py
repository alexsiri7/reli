"""Centralized environment configuration using pydantic-settings.

All environment variables are defined here as typed fields with defaults.
Import ``settings`` from this module instead of calling ``os.environ.get()``
directly.  Misnamed or missing variables are caught at import time.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Logging ---
    log_level: str = "INFO"

    # --- Data directory ---
    data_dir: str = str(Path(__file__).parent)

    # --- Requesty (LLM gateway) ---
    requesty_base_url: str = "https://router.requesty.ai/v1"
    requesty_api_key: str = ""
    requesty_model: str = ""
    requesty_reasoning_model: str = ""
    requesty_response_model: str = ""

    # --- Embedding ---
    embedding_model: str = "text-embedding-3-large"

    # --- Ollama (optional local LLM) ---
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""
    ollama_embed_model: str = "nomic-embed-text"

    # --- Google OAuth ---
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/calendar/callback"
    google_auth_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # --- JWT / Auth ---
    secret_key: str = ""

    # --- Token encryption ---
    token_encryption_key: str = ""

    # --- Google Custom Search ---
    google_search_api_key: str = ""
    google_search_cx: str = ""

    # --- Rate limiting ---
    rate_limit_enabled: str = "true"
    rate_limit_llm_rpm: int = 10
    rate_limit_api_rpm: int = 60

    # --- Sweep scheduler ---
    sweep_enabled: str = "true"
    sweep_hour: int = Field(default=3, ge=0, le=23)
    sweep_minute: int = Field(default=0, ge=0, le=59)

    @property
    def rate_limit_is_enabled(self) -> bool:
        return self.rate_limit_enabled.lower() not in ("false", "0", "no")

    @property
    def sweep_is_enabled(self) -> bool:
        return self.sweep_enabled.lower() not in ("false", "0", "no")


settings = Settings()
