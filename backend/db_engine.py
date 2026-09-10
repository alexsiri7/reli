"""SQLModel engine and session management.

The connection string comes from ``settings.database_url`` and must be Postgres. Nothing here reads
configuration at import time — ``get_engine`` resolves it on first use — so importing this module
(or ``backend.main``) never depends on the environment being set up yet.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Generator
from datetime import date, datetime
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, create_engine

from .config import settings


def _json_default(obj: Any) -> Any:
    """Serialize the types the journal's ``before``/``after`` snapshots carry but ``json`` cannot."""
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def json_serializer(value: Any) -> str:
    """Drop-in replacement for ``json.dumps`` used by SQLAlchemy engines."""
    return json.dumps(value, default=_json_default)


_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the process-wide engine, creating it on first call."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            echo=False,
            json_serializer=json_serializer,
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
