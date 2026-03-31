"""Shared fixtures for E2E integration tests."""

import os

import httpx
import pytest


BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
API_TOKEN = os.environ.get("RELI_API_TOKEN", "e2e-test-token")


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL.rstrip("/")


@pytest.fixture(scope="session")
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


@pytest.fixture(scope="session")
def client(base_url: str, auth_headers: dict[str, str]) -> httpx.Client:
    """Pre-configured httpx client with auth and base URL."""
    with httpx.Client(
        base_url=base_url,
        headers=auth_headers,
        timeout=30.0,
    ) as c:
        yield c  # type: ignore[misc]
