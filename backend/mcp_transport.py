"""The bearer-token ASGI transport that fronts the mounted MCP app.

Split out of :mod:`backend.mcp_server`, which wraps :mod:`backend.service` and
:mod:`backend.queries` as MCP tools and carries no transport concerns of its own.
"""

from __future__ import annotations

import json
import logging

from mcp.server.transport_security import TransportSecuritySettings
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from . import auth
from .config import MIN_SECRET_KEY_BYTES, settings
from .mcp_server import reli_mcp

logger = logging.getLogger(__name__)

# --- Transport -------------------------------------------------------------


_EXPIRED = (
    "Access token expired: the connector refreshes it at /oauth/token with its refresh token, "
    "or re-authorises against Google"
)
_NOT_OURS = "Not a token this Reli issued: authorise the connector against Google via the authorization server"
_REVOKED = "Access token revoked: the connector refreshes it at /oauth/token, or re-authorises against Google"
_CLOSED = "/mcp is closed: a human sets SECRET_KEY and the Google sign-in settings (CLAUDE.md)"
_NO_BEARER = (
    "Authorization required: a Bearer of the access token the authorization server at /oauth/token "
    "issues after a Google sign-in"
)


_REFUSALS = {
    auth.Refusal.CLOSED: _CLOSED,
    auth.Refusal.EXPIRED: _EXPIRED,
    auth.Refusal.INVALID: _NOT_OURS,
    auth.Refusal.NOT_ALLOWED: auth.ACCOUNT_NOT_ALLOWED,
    auth.Refusal.REVOKED: _REVOKED,
}


class _BearerTokenMiddleware:
    """Requires ``Authorization: Bearer <credential>`` on every request to the mounted app.

    The one credential is an ``aud="mcp"`` JWT minted by the authorization server in
    :mod:`backend.mcp_oauth` after a Google sign-in, for an account still in ``ALLOWED_EMAILS``:
    the allowlist, the revocation list logout writes and the refresh family the token was issued
    under are read on every request, so removing an address or revoking the family ends its live
    tokens at once.

    An unset or too-short ``SECRET_KEY`` closes the endpoint rather than opening it: there is no
    dev-mode bypass, because /mcp is the only write path into the graph and it is publicly
    reachable. Every 401 says what a human or the connector must do next, and names the RFC 9728
    resource metadata when a base URL is configured, which is how an MCP client discovers the
    authorization server.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Read the secret per request, not at construction: the app is built at import time, so a
        # value captured then could never be corrected.
        if not settings.secret_key_configured:
            await _refuse(scope, receive, send, _CLOSED)
            return
        token = auth.bearer_token(scope)
        if not token:
            await _refuse(scope, receive, send, _NO_BEARER)
            return
        try:
            await run_in_threadpool(auth.admit, token, auth.MCP_AUDIENCE)
        except auth.CredentialRefused as refused:
            error = None if refused.reason is auth.Refusal.CLOSED else "invalid_token"
            await _refuse(scope, receive, send, _REFUSALS[refused.reason], error=error)
            return
        await self._app(scope, receive, send)


async def _refuse(scope: Scope, receive: Receive, send: Send, description: str, error: str | None = None) -> None:
    """A 401 whose body is the remedy and whose ``WWW-Authenticate`` follows RFC 6750 §3 and RFC 9728."""
    challenge = 'Bearer realm="reli"'
    base = auth.base_url()
    if base:
        challenge += f', resource_metadata="{base}/.well-known/oauth-protected-resource"'
    if error:
        challenge += f', error="{error}", error_description="{description}"'
    response = Response(
        content=json.dumps({"detail": description}),
        status_code=401,
        media_type="application/json",
        headers={"WWW-Authenticate": challenge},
    )
    await response(scope, receive, send)


def create_mcp_asgi_app() -> ASGIApp:
    """The streamable-HTTP MCP app behind the bearer check, for ``app.mount("/mcp", ...)``."""
    if not settings.secret_key_configured:
        logger.warning(
            "SECRET_KEY is not set, or is shorter than %d bytes: /mcp will answer 401 to every request.",
            MIN_SECRET_KEY_BYTES,
        )
    elif missing := auth.missing_sign_in_settings():
        logger.warning("SECRET_KEY is set but %s is not: the OAuth sign-in cannot complete.", ", ".join(missing))
    return _BearerTokenMiddleware(
        reli_mcp.streamable_http_app(
            # Mounted at /mcp by backend.main, so the SDK's own default of "/mcp" would serve
            # /mcp/mcp.
            streamable_http_path="/",
            # The tools carry the actor per call and hold no session state, so there is nothing
            # for a session to remember; stateless also survives a container restart
            # mid-conversation.
            stateless_http=True,
            # The SDK's default host allowlist is 127.0.0.1/localhost only, which answers 421 to
            # every request carrying a real Host header — Reli is served through a Cloudflare
            # tunnel, so that default is an outage. Rebinding only rides a credential the browser
            # attaches by itself, and _BearerTokenMiddleware admits nothing but a bearer a rebound
            # page cannot know and never reads a cookie; test_a_cookie_alone_never_reaches_the_mcp_app
            # holds that (#1823). Admitting any ambient credential here means turning this on first.
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
    )
