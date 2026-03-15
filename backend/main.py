"""Reli FastAPI application entry point."""

import logging
import os
import pathlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

# Configure logging — LOG_LEVEL env var controls verbosity (default: INFO)
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from .auth import require_user  # noqa: E402
from .database import init_db  # noqa: E402
from .rate_limit import RateLimitMiddleware, get_rate_limit_config  # noqa: E402
from .routers import auth, briefing, calendar, chat, gmail, proactive, sweep, thing_types, things  # noqa: E402
from .sweep_scheduler import start_scheduler, stop_scheduler  # noqa: E402

_FRONTEND_DIST = pathlib.Path(__file__).parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="Reli API",
    description=(
        "Reli is a conversation-driven personal information manager. "
        "All data is stored locally in SQLite. "
        "The Universal Thing model represents tasks, notes, projects, ideas, and goals."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_rl_config = get_rate_limit_config()
app.add_middleware(RateLimitMiddleware, **_rl_config)

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
app.include_router(sweep.router, prefix="/api", dependencies=_api_deps)


@app.get("/healthz", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "reli"}


# Serve React SPA (only when the built dist directory exists)
if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        # Resolve to prevent directory traversal (e.g. ../../etc/passwd)
        if full_path:
            static_file = (_FRONTEND_DIST / full_path).resolve()
            if static_file.is_relative_to(_FRONTEND_DIST.resolve()) and static_file.is_file():
                return FileResponse(static_file)
        return FileResponse(_FRONTEND_DIST / "index.html")
