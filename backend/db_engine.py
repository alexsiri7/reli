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
and libpq's default ``prefer`` accepts a server that declines TLS. A deploy also verifies who the
server is (#1816): ``require`` would hand the ``reli`` role's password to anything between Railway
and the pooler that presents a certificate. ``tls_connect_args`` holds the rule for this engine and
the migrations' alike.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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

# The root the production pooler's chain ends in (Supabase Root 2021 CA), valid until 2031-04-26.
# When Supabase rotates it, replace the file with the one the Supabase dashboard serves under
# Database settings → SSL configuration.
_SUPABASE_ROOT_CA_IN_BACKEND = "certs/supabase-root-2021-ca.crt"
SUPABASE_ROOT_CA = Path(__file__).resolve().parent / _SUPABASE_ROOT_CA_IN_BACKEND


def tls_connect_args(database_url: str) -> dict[str, str]:
    """The ``connect_args`` that make a connection to ``database_url`` require TLS.

    On a deploy the connection is ``verify-full`` against ``SUPABASE_ROOT_CA`` (#1816): a URL may
    name no ``sslmode`` or ``verify-full``, any other mode raises so the boot fails, and an
    ``sslrootcert`` in the URL is overridden, because ``connect_args`` win over the URL's query.

    Outside a deploy a URL naming no ``sslmode`` gets ``require`` and one naming a mode keeps it —
    the ``localdb`` Postgres speaks no TLS, which is why its URL says ``sslmode=disable``.
    """
    sslmode = make_url(database_url).query.get("sslmode")
    if settings.production:
        if sslmode not in (None, "verify-full"):
            raise RuntimeError(
                f"DATABASE_URL sets sslmode={sslmode}. A deploy connects with sslmode=verify-full against "
                f"the bundled Supabase root CA (#1816); drop the parameter."
            )
        return {"sslmode": "verify-full", "sslrootcert": str(SUPABASE_ROOT_CA)}
    if sslmode is None:
        return {"sslmode": "require"}
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


# libpq's wording, on libpq 17, for a chain that does not end in the root, a certificate that does not
# name the host, and a root file that is missing.
_CERTIFICATE_FAILURES = ("certificate verify failed", "does not match host name", "root certificate file")

CERTIFICATE_FAILURE = (
    "The database server's TLS certificate did not verify against the Supabase root CA bundled at "
    f"backend/{_SUPABASE_ROOT_CA_IN_BACKEND} (sslmode=verify-full, #1816). If Supabase has rotated "
    "its CA, replace that file with the certificate from the Supabase dashboard (Database settings → "
    "SSL configuration). libpq said: "
)


def _rewrite_the_message(context: ExceptionContext) -> None:
    for error in (context.original_exception, context.sqlalchemy_exception):
        if error is not None and len(error.args) == 1 and isinstance(error.args[0], str):
            first_line = error.args[0].split("\n", 1)[0]
            if any(marker in first_line for marker in _CERTIFICATE_FAILURES):
                first_line = CERTIFICATE_FAILURE + first_line
            error.args = (first_line,)


def redact_statement_errors(engine: Engine) -> None:
    """Cut every database error the engine raises to its first line: the error class and message.

    psycopg2 interpolates the parameters client-side, so the lines Postgres adds beneath its message
    — the ``LINE`` excerpt, ``DETAIL`` and ``CONTEXT`` — quote the written Thing, and SQLAlchemy
    copies that text into the error it wraps the driver's in. The ``[SQL: …]`` block is added when
    the error is printed, so the statement survives the cut, and the engine's ``hide_parameters``
    decides whether the bound parameters are printed beneath it.

    A connection refused because the server's certificate did not verify is prefixed with a sentence
    naming the bundled CA, so a stale certificate reads as one at boot.
    """
    event.listen(engine, "handle_error", _rewrite_the_message)


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
