"""Reli FastAPI application entry point."""

import pathlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from .database import init_db  # noqa: E402
from .routers import briefing, calendar, chat, gmail, proactive, thing_types, things  # noqa: E402

_FRONTEND_DIST = pathlib.Path(__file__).parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


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

app.include_router(things.router, prefix="/api")
app.include_router(thing_types.router, prefix="/api")
app.include_router(briefing.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(gmail.router, prefix="/api")
app.include_router(calendar.router, prefix="/api")
app.include_router(proactive.router, prefix="/api")


@app.get("/healthz", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "reli"}


# Serve React SPA (only when the built dist directory exists)
if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        # Serve static files from dist root (favicon, icons, etc.)
        static_file = _FRONTEND_DIST / full_path
        if full_path and static_file.is_file():
            return FileResponse(static_file)
        return FileResponse(_FRONTEND_DIST / "index.html")
