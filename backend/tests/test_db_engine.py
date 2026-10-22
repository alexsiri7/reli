"""The engine every request runs on: what a session carries into Postgres (#1535) and what its errors
carry out (#1694).

The setting being present on the session is the fact this repository can prove; Postgres enforcing
it is Postgres's contract, so there is no ``pg_sleep`` here.
"""

import traceback

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


def test_a_database_error_does_not_carry_the_bound_parameters(session):
    """An unhandled database error is re-raised to the log, so its traceback must not hold Thing content (#1694).

    The URLs bind after the notes, so they sit outside the server's ``LINE`` excerpt: the bound
    parameters are the only place the formatted error could have carried them.
    """
    logged = "".join(traceback.format_exception(_failed_create(session)))
    assert "SQL parameters hidden" in logged
    assert "private.example" not in logged
