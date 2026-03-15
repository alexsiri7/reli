"""Reli FastAPI application entry point."""

import pathlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from .auth import API_KEY, require_api_key  # noqa: E402
from .database import init_db  # noqa: E402
from .routers import briefing, calendar, chat, gmail, proactive, sweep, thing_types, things  # noqa: E402
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

# All /api routes require a valid API key
_api_deps = [Depends(require_api_key)]

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

    _INDEX_HTML: str | None = None

    def _get_index_html() -> str:
        """Read index.html and inject the API key as a window global."""
        global _INDEX_HTML  # noqa: PLW0603
        if _INDEX_HTML is None:
            raw = (_FRONTEND_DIST / "index.html").read_text()
            inject = f'<script>window.__RELI_API_KEY__="{API_KEY}";</script>'
            _INDEX_HTML = raw.replace("</head>", f"{inject}</head>", 1)
        return _INDEX_HTML

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse | HTMLResponse:
        # Resolve to prevent directory traversal (e.g. ../../etc/passwd)
        if full_path:
            static_file = (_FRONTEND_DIST / full_path).resolve()
            if static_file.is_relative_to(_FRONTEND_DIST.resolve()) and static_file.is_file():
                return FileResponse(static_file)
        return HTMLResponse(_get_index_html())
