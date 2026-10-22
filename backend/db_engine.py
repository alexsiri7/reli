"""SQLModel engine and session management.

The connection string comes from ``settings.database_url`` and must be Postgres. Nothing here reads
configuration at import time — ``get_engine`` resolves it on first use — so importing this module
(or ``backend.main``) never depends on the environment being set up yet.

Every connection the engine opens carries a ``statement_timeout``, so no statement — however the
graph is shaped — can hold one of the pool's connections indefinitely.

An unhandled database error is re-raised to the log and Sentry, so the exceptions an engine raises
must not carry a Thing's title, notes or URLs or a journal entry's before/after snapshots (#1694).
``hide_parameters`` keeps SQLAlchemy from appending the bound parameters, and
``redact_statement_errors`` cuts what remains of the server's text, which quotes them.

The connection must be encrypted (#1695): prod reaches the Supabase pooler over the public internet,
and libpq's default ``prefer`` accepts a server that declines TLS. ``tls_connect_args`` holds the
rule for this engine and the migrations' alike.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, event, make_url
from sqlalchemy.engine import ExceptionContext
from sqlmodel import Session, create_engine

from .config import settings

_engine: Engine | None = None

# The backstop for the reads that take no ``limit`` (``queries.due_for_checkin``, ``stale``,
# ``blocked``, ``relationships_for``) and for everything else: Postgres cancels a statement that runs
# past this, so a request fails instead of pinning one of the five pooled connections. Every query
# is an indexed read on one person's graph and finishes in milliseconds, so this is more than an
# order of magnitude above anything legitimate. Migrations are not under it: prod also sets this
# timeout as the ``reli`` role's default, because its pooler drops connect-time options, and
# ``alembic/env.py`` sets ``statement_timeout = 0`` for the migration transaction so a long
# ``alembic upgrade head`` cannot be killed by it (#1535, #1572).
STATEMENT_TIMEOUT = "30s"

# The libpq modes that refuse a server which declines TLS. ``verify-full`` with a bundled Supabase CA
# is the owner's call (#1695); until then ``require`` is what a URL without a mode gets.
TLS_SSLMODES = frozenset({"require", "verify-ca", "verify-full"})


def tls_connect_args(database_url: str) -> dict[str, str]:
    """The ``connect_args`` that make a connection to ``database_url`` require TLS.

    A URL naming no ``sslmode`` gets ``require``; one naming a mode from ``TLS_SSLMODES`` keeps it.
    A weaker mode is honoured only outside a deploy — the ``localdb`` Postgres speaks no TLS, which
    is why its URL says ``sslmode=disable`` — and on a deploy it raises, so the boot fails rather
    than talking to the database in the clear.
    """
    sslmode = make_url(database_url).query.get("sslmode")
    if sslmode is None:
        return {"sslmode": "require"}
    if sslmode not in TLS_SSLMODES and settings.production:
        raise RuntimeError(
            f"DATABASE_URL sets sslmode={sslmode}, which allows an unencrypted connection. A deploy "
            f"requires one of {', '.join(sorted(TLS_SSLMODES))}; drop the parameter to get require."
        )
    return {}


def get_engine() -> Engine:
    """Return the process-wide engine, creating it on first call."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            echo=False,
            hide_parameters=True,
            pool_size=3,
            max_overflow=2,
            pool_pre_ping=True,
            connect_args={
                "options": f"-c statement_timeout={STATEMENT_TIMEOUT}",
                **tls_connect_args(settings.database_url),
            },
        )
        redact_statement_errors(_engine)
    return _engine


def _keep_the_first_line(context: ExceptionContext) -> None:
    for error in (context.original_exception, context.sqlalchemy_exception):
        if error is not None and len(error.args) == 1 and isinstance(error.args[0], str):
            error.args = (error.args[0].split("\n", 1)[0],)


def redact_statement_errors(engine: Engine) -> None:
    """Cut every database error the engine raises to its first line: the error class and message.

    psycopg2 interpolates the parameters client-side, so the lines Postgres adds beneath its message
    — the ``LINE`` excerpt, ``DETAIL`` and ``CONTEXT`` — quote the written Thing, and SQLAlchemy
    copies that text into the error it wraps the driver's in. The ``[SQL: …]`` block is added when
    the error is printed, so the statement survives the cut, and the engine's ``hide_parameters``
    decides whether the bound parameters are printed beneath it.
    """
    event.listen(engine, "handle_error", _keep_the_first_line)


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
