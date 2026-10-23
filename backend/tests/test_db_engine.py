"""The engine every request runs on: what a session carries into Postgres (#1535), what its errors
carry out (#1694) and that it reaches Postgres only over TLS (#1695).

The setting being present on the session is the fact this repository can prove; Postgres enforcing
it is Postgres's contract, so there is no ``pg_sleep`` here.
"""

import logging
import re
from pathlib import Path

import pytest
import yaml
from sqlalchemy import make_url, text
from sqlalchemy.exc import DataError, OperationalError

from backend import db_engine, service
from backend.config import settings
from backend.db_engine import STATEMENT_TIMEOUT, open_session, tls_connect_args
from backend.db_models import Actor


def test_every_session_runs_under_the_statement_timeout(migrated_db):
    with open_session() as session:
        assert session.connection().execute(text("SHOW statement_timeout")).scalar_one() == STATEMENT_TIMEOUT


def test_a_url_without_an_sslmode_will_not_connect_to_a_server_without_tls(migrated_db, monkeypatch):
    """The test Postgres speaks no TLS, so the engine's connection is refused rather than sent in the clear."""
    url = make_url(migrated_db)
    monkeypatch.setattr(settings, "DATABASE_URL", url.set(query={}).render_as_string(hide_password=False))
    db_engine.reset_engine()
    try:
        with pytest.raises(OperationalError, match="SSL"), open_session() as session:
            session.connection()
    finally:
        db_engine.reset_engine()


@pytest.mark.parametrize("sslmode", ["require", "verify-ca", "verify-full"])
def test_a_url_naming_a_tls_mode_keeps_it_on_a_deploy(sslmode, monkeypatch):
    monkeypatch.setattr(settings, "PRODUCTION", "1")
    assert tls_connect_args(f"postgresql://reli@db/reli?sslmode={sslmode}") == {}


def test_a_url_naming_no_mode_requires_tls():
    assert tls_connect_args("postgresql://reli@db/reli") == {"sslmode": "require"}


@pytest.mark.parametrize("sslmode", ["disable", "allow", "prefer"])
def test_a_deploy_refuses_a_mode_that_allows_an_unencrypted_connection(sslmode, monkeypatch):
    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT_NAME", "production")
    with pytest.raises(RuntimeError, match=f"sslmode={sslmode}"):
        tls_connect_args(f"postgresql://reli@db/reli?sslmode={sslmode}")


def test_a_local_run_keeps_the_localdb_profiles_disable(monkeypatch):
    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT_NAME", "")
    monkeypatch.setattr(settings, "PRODUCTION", "")
    assert tls_connect_args("postgresql://reli:reli@localhost:5432/reli?sslmode=disable") == {}


def test_the_self_hosted_compose_service_is_a_deploy():
    """``docker compose up -d`` runs the ``reli`` service with no Railway variable, so only the
    ``PRODUCTION`` default it carries makes that container a deploy that refuses ``sslmode=disable``."""
    compose = yaml.safe_load((Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text())
    defaults = [
        match.group(1)
        for entry in compose["services"]["reli"]["environment"]
        if (match := re.fullmatch(r"PRODUCTION=\$\{PRODUCTION:-(.*)\}", entry))
    ]
    assert len(defaults) == 1 and defaults[0], "the reli service must default PRODUCTION when the host leaves it unset"


def test_the_staging_compose_service_hides_the_docs_but_is_no_deploy():
    """#1720: ``reli-staging`` hides its API docs, but its ``postgres-staging`` speaks no TLS, so the
    container must not be a deploy that refuses ``sslmode=disable``."""
    compose = yaml.safe_load((Path(__file__).resolve().parents[2] / "docker-compose.staging.yml").read_text())
    environment = compose["services"]["reli-staging"]["environment"]
    assert "HIDE_API_DOCS=1" in environment
    assert not [entry for entry in environment if entry.startswith(("PRODUCTION=", "RAILWAY_ENVIRONMENT_NAME="))]


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
