"""Centralized environment configuration using pydantic-settings.

All environment variables are defined here as typed fields with defaults.
Missing or misnamed vars fail fast at startup instead of silently falling back.

Usage:
    from backend.config import settings

    settings.REQUESTY_API_KEY
    settings.DATA_DIR
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Requesty LLM gateway ---
    REQUESTY_BASE_URL: str = "https://router.requesty.ai/v1"
    REQUESTY_API_KEY: str = ""
    REQUESTY_MODEL: str = ""
    REQUESTY_REASONING_MODEL: str = ""
    REQUESTY_RESPONSE_MODEL: str = ""

    # --- Embedding ---
    EMBEDDING_MODEL: str = "text-embedding-3-large"

    # --- Ollama (optional local LLM) ---
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = ""
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"

    # --- Google OAuth ---
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/calendar/callback"
    GOOGLE_AUTH_REDIRECT_URI: str = "http://localhost:8000/api/auth/google/callback"

    # --- Google Custom Search ---
    GOOGLE_SEARCH_API_KEY: str = ""
    GOOGLE_SEARCH_CX: str = ""

    # --- Auth ---
    SECRET_KEY: str = ""
    ALLOWED_EMAILS: str = ""  # Comma-separated allowlist; empty = allow all

    @property
    def allowed_emails_set(self) -> set[str]:
        """Parse ALLOWED_EMAILS into a lowercase set. Empty string means allow all."""
        if not self.ALLOWED_EMAILS.strip():
            return set()
        return {e.strip().lower() for e in self.ALLOWED_EMAILS.split(",") if e.strip()}

    # --- Token encryption ---
    TOKEN_ENCRYPTION_KEY: str = ""

    # --- Data directory ---
    DATA_DIR: str = Field(default_factory=lambda: str(Path(__file__).parent))

    # --- Logging ---
    LOG_LEVEL: str = "INFO"

    # --- Rate limiting ---
    RATE_LIMIT_ENABLED: str = "true"
    RATE_LIMIT_LLM_RPM: int = 10
    RATE_LIMIT_API_RPM: int = 60

    # --- GitHub Feedback ---
    GITHUB_FEEDBACK_TOKEN: str = ""
    GITHUB_FEEDBACK_REPO: str = ""  # e.g. "owner/repo"

    # --- Sweep scheduler ---
    SWEEP_ENABLED: str = "true"
    SWEEP_HOUR: int = 3
    SWEEP_MINUTE: int = 0

    @property
    def rate_limit_enabled_bool(self) -> bool:
        return self.RATE_LIMIT_ENABLED.lower() not in ("false", "0", "no")

    @property
    def sweep_enabled_bool(self) -> bool:
        return self.SWEEP_ENABLED.lower() not in ("false", "0", "no")


settings = Settings()
