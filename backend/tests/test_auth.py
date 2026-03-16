"""Tests for JWT session authentication."""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def authed_client(patched_db):
    """TestClient with SECRET_KEY set so auth is enforced."""
    with patch("backend.auth.SECRET_KEY", "test-secret-key"):
        from backend.main import app

        with TestClient(app) as c:
            yield c


class TestUpsertUser:
    def test_first_login_creates_user_thing(self, patched_db):
        """On first OAuth login, a Thing with type_hint='person' is auto-created."""
        from backend.database import db
        from backend.routers.auth import _upsert_user

        user_id = _upsert_user("google-123", "alice@example.com", "Alice", None)

        with db() as conn:
            thing = conn.execute(
                "SELECT * FROM things WHERE user_id = ? AND type_hint = 'person'",
                (user_id,),
            ).fetchone()

        assert thing is not None
        assert thing["title"] == "Alice"
        assert thing["surface"] == 0
        data = json.loads(thing["data"])
        assert data["email"] == "alice@example.com"
        assert data["google_id"] == "google-123"

    def test_second_login_does_not_duplicate_thing(self, patched_db):
        """Subsequent logins should NOT create additional User Things."""
        from backend.database import db
        from backend.routers.auth import _upsert_user

        _upsert_user("google-456", "bob@example.com", "Bob", None)
        _upsert_user("google-456", "bob@example.com", "Bob Updated", None)

        with db() as conn:
            things = conn.execute(
                "SELECT * FROM things WHERE type_hint = 'person'",
            ).fetchall()

        assert len(things) == 1
        assert things[0]["title"] == "Bob"


class TestJWTAuth:
    def test_api_rejects_missing_cookie(self, authed_client):
        resp = authed_client.get("/api/things")
        assert resp.status_code == 401
        assert "Not authenticated" in resp.json()["detail"]

    def test_api_rejects_invalid_cookie(self, authed_client):
        authed_client.cookies.set("reli_session", "garbage-token")
        resp = authed_client.get("/api/things")
        assert resp.status_code == 401

    def test_api_accepts_valid_jwt(self, authed_client):
        """Create a valid JWT and verify it grants access."""
        import jwt

        payload = {"sub": "test-user-id", "email": "test@example.com", "exp": 9999999999}
        token = jwt.encode(payload, "test-secret-key", algorithm="HS256")
        authed_client.cookies.set("reli_session", token)
        resp = authed_client.get("/api/things")
        assert resp.status_code == 200

    def test_healthz_no_auth_required(self, authed_client):
        resp = authed_client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_auth_routes_are_public(self, authed_client):
        """Auth endpoints should not require authentication."""
        resp = authed_client.get("/api/auth/me")
        # 401 because no cookie, but NOT because of the route-level dependency
        assert resp.status_code == 401
        assert "Not authenticated" in resp.json()["detail"]

    def test_api_bypassed_when_no_secret_key(self, patched_db):
        """When SECRET_KEY is empty, auth is disabled for local dev."""
        with patch("backend.auth.SECRET_KEY", ""):
            from backend.main import app

            with TestClient(app) as c:
                resp = c.get("/api/things")
                assert resp.status_code == 200
