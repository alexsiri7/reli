"""Reli FastAPI application entry point."""

import logging
import pathlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx

from .config import settings as _app_settings  # noqa: E402 — must load before other backend imports

# Configure logging — LOG_LEVEL env var controls verbosity (default: INFO)
logging.basicConfig(
    level=getattr(logging, _app_settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

from .sentry import init_sentry  # noqa: E402

init_sentry()

from .tracing import init_tracing  # noqa: E402

init_tracing()

from fastapi import Depends, FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.responses import Response as StarletteResponse  # noqa: E402

from .auth import COOKIE_NAME, JWT_ALGORITHM, SECRET_KEY, require_user  # noqa: E402
from .database import clean_orphan_relationships, init_db  # noqa: E402
from .mcp_server import create_mcp_asgi_app  # noqa: E402
from .metrics import MetricsMiddleware, metrics_response  # noqa: E402
from .rate_limit import RateLimitMiddleware, get_rate_limit_config  # noqa: E402
from .response_metrics import ResponseMetricsMiddleware, metrics_store  # noqa: E402
from .routers import (  # noqa: E402
    auth,
    briefing,
    calendar,
    chat,
    conflicts,
    connections,
    feedback,
    focus,
    gmail,
    proactive,
    settings,
    staleness,
    sweep,
    thing_types,
    things,
    think,
)
from .sentry import set_sentry_user  # noqa: E402
from .sweep_scheduler import start_scheduler, stop_scheduler  # noqa: E402
from .tracing import init_tracing, shutdown_tracing  # noqa: E402

_FRONTEND_DIST = pathlib.Path(__file__).parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_tracing()
    init_db()
    clean_orphan_relationships()
    start_scheduler()
    async with httpx.AsyncClient(timeout=15.0) as client:
        app.state.httpx_client = client
        yield
    stop_scheduler()
    shutdown_tracing()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add standard security headers to every response."""

    async def dispatch(  # type: ignore[override]
        self, request: Request, call_next: Callable[[Request], Awaitable[StarletteResponse]]
    ) -> StarletteResponse:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https://*.googleusercontent.com; "
            "connect-src 'self'; "
            "font-src 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


class SentryUserContextMiddleware(BaseHTTPMiddleware):
    """Set Sentry user context from JWT session cookie on each request."""

    async def dispatch(  # type: ignore[override]
        self, request: Request, call_next: Callable[[Request], Awaitable[StarletteResponse]]
    ) -> StarletteResponse:
        token = request.cookies.get(COOKIE_NAME)
        if token and SECRET_KEY:
            try:
                import jwt as pyjwt

                payload = pyjwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
                set_sentry_user(payload.get("sub", ""), payload.get("email"))
            except Exception:
                pass  # Don't block requests if JWT decode fails
        return await call_next(request)


_TAG_METADATA = [
    {
        "name": "auth",
        "description": "Google OAuth2 login, JWT session management, and user profile.",
    },
    {
        "name": "things",
        "description": "CRUD operations for Things — the universal data model (tasks, notes, projects, ideas, goals).",
    },
    {
        "name": "thing-types",
        "description": "Manage custom Thing Types with icons and colors.",
    },
    {
        "name": "chat",
        "description": "Multi-agent chat pipeline and chat history management.",
    },
    {
        "name": "briefing",
        "description": "Daily briefing: checkin-due Things and sweep findings.",
    },
    {
        "name": "gmail",
        "description": "Gmail read-only integration: OAuth2 connection and message access.",
    },
    {
        "name": "calendar",
        "description": "Google Calendar read-only integration: OAuth2 connection and upcoming events.",
    },
    {
        "name": "proactive",
        "description": "Proactive surfaces — Things with upcoming time-relevant dates.",
    },
    {
        "name": "settings",
        "description": "Application settings: LLM model configuration via Requesty.",
    },
    {
        "name": "sweep",
        "description": "Nightly sweep: SQL candidate collection and LLM-powered reflection.",
    },
    {
        "name": "focus",
        "description": "Focus recommendations: prioritized Things with reasoning explanations.",
    },
    {
        "name": "connections",
        "description": "Auto-connect: suggested relationships between semantically similar Things.",
    },
    {
        "name": "staleness",
        "description": "Staleness & neglect detection: batch summary of stale and neglected items.",
    },
    {
        "name": "feedback",
        "description": "User feedback submission via GitHub Issues.",
    },
    {
        "name": "think",
        "description": "Reasoning-as-a-service: analyze natural language and return structured instructions.",
    },
    {
        "name": "health",
        "description": "Health check endpoint.",
    },
]

app = FastAPI(
    title="Reli API",
    description=(
        "Reli is a conversation-driven personal information manager. "
        "All data is stored locally in SQLite. "
        "The Universal Thing model represents tasks, notes, projects, ideas, and goals.\n\n"
        "## Authentication\n\n"
        "Most endpoints require a valid JWT session cookie (`reli_session`). "
        "Obtain one by completing the Google OAuth2 flow via `/api/auth/google`."
    ),
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=_TAG_METADATA,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SecurityHeadersMiddleware)
_rl_config = get_rate_limit_config()
app.add_middleware(RateLimitMiddleware, **_rl_config)
app.add_middleware(ResponseMetricsMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(SentryUserContextMiddleware)

# Auth routes are public (login/callback/logout)
app.include_router(auth.router, prefix="/api")

# All other /api routes require a valid JWT session
_api_deps = [Depends(require_user)]

app.include_router(things.router, prefix="/api", dependencies=_api_deps)
app.include_router(thing_types.router, prefix="/api", dependencies=_api_deps)
app.include_router(briefing.router, prefix="/api", dependencies=_api_deps)
app.include_router(chat.router, prefix="/api", dependencies=_api_deps)
app.include_router(gmail.router, prefix="/api", dependencies=_api_deps)
app.include_router(calendar.router, prefix="/api", dependencies=_api_deps)
app.include_router(proactive.router, prefix="/api", dependencies=_api_deps)
app.include_router(conflicts.router, prefix="/api", dependencies=_api_deps)
app.include_router(settings.router, prefix="/api", dependencies=_api_deps)
app.include_router(sweep.router, prefix="/api", dependencies=_api_deps)
app.include_router(focus.router, prefix="/api", dependencies=_api_deps)
app.include_router(staleness.router, prefix="/api", dependencies=_api_deps)
app.include_router(feedback.router, prefix="/api", dependencies=_api_deps)
app.include_router(connections.router, prefix="/api", dependencies=_api_deps)
app.include_router(think.router, prefix="/api", dependencies=_api_deps)


@app.get("/healthz", tags=["health"], summary="Health check", description="Returns service health status.")
def health() -> dict[str, str]:
    """Returns service health status."""
    return {"status": "ok", "service": "reli"}


@app.get("/api/health", tags=["health"])
def health_detailed() -> dict:
    """Detailed health check with DB, ChromaDB, and performance metrics."""
    from .database import get_connection
    from .vector_store import vector_count

    # DB status
    db_ok = False
    try:
        conn = get_connection()
        conn.execute("SELECT 1")
        conn.close()
        db_ok = True
    except Exception:
        pass

    # ChromaDB status
    chroma_ok = False
    vec_count = 0
    try:
        vec_count = vector_count()
        chroma_ok = True
    except Exception:
        pass

    avg_ms = metrics_store.avg_response_time_ms()

    return {
        "status": "ok" if db_ok else "degraded",
        "service": "reli",
        "uptime_seconds": round(metrics_store.uptime_seconds(), 1),
        "db_connected": db_ok,
        "chromadb_connected": chroma_ok,
        "vector_count": vec_count,
        "avg_response_time_ms": round(avg_ms, 2) if avg_ms is not None else None,
        "recent_request_count": metrics_store.request_count(),
    }


@app.get("/metrics", tags=["monitoring"], include_in_schema=False)
def metrics() -> StarletteResponse:
    return metrics_response()


# MCP server — Streamable HTTP transport, mounted at /mcp
# Protected by MCP_API_TOKEN bearer token (empty = dev/open mode)
app.mount("/mcp", create_mcp_asgi_app(_app_settings.MCP_API_TOKEN))

# Serve React SPA (only when the built dist directory exists)
if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    _RESOLVED_DIST = _FRONTEND_DIST.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        if full_path:
            # Reject null bytes and absolute paths (pathlib treats /foo as root)
            if "\x00" in full_path or full_path.startswith("/"):
                return FileResponse(_RESOLVED_DIST / "index.html")
            # Strip path traversal segments before joining
            clean = pathlib.PurePosixPath(full_path)
            if ".." in clean.parts:
                return FileResponse(_RESOLVED_DIST / "index.html")
            static_file = (_RESOLVED_DIST / full_path).resolve()
            if static_file.is_relative_to(_RESOLVED_DIST) and static_file.is_file():
                return FileResponse(static_file)
        return FileResponse(_RESOLVED_DIST / "index.html")
