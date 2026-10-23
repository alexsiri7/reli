"""Session-cookie auth guarding the ``/api`` routes.

Split out of :mod:`backend.api`, which is the read-only HTTP surface the web view consumes and
carries no transport-level access control of its own.
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from . import auth

logger = logging.getLogger(__name__)

# --- Access control --------------------------------------------------------


#: What the check guards: the graph, which only ``/api`` serves. The bundle is static code from a
#: public repository and is the sign-in view, so it answers everyone; ``/api/auth/`` is how a
#: browser gets a session, so it must answer before there is one, and it is the only ``/api`` path
#: that does. ``/healthz``, ``/mcp``, ``/.well-known/`` and ``/oauth/`` were never the web view's to
#: guard — ``/mcp`` carries its own bearer check. The prefix ends in a slash so ``/api/auth`` cannot
#: be widened into ``/api/authors``.
_GUARDED_PREFIX = "/api/"
_PUBLIC_PREFIX = "/api/auth/"

_NO_CREDENTIAL = "Not signed in: sign in with Google at /."


def _is_guarded(path: str) -> bool:
    if path.startswith(_PUBLIC_PREFIX):
        return False
    return path == "/api" or path.startswith(_GUARDED_PREFIX)


def _refusal(request: Request) -> str | None:
    """Why the request is not admitted, or ``None`` when the ``__Host-reli_session`` cookie admits it."""
    try:
        if auth.web_session(request) is not None:
            return None
    except auth.SessionRefused as refused:
        return str(refused)
    return _NO_CREDENTIAL


class _WebViewAuthMiddleware:
    """Requires the ``__Host-reli_session`` cookie on every ``/api`` path outside the public ones.

    The cookie is the only credential: there is no HTTP Basic password any more (#1471), so nothing
    but a Google sign-in opens the graph. Nothing configured closes it rather than opening it —
    there is no dev-mode bypass, because these routes serve the user's whole graph and the deploy
    URLs answer the public internet.

    The 401 carries no ``WWW-Authenticate``: a challenge would make the browser pop its own
    credential prompt over the sign-in view. The body says what admits a request instead.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_guarded(scope.get("path", "")):
            await self._app(scope, receive, send)
            return

        reason = _refusal(Request(scope))
        if reason is not None:
            response = Response(content=json.dumps({"detail": reason}), status_code=401, media_type="application/json")
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)


def add_web_view_auth(app: FastAPI) -> None:
    """Put every ``/api`` route outside ``/api/auth/`` behind the session."""
    missing = auth.missing_sign_in_settings()
    if missing:
        logger.warning(
            "The Google sign-in is missing %s: /api will answer 401 to every request.",
            ", ".join(missing),
        )
    base = auth.base_url()
    if base and not base.startswith("https://"):
        logger.warning(
            "RELI_BASE_URL / GOOGLE_AUTH_REDIRECT_URI resolve to %s, not https: the %s cookie is Secure "
            "regardless, and a deploy actually served over http cannot hold a web session.",
            base,
            auth.SESSION_COOKIE,
        )
    app.add_middleware(_WebViewAuthMiddleware)
