"""Reli FastAPI application entry point.

Reli is a data service, not an application: the graph is reached over MCP and the judgement happens
in Claude. This app serves the health check the deploy pipeline polls, the OAuth 2.1 authorization
server of :mod:`backend.mcp_oauth` and the Google callback of :mod:`backend.auth` that an MCP client
authorises through, mounts the MCP tools of :mod:`backend.mcp_server` at ``/mcp``, and serves the
read-only web view of :mod:`backend.api` — its ``/api`` routes and, when the image was built with
one, the frontend bundle behind them.
"""

import logging
import pathlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from . import api, auth, mcp_oauth
from .config import settings
from .mcp_server import create_mcp_asgi_app, reli_mcp
from .sentry import init_sentry

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

init_sentry()

_ALEMBIC_INI = pathlib.Path(__file__).resolve().parent.parent / "alembic.ini"
_DIST = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bring the schema to head before serving.

    A migration failure propagates and the boot fails. There is deliberately no ``create_all``
    fallback: the journal's append-only trigger lives in the migration and not in the ORM metadata,
    so a schema built from metadata would be a silently mutable journal.

    The MCP session manager is started here rather than by the mounted sub-app, because a mounted
    Starlette app's own lifespan never runs.
    """
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    alembic_command.upgrade(AlembicConfig(str(_ALEMBIC_INI)), "head")
    logger.info("Alembic migrations applied successfully.")
    async with reli_mcp.session_manager.run():
        yield


app = FastAPI(
    title="Reli API",
    description=(
        "Reli stores Things, the relationships between them, and an append-only journal of every "
        "mutation. Reads and writes arrive over MCP at /mcp. The /api routes are the read-only view "
        "the web frontend consumes, with one exception: rejecting a preference."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz", tags=["health"], summary="Health check", description="Returns service health status.")
def health() -> dict[str, str]:
    """Returns service health status."""
    return {"status": "ok", "service": "reli"}


class _BareMcpPath:
    """Serves ``/mcp`` as ``/mcp/`` instead of redirecting to it.

    The mount below only matches under ``/mcp/``; a bare ``/mcp`` is otherwise a 307 — Starlette's own
    slash redirect, or the explicit one this replaced — and the claude.ai connector follows a 307
    without re-sending its ``Authorization`` header, so the follow-up is a 401 and the connector
    reports the authorisation as failed right after completing it. Rewriting the path before routing
    keeps one mount, one bearer check and no redirect for any method the streamable-HTTP transport
    uses; ``/mcp/`` stays the canonical resource the protected-resource metadata advertises.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == "/mcp":
            scope = {**scope, "path": "/mcp/", "raw_path": (scope.get("raw_path") or b"/mcp") + b"/"}
        await self._app(scope, receive, send)


# Before api.router, which ends in the /api/{unmatched:path} catch-all that would otherwise take the
# Google callback.
app.include_router(auth.router)
app.include_router(mcp_oauth.router)
app.include_router(api.router)
app.mount("/mcp", create_mcp_asgi_app())
app.add_middleware(_BareMcpPath)

# Last, and in this order: the frontend fallback answers every unmatched path, so anything mounted
# after it would never be reached.
api.mount_frontend(app, _DIST)
api.add_web_view_auth(app)
