"""Sentry error monitoring integration.

Initializes Sentry SDK when SENTRY_DSN is configured. Provides a helper
to set user context (opaque user_id only) on the current Sentry scope.
"""

import logging

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from .config import settings

logger = logging.getLogger(__name__)


def _strip_cookie_breadcrumb(crumb: dict, hint: dict | None) -> dict | None:
    """Redact all Cookie/Set-Cookie header values from breadcrumbs.

    Sentry before_breadcrumb hook: return the crumb to keep it,
    or None to drop it entirely. This implementation always keeps the crumb.
    """
    data = crumb.get("data")
    if not isinstance(data, dict):
        return crumb
    for key in list(data):
        if key.lower() in ("cookie", "set-cookie", "authorization"):
            data[key] = "[Filtered]"
    return crumb


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
        before_breadcrumb=_strip_cookie_breadcrumb,
    )
    logger.info("Sentry initialized (env=%s)", settings.SENTRY_ENVIRONMENT)


def set_sentry_user(user_id: str) -> None:
    """Set user context on the current Sentry scope using opaque user ID only."""
    if not settings.SENTRY_DSN:
        return
    sentry_sdk.set_user({"id": user_id})
