"""Centralized environment configuration using pydantic-settings.

All environment variables are defined here as typed fields. Missing or misnamed vars fail fast at
startup instead of silently falling back.

Usage:
    from backend.config import settings

    settings.database_url
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ---
    DATABASE_URL: str = ""

    # --- MCP ---
    # Bearer token for the /mcp endpoint. Human-provisioned: an empty value closes /mcp with a
    # 401 rather than opening it, and never stops the boot — /healthz must stay green so a
    # missing secret does not roll the deploy back.
    MCP_API_TOKEN: str = ""

    # --- Google (read-only Calendar and Gmail) ---
    # Human-provisioned, exactly like MCP_API_TOKEN: a person runs
    # scripts/google_oauth_grant.py once and pastes the refresh token here. Empty defaults keep an
    # unconfigured deploy booting — only the three Google tools fail, and they say what to set.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REFRESH_TOKEN: str = ""

    # --- Logging ---
    LOG_LEVEL: str = "INFO"

    # --- Sentry ---
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "production"
    SENTRY_TRACES_SAMPLE_RATE: float = 0.2

    @property
    def database_url(self) -> str:
        """The Postgres connection string, which must come from the environment.

        There is no fallback: an unset ``DATABASE_URL`` raises rather than silently pointing the
        service at a local file, so a misconfigured deploy fails loudly instead of serving an
        empty database.
        """
        if not self.DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is not set. Reli requires a Postgres connection string; there is no local-file fallback."
            )
        return self.DATABASE_URL


settings = Settings()
