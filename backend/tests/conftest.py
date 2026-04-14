"""Shared pytest fixtures for backend tests."""

import os
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

# Disable rate limiting for all tests (except test_rate_limit.py which uses its own app)
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

# Prevent test errors from polluting production Sentry (re-icdi)
os.environ.setdefault("SENTRY_DSN", "")

# Force auth to disabled in tests: prevent production .env credentials from
# being loaded by pydantic-settings when tests run from the rig directory.
# test_auth.py patches backend.auth.SECRET_KEY directly for auth-enabled tests.
os.environ["SECRET_KEY"] = ""
os.environ["RELI_API_TOKEN"] = ""
os.environ.setdefault("AUTH_DISABLED", "true")

# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db_path(tmp_path: Path) -> Path:
    """Return a path to a fresh temporary SQLite database."""
    return tmp_path / "test_reli.db"


@pytest.fixture()
def patched_db(tmp_db_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Patch both legacy and ORM database modules to use a temp SQLite file.

    Creates tables via ``SQLModel.metadata.create_all()`` (Alembic is not
    used in tests).  The legacy ``database.db()`` context manager is patched
    so test files that still use raw ``sqlite3`` connections hit the same DB.
    """
    import backend.database as db_module
    import backend.db_engine as engine_module
    from sqlmodel import SQLModel, Session, create_engine

    # Point the legacy raw-sqlite helpers at the temp DB
    monkeypatch.setattr(db_module, "DB_PATH", tmp_db_path)

    # Create a SQLModel engine for the temp DB
    test_engine = create_engine(
        f"sqlite:///{tmp_db_path}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(test_engine)

    # Seed default thing types (replaces legacy _seed_thing_types from init_db)
    from backend.db_models import ThingTypeRecord

    _DEFAULT_THING_TYPES = [
        ("task", "\U0001f4cb"),
        ("note", "\U0001f4dd"),
        ("project", "\U0001f4c1"),
        ("idea", "\U0001f4a1"),
        ("goal", "\U0001f3af"),
        ("journal", "\U0001f4d3"),
        ("person", "\U0001f464"),
        ("place", "\U0001f4cd"),
        ("event", "\U0001f4c5"),
        ("concept", "\U0001f9e0"),
        ("reference", "\U0001f517"),
        ("preference", "\u2699\ufe0f"),
    ]
    with Session(test_engine) as session:
        for name, icon in _DEFAULT_THING_TYPES:
            session.add(ThingTypeRecord(id=name, name=name, icon=icon))
        session.commit()

    monkeypatch.setattr(engine_module, "engine", test_engine)

    # Override get_session to use the test engine
    def _test_get_session():
        with Session(test_engine) as session:
            yield session

    monkeypatch.setattr(engine_module, "get_session", _test_get_session)

    yield tmp_db_path

    # Dispose the test engine to release all connections
    test_engine.dispose()


# ---------------------------------------------------------------------------
# Vector store mock
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_vector_store():
    """Mock vector store to avoid requiring a real pgvector/Postgres instance.

    Patches both the source module and the imported symbols in each router,
    since background tasks hold references to the imported names.
    """
    with (
        patch("backend.vector_store.upsert_thing", return_value=None),
        patch("backend.vector_store.delete_thing", return_value=None),
        patch("backend.vector_store.vector_count", return_value=0),
        patch("backend.vector_store.vector_search", return_value=[]),
        patch("backend.routers.auth.upsert_thing", return_value=None),
        patch("backend.routers.things.upsert_thing", return_value=None) as mock_upsert,
        patch("backend.routers.things.vs_delete", return_value=None) as mock_delete,
        patch("backend.pipeline.vector_count", return_value=0) as mock_count,
        patch("backend.pipeline.vector_search", return_value=[]) as mock_search,
    ):
        yield {
            "upsert": mock_upsert,
            "delete": mock_delete,
            "count": mock_count,
            "search": mock_search,
        }


# ---------------------------------------------------------------------------
# FastAPI test clients
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(patched_db) -> Generator[TestClient, None, None]:
    """Synchronous TestClient with temp DB and mocked vector store.

    Auth is bypassed because SECRET_KEY is empty in tests, so require_user()
    returns '' (unauthenticated passthrough for local dev).
    """
    from backend.main import app

    with TestClient(app) as c:
        yield c


@pytest_asyncio.fixture()
async def async_client(patched_db) -> AsyncClient:
    """Async HTTPX client for async endpoint tests."""
    from backend.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
