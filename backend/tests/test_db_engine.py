"""The engine every request runs on: what a session carries into Postgres (#1535).

The setting being present on the session is the fact this repository can prove; Postgres enforcing
it is Postgres's contract, so there is no ``pg_sleep`` here.
"""

from sqlalchemy import text

from backend.db_engine import STATEMENT_TIMEOUT, open_session


def test_every_session_runs_under_the_statement_timeout(migrated_db):
    with open_session() as session:
        assert session.connection().execute(text("SHOW statement_timeout")).scalar_one() == STATEMENT_TIMEOUT
