"""Centralized environment configuration using pydantic-settings.

All environment variables are defined here as typed fields with defaults.
Missing or misnamed vars fail fast at startup instead of silently falling back.

Usage:
    from backend.config import settings

    settings.REQUESTY_API_KEY
    settings.DATA_DIR
"""

import os
import warnings
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
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
    EMBEDDING_MODEL: str = "text-embedding-3-small"

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
    COOKIE_SECURE: str = "true"  # Set to "false" only in local dev (no HTTPS)

    # --- MCP API token (for MCP server → REST API auth) ---
    RELI_API_TOKEN: str = ""  # Shared secret; set to enable token-based auth for MCP
    # user_id this token authenticates as; if empty, falls back to first user (single-tenant)
    RELI_API_TOKEN_USER_ID: str = ""
    RELI_API_URL: str = "http://localhost:8000"  # Base URL for MCP server to reach REST API

    # --- MCP HTTP server token (for Claude Code → MCP server auth) ---
    MCP_API_TOKEN: str = ""  # Bearer token required to connect to /mcp endpoint

    # --- Application base URL (used in OAuth metadata endpoints) ---
    # If empty, derived from GOOGLE_AUTH_REDIRECT_URI (scheme + host).
    RELI_BASE_URL: str = ""  # e.g. https://reli.interstellarai.net

    @property
    def allowed_emails_set(self) -> set[str]:
        """Parse ALLOWED_EMAILS into a lowercase set. Empty string means allow all."""
        return {e.strip().lower() for e in self.ALLOWED_EMAILS.split(",") if e.strip()}

    # --- Token encryption ---
    TOKEN_ENCRYPTION_KEY: str = ""

    # --- Data directory ---
    DATA_DIR: str = Field(default_factory=lambda: str(Path(__file__).parent))

    # --- Logging ---
    LOG_LEVEL: str = "INFO"

    # --- Rate limiting ---
    RATE_LIMIT_ENABLED: str = "true"
    RATE_LIMIT_LLM_RPM: int = 30
    RATE_LIMIT_AUTH_RPM: int = 10
    RATE_LIMIT_API_RPM: int = 60
    # Comma-separated CIDRs of trusted reverse proxies (e.g. "10.0.0.0/8,172.16.0.0/12").
    # X-Forwarded-For is only trusted when the direct connection IP falls within one of these.
    # Empty string (default) means never trust X-Forwarded-For.
    RATE_LIMIT_TRUSTED_PROXY_CIDRS: str = ""

    # --- GitHub Feedback ---
    GITHUB_FEEDBACK_TOKEN: str = ""
    GITHUB_FEEDBACK_REPO: str = ""  # e.g. "owner/repo"

    # --- Storage backend ---
    STORAGE_BACKEND: Literal["sqlite", "supabase"] = "sqlite"
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""

    # --- Database URL (SQLModel/SQLAlchemy) ---
    # When set, used directly (e.g. postgresql://user:pass@host/db for Supabase).
    # When empty, derived as sqlite:///DATA_DIR/reli.db.
    DATABASE_URL: str = ""

    @property
    def database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"sqlite:///{Path(self.DATA_DIR) / 'reli.db'}"

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        """Fail fast if required secrets are missing in production."""
        if os.getenv("RAILWAY_ENVIRONMENT_NAME") or os.getenv("PRODUCTION"):
            required = {
                "SECRET_KEY": self.SECRET_KEY,
                "REQUESTY_API_KEY": self.REQUESTY_API_KEY,
            }
            missing = [k for k, v in required.items() if not v]
            if missing:
                raise ValueError(f"Missing required production env vars: {', '.join(missing)}")
        if not self.SECRET_KEY and not self.RELI_API_TOKEN:
            auth_disabled = os.getenv("AUTH_DISABLED", "").lower() in ("true", "1", "yes")
            if not auth_disabled:
                raise ValueError(
                    "SECRET_KEY or RELI_API_TOKEN must be set. "
                    "To intentionally run without auth, set AUTH_DISABLED=true"
                )
            warnings.warn(
                "SECRET_KEY is empty — authentication is DISABLED (AUTH_DISABLED=true)",
                stacklevel=2,
            )
        elif not self.SECRET_KEY:
            warnings.warn(
                "SECRET_KEY is empty — cookie-based auth (Google OAuth) is DISABLED",
                stacklevel=2,
            )
        return self

    @model_validator(mode="after")
    def _validate_supabase_config(self) -> "Settings":
        if self.STORAGE_BACKEND == "supabase":
            missing = []
            if not self.SUPABASE_URL:
                missing.append("SUPABASE_URL")
            if not self.SUPABASE_KEY:
                missing.append("SUPABASE_KEY")
            if missing:
                raise ValueError(f"STORAGE_BACKEND=supabase requires: {', '.join(missing)}")
        return self

    # --- CORS ---
    CORS_ORIGINS: str = ""  # Comma-separated extra origins (e.g. https://reli.interstellarai.net)
    MCP_CORS_ORIGINS: str = ""  # Comma-separated origins allowed on MCP/OAuth endpoints; empty = use wildcard (*)

    # --- Sentry ---
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "production"
    SENTRY_TRACES_SAMPLE_RATE: float = 0.2

    # --- Phoenix / OpenTelemetry ---
    PHOENIX_ENABLED: str = "false"
    PHOENIX_ENDPOINT: str = "http://localhost:6006/v1/traces"
    OTEL_SERVICE_NAME: str = "reli"

    @staticmethod
    def _is_truthy(value: str) -> bool:
        return value.lower() not in ("false", "0", "no")

    @property
    def phoenix_enabled_bool(self) -> bool:
        return self._is_truthy(self.PHOENIX_ENABLED)

    # --- Sweep scheduler ---
    SWEEP_ENABLED: str = "true"
    SWEEP_HOUR: int = 3
    SWEEP_MINUTE: int = 0
    SWEEP_SUPPRESSED_FINDING_TYPES: str = "lifestyle_wellness,location_suggestion,unverified_context"
    # 0.0 = disabled, 1.0 = blocks everything; findings below threshold are excluded from briefings
    SWEEP_MIN_CONFIDENCE: float = 0.5
    # Auto-merge: execute merges autonomously for exact-match duplicates above this threshold
    SWEEP_AUTO_MERGE_ENABLED: str = "true"
    SWEEP_AUTO_MERGE_CONFIDENCE_THRESHOLD: float = 0.95

    @property
    def suppressed_finding_types_set(self) -> frozenset[str]:
        return frozenset(t.strip() for t in self.SWEEP_SUPPRESSED_FINDING_TYPES.split(",") if t.strip())

    @property
    def rate_limit_enabled_bool(self) -> bool:
        return self._is_truthy(self.RATE_LIMIT_ENABLED)

    @property
    def sweep_enabled_bool(self) -> bool:
        return self._is_truthy(self.SWEEP_ENABLED)

    @property
    def sweep_auto_merge_enabled_bool(self) -> bool:
        return self._is_truthy(self.SWEEP_AUTO_MERGE_ENABLED)

    @property
    def cookie_secure_bool(self) -> bool:
        return self._is_truthy(self.COOKIE_SECURE)


settings = Settings()
