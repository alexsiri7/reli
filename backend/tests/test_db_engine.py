"""The engine every request runs on: what a session carries into Postgres (#1535), what its errors
carry out (#1694), that it reaches Postgres only over TLS (#1695) and that a deploy verifies the
server against the bundled Supabase root CA (#1816).

The setting being present on the session is the fact this repository can prove; Postgres enforcing
it is Postgres's contract, so there is no ``pg_sleep`` here.
"""

import logging
import re
import ssl
from pathlib import Path

import psycopg2
import pytest
import yaml
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import DataError, OperationalError
from sqlalchemy.pool import NullPool

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


@pytest.mark.parametrize("url", ["postgresql://reli@db/reli", "postgresql://reli@db/reli?sslmode=verify-full"])
def test_a_deploy_verifies_the_server_against_the_bundled_supabase_ca(url, monkeypatch):
    monkeypatch.setattr(settings, "PRODUCTION", "1")
    assert tls_connect_args(url) == {"sslmode": "verify-full", "sslrootcert": str(db_engine.SUPABASE_ROOT_CA)}


def test_a_url_naming_no_mode_requires_tls(monkeypatch):
    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT_NAME", "")
    monkeypatch.setattr(settings, "PRODUCTION", "")
    assert tls_connect_args("postgresql://reli@db/reli") == {"sslmode": "require"}


@pytest.mark.parametrize("sslmode", ["disable", "allow", "prefer", "require", "verify-ca"])
def test_a_deploy_refuses_any_mode_short_of_verify_full(sslmode, monkeypatch):
    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT_NAME", "production")
    with pytest.raises(RuntimeError, match=f"sslmode={sslmode}"):
        tls_connect_args(f"postgresql://reli@db/reli?sslmode={sslmode}")


def test_the_bundled_ca_is_supabases_root():
    """A moved, renamed or corrupted file would fail every deploy's boot; this fails the build first."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(db_engine.SUPABASE_ROOT_CA))
    [certificate] = context.get_ca_certs()
    assert (("commonName", "Supabase Root 2021 CA"),) in certificate["subject"]


def test_a_certificate_failure_says_so_plainly():
    """The ``handle_error`` path the boot's connection takes when libpq refuses the server's chain."""

    def refused():
        raise psycopg2.OperationalError(
            'connection to server at "h" (1.2.3.4), port 5432 failed: SSL error: certificate verify failed\n'
        )

    engine = create_engine("postgresql+psycopg2://", creator=refused, poolclass=NullPool)
    db_engine.redact_statement_errors(engine)
    with pytest.raises(OperationalError, match="did not verify against the Supabase root CA") as failure:
        engine.connect()
    assert "certificate verify failed" in str(failure.value)


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
