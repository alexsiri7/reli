"""Shared pytest fixtures for backend tests.

The schema is Postgres-specific — JSONB, a GIN index, native enums and a PL/pgSQL trigger — so the
tests run against a real Postgres brought up by testcontainers, migrated with ``alembic upgrade
head`` rather than ``SQLModel.metadata.create_all``. That is what makes the migration itself, and
not just the ORM models, the thing under test.

Set ``RELI_TEST_DATABASE_URL`` to run against an existing database instead of starting a container.
"""

import json
import os
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

GOOGLE_FIXTURES = Path(__file__).parent / "fixtures" / "google"

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
        # The OAuth stores purge only expired rows, and mcp_registered_clients caps at 100 live
        # ones: left in place, registrations from earlier tests would turn into 503s mid-suite.
        for table in ("mcp_refresh_tokens", "mcp_auth_codes", "mcp_oauth_sessions", "mcp_registered_clients"):
            cleanup.execute(text(f"DELETE FROM {table}"))
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


@pytest.fixture()
def tools(session, monkeypatch):
    """Bind every MCP tool to the fixture session for the duration of one test.

    ``@reli_mcp.tool()`` returns the function unchanged, so the tools are called directly; with
    ``_session`` bound here, a tool's write and the assertion about it share one transaction.
    """
    from backend import mcp_server

    @contextmanager
    def _fixture_session():
        yield session

    monkeypatch.setattr(mcp_server, "_session", _fixture_session)
    return session


def _google_fixture(name):
    return json.loads((GOOGLE_FIXTURES / f"{name}.json").read_text())


@pytest.fixture()
def configured(monkeypatch):
    """A Google credential in settings, and no access token left over from another test."""
    from backend import google_client
    from backend.config import settings

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(settings, "GOOGLE_REFRESH_TOKEN", "refresh-token")
    google_client.reset_token_cache()
    yield
    google_client.reset_token_cache()


@pytest.fixture()
def google(configured, monkeypatch):
    """A read-only Google serving the recorded fixtures: the handler fails the test if anything
    but a GET reaches an API. ``responses`` overrides a source's listing; ``fixture`` loads one."""
    from backend import google_client
    from backend.google_client import TOKEN_URL

    seen: list[httpx.Request] = []
    responses: dict[str, object] = {}

    def handler(request):
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "access-token", "expires_in": 3600})

        assert request.method == "GET", f"{request.method} {request.url} is not a read"
        seen.append(request)

        path = request.url.path
        if path.startswith("/gmail/v1/users/me/messages/"):
            message_id = path.rsplit("/", 1)[-1]
            for message in _google_fixture("messages_metadata"):
                if message["id"] == message_id:
                    return httpx.Response(200, json=message)
            stub = dict(_google_fixture("messages_metadata")[0])
            stub["id"] = message_id
            return httpx.Response(200, json=stub)
        if path == "/gmail/v1/users/me/messages":
            return httpx.Response(200, json=responses.get("messages", _google_fixture("messages_list")))
        if path.startswith("/calendar/v3/calendars/primary/events"):
            return httpx.Response(200, json=responses.get("events", _google_fixture("events_list")))
        raise AssertionError(f"unexpected URL {request.url}")

    monkeypatch.setattr(google_client, "_http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return type("Google", (), {"seen": seen, "responses": responses, "fixture": staticmethod(_google_fixture)})()
