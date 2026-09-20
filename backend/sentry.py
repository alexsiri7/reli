"""Sentry error monitoring integration.

Initializes Sentry SDK when SENTRY_DSN is configured. Provides a helper
to set user context (opaque user_id only) on the current Sentry scope.
"""

import logging
from urllib.parse import urlsplit

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.types import Event, Hint

from .config import settings

logger = logging.getLogger(__name__)


def _strip_cookie_breadcrumb(crumb: dict, hint: dict | None) -> dict | None:
    """Redact sensitive header values (Cookie, Set-Cookie, Authorization) from breadcrumbs.

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


# The routes whose requests carry auth-flow secrets: /oauth/token reads client_secret,
# refresh_token, code and code_verifier from its form body, and Google lands on
# /api/auth/google/callback with code and state in the query string. Sentry's default scrubber
# matches keys exactly ("secret", "token"), so none of those names is caught by it.
_SECRET_BEARING_PREFIXES = ("/oauth/", "/api/auth/")


def _strip_auth_flow_request(event: Event, hint: Hint) -> Event:
    """Drop the request body, query string and cookies from events raised on a secret-bearing route.

    Sentry before_send / before_send_transaction hook. The event itself is always kept — the aim
    is that a 503 on /oauth/token still reports, without the credentials that were in the request.
    The SDK records ``request.url`` as a full URL when the Host header is present, so the match
    is on the path only.
    """
    request = event.get("request")
    if not isinstance(request, dict):
        return event
    url = request.get("url")
    if isinstance(url, str) and urlsplit(url).path.startswith(_SECRET_BEARING_PREFIXES):
        for key in ("data", "query_string", "cookies"):
            request.pop(key, None)
    return event


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
        # No request body on any event, and no frame locals: the /oauth/token handler holds
        # client_secret, refresh_token and code_verifier as plain locals, which a stack snapshot
        # would carry past the hook below.
        max_request_body_size="never",
        include_local_variables=False,
        before_breadcrumb=_strip_cookie_breadcrumb,
        before_send=_strip_auth_flow_request,
        before_send_transaction=_strip_auth_flow_request,
    )
    logger.info("Sentry initialized (env=%s)", settings.SENTRY_ENVIRONMENT)


def set_sentry_user(user_id: str) -> None:
    """Set user context on the current Sentry scope using opaque user ID only."""
    if not settings.SENTRY_DSN:
        return
    sentry_sdk.set_user({"id": user_id})
