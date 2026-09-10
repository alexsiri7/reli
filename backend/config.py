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
