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

    # --- Web view ---
    # HTTP Basic password the /api routes accept, beside the Google sign-in's session cookie.
    # Human-provisioned on the same terms as MCP_API_TOKEN: an empty value closes nothing the
    # sign-in opens, and with the sign-in also unset /api answers 401 to everything — never
    # stopping the boot, so /healthz stays green and a missing secret does not roll the deploy
    # back. The bundle at / is always public; it is the sign-in view.
    WEB_UI_PASSWORD: str = ""

    # --- Google sign-in (web view and MCP) ---
    # The settings behind the OAuth 2.1 authorization server at /oauth/* and the Google login it
    # delegates to. Human-provisioned on the MCP_API_TOKEN pattern: every one defaults to empty,
    # an empty value closes the sign-in (501 from /oauth/authorize naming what is missing, no JWT
    # ever accepted) and never stops the boot.
    #
    # SECRET_KEY signs every JWT Reli mints (HS256). PyJWT warns below 32 bytes; provision with
    # `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
    SECRET_KEY: str = ""
    # Comma-separated Google account emails allowed to sign in. Empty admits nobody.
    ALLOWED_EMAILS: str = ""
    # Where Google sends the browser back: `<base>/api/auth/google/callback`, registered verbatim on
    # the OAuth client. No localhost default — an empty value is "not configured", never a guess
    # sent to Google.
    GOOGLE_AUTH_REDIRECT_URI: str = ""
    # The issuer and the base of the OAuth metadata documents. When empty it is derived from
    # GOOGLE_AUTH_REDIRECT_URI's scheme and host.
    RELI_BASE_URL: str = ""

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
    def allowed_emails(self) -> frozenset[str]:
        """The ALLOWED_EMAILS list, lower-cased, with blanks dropped. Empty means nobody may sign in."""
        return frozenset(email.strip().lower() for email in self.ALLOWED_EMAILS.split(",") if email.strip())

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
