"""Sentry error monitoring integration.

Initializes Sentry SDK when SENTRY_DSN is configured. Provides a helper
to set user context (user_id, email) on the current Sentry scope.
"""

import logging

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from .config import settings

logger = logging.getLogger(__name__)


def init_sentry() -> None:
    """Initialize Sentry SDK if SENTRY_DSN is configured."""
    if not settings.SENTRY_DSN:
        logger.info("SENTRY_DSN not set — Sentry disabled")
        return

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
        ],
        send_default_pii=False,
    )
    logger.info("Sentry initialized (env=%s)", settings.SENTRY_ENVIRONMENT)


def set_sentry_user(user_id: str, email: str | None = None) -> None:
    """Set user context on the current Sentry scope."""
    if not settings.SENTRY_DSN:
        return
    user_data: dict[str, str] = {"id": user_id}
    if email:
        user_data["email"] = email
    sentry_sdk.set_user(user_data)
