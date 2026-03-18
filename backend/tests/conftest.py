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

# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db_path(tmp_path: Path) -> Path:
    """Return a path to a fresh temporary SQLite database."""
    return tmp_path / "test_reli.db"


@pytest.fixture()
def patched_db(tmp_db_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Patch the database module to use a temp SQLite file."""
    import backend.database as db_module

    monkeypatch.setattr(db_module, "DB_PATH", tmp_db_path)
    db_module.init_db()
    return tmp_db_path


# ---------------------------------------------------------------------------
# Vector store mock
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_vector_store():
    """Mock ChromaDB / vector store to avoid requiring a real Chroma instance.

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
