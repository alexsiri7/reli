"""Reli FastAPI application entry point."""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .routers import briefing, chat, things


@asynccontextmanager
async def lifespan(app: FastAPI):
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

app.include_router(things.router)
app.include_router(briefing.router)
app.include_router(chat.router)


@app.get("/", tags=["health"])
def health():
    return {"status": "ok", "service": "reli"}
