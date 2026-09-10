"""SQLModel engine and session management.

The connection string comes from ``settings.database_url`` and must be Postgres. Nothing here reads
configuration at import time — ``get_engine`` resolves it on first use — so importing this module
(or ``backend.main``) never depends on the environment being set up yet.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine
from sqlmodel import Session, create_engine

from .config import settings

_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the process-wide engine, creating it on first call."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            echo=False,
            pool_size=3,
            max_overflow=2,
            pool_pre_ping=True,
        )
    return _engine


def reset_engine() -> None:
    """Drop the cached engine so the next ``get_engine`` re-reads the configured URL."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def get_session() -> Generator[Session, None, None]:
    """Yield a SQLModel session. Use as a FastAPI ``Depends()`` or context manager."""
    with Session(get_engine()) as session:
        yield session
