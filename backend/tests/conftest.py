"""Shared pytest fixtures for backend tests.

The schema is Postgres-specific — JSONB, a GIN index, native enums and a PL/pgSQL trigger — so the
tests run against a real Postgres brought up by testcontainers, migrated with ``alembic upgrade
head`` rather than ``SQLModel.metadata.create_all``. That is what makes the migration itself, and
not just the ORM models, the thing under test.

Set ``RELI_TEST_DATABASE_URL`` to run against an existing database instead of starting a container.
"""

import os
from collections.abc import Generator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

# Keep test failures out of the production Sentry project.
os.environ.setdefault("SENTRY_DSN", "")


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """A Postgres to test against: the one named in the environment, or a throwaway container."""
    configured = os.environ.get("RELI_TEST_DATABASE_URL")
    if configured:
        yield configured
        return

    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="psycopg2") as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def migrated_db(postgres_url: str) -> Iterator[str]:
    """Point the app at the test database and bring it to head."""
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    from backend import config as config_module
    from backend import db_engine

    # Mutate the settings singleton rather than rebinding it: backend.db_engine and
    # backend/alembic/env.py hold a reference to this object, taken at import time.
    os.environ["DATABASE_URL"] = postgres_url
    config_module.settings.DATABASE_URL = postgres_url
    db_engine.reset_engine()

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    alembic_command.upgrade(AlembicConfig(os.path.join(repo_root, "alembic.ini")), "head")

    yield postgres_url

    db_engine.reset_engine()


@pytest.fixture()
def session(migrated_db: str) -> Generator[Session, None, None]:
    """A session against the migrated database, left empty of Things for the next test.

    Teardown deletes Things and relationships without journalling, which no application code path
    may do — it is fixture teardown, which is why ``test_architecture.py`` excludes this directory.
    The ``journal`` rows stay: the append-only trigger refuses to delete them, and every journal
    assertion is written as a delta so accumulated entries are harmless.
    """
    from backend.db_engine import get_engine

    with Session(get_engine()) as db_session:
        yield db_session

    with Session(get_engine()) as cleanup:
        cleanup.execute(text("DELETE FROM relationships"))
        cleanup.execute(text("DELETE FROM things"))
        cleanup.commit()


@pytest.fixture(scope="session")
def client(migrated_db: str) -> Iterator[TestClient]:
    """The app with its real lifespan, entered once for the whole session.

    Session scope is not negotiable: the lifespan starts the MCP session manager, which the SDK
    allows to run only once per ``FastMCP`` instance, and ``backend.main`` builds exactly one at
    import. A second ``TestClient(app)`` raises in lifespan and takes every later test with it.
    """
    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client
