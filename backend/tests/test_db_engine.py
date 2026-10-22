"""The engine every request runs on: what a session carries into Postgres (#1535) and what its errors
carry out (#1694).

The setting being present on the session is the fact this repository can prove; Postgres enforcing
it is Postgres's contract, so there is no ``pg_sleep`` here.
"""

import logging

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError

from backend import service
from backend.db_engine import STATEMENT_TIMEOUT, open_session
from backend.db_models import Actor


def test_every_session_runs_under_the_statement_timeout(migrated_db):
    with open_session() as session:
        assert session.connection().execute(text("SHOW statement_timeout")).scalar_one() == STATEMENT_TIMEOUT


def _failed_create(session) -> DataError:
    """A real write the database refuses: a NUL is valid JSON but not JSONB text, so the notes fail."""
    with pytest.raises(DataError) as failure:
        service.create_thing(
            session,
            actor=Actor.CLAUDE_INTERACTIVE,
            title="private title",
            notes={"note": "private note\x00"},
            urls={"link": "https://private.example/leak"},
        )
    session.rollback()
    return failure.value


def test_a_logged_database_error_does_not_carry_the_thing_it_was_writing(session, caplog):
    """An unhandled database error is re-raised to the log and Sentry, so it must name the error and
    nothing of the Thing (#1694).

    The note's NUL sits in the server's ``LINE`` excerpt and ``CONTEXT``, on the SQLAlchemy error and
    again on the psycopg2 error it wraps; the URLs bind after the notes, so only the bound parameters
    could have carried them.
    """
    logger = logging.getLogger("uvicorn.error")
    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        logger.error("Exception in ASGI application", exc_info=_failed_create(session))
    assert "unsupported Unicode escape sequence" in caplog.text
    assert "SQL parameters hidden" in caplog.text
    assert "private" not in caplog.text
