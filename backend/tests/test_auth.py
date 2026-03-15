"""Tests for API key authentication."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def unauthed_client(patched_db):
    """TestClient WITHOUT the API key header."""
    from backend.main import app

    with TestClient(app) as c:
        yield c


class TestAuth:
    def test_api_rejects_missing_key(self, unauthed_client):
        resp = unauthed_client.get("/api/things")
        assert resp.status_code == 401
        assert "API key" in resp.json()["detail"]

    def test_api_rejects_wrong_key(self, unauthed_client):
        resp = unauthed_client.get("/api/things", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401

    def test_api_accepts_valid_key(self, client):
        resp = client.get("/api/things")
        assert resp.status_code == 200

    def test_healthz_no_key_required(self, unauthed_client):
        resp = unauthed_client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
