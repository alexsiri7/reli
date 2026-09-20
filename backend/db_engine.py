"""SQLModel engine and session management.

The connection string comes from ``settings.database_url`` and must be Postgres. Nothing here reads
configuration at import time — ``get_engine`` resolves it on first use — so importing this module
(or ``backend.main``) never depends on the environment being set up yet.

Every connection the engine opens carries a ``statement_timeout``, so no statement — however the
graph is shaped — can hold one of the pool's connections indefinitely.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlmodel import Session, create_engine

from .config import settings

_engine: Engine | None = None

# The backstop for the reads that take no ``limit`` (``queries.due_for_checkin``, ``stale``,
# ``blocked``, ``relationships_for``) and for everything else: Postgres cancels a statement that runs
# past this, so a request fails instead of pinning one of the five pooled connections. Every query
# is an indexed read on one person's graph and finishes in milliseconds, so this is more than an
# order of magnitude above anything legitimate. Migrations are not under it — ``alembic/env.py``
# builds its own engine — so a long ``alembic upgrade head`` cannot be killed by it (#1535).
STATEMENT_TIMEOUT = "30s"


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
            connect_args={"options": f"-c statement_timeout={STATEMENT_TIMEOUT}"},
        )
    return _engine


def reset_engine() -> None:
    """Drop the cached engine so the next ``get_engine`` re-reads the configured URL."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


@contextmanager
def open_session() -> Iterator[Session]:
    """The session a request runs in.

    Each module binds it as ``_session`` so tests can patch that seam per module.
    """
    with Session(get_engine()) as session:
        yield session
