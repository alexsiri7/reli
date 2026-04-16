"""Tests for JWT session authentication."""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from backend.routers.auth import _upsert_user


@pytest.fixture()
def authed_client(patched_db):
    """TestClient with SECRET_KEY set so auth is enforced."""
    with patch("backend.auth.SECRET_KEY", "test-secret-key"):
        from backend.main import app

        with TestClient(app) as c:
            yield c


class TestUpsertUserConcurrency:
    """Test that concurrent OAuth callbacks don't crash on duplicate insert."""

    def test_upsert_user_handles_integrity_error(self, patched_db):
        """Simulated race: commit succeeds then IntegrityError is raised; retry finds the winner row."""
        original_commit = Session.commit
        call_count = 0

        def commit_that_races(self):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Simulate the concurrent winner by inserting the row first
                original_commit(self)
                # Now raise as if a second concurrent request hit a conflict
                raise IntegrityError("mock", {}, Exception("unique violation"))
            return original_commit(self)

        with patch.object(Session, "commit", commit_that_races):
            # _upsert_user will: try INSERT -> commit_that_races commits it
            # then raises IntegrityError -> rollback -> re-SELECT finds the
            # row (it was committed) -> updates it -> second commit succeeds
            user_id = _upsert_user("google-race", "racer@example.com", "Racer", None)

        assert user_id is not None
        assert user_id.startswith("u-")
        assert call_count == 2  # initial commit + retry commit both ran

    def test_upsert_user_reraises_unexpected_integrity_error(self, patched_db):
        """IntegrityError with no concurrent winner should propagate."""

        def commit_that_fails_cold(self):
            # Do NOT insert first — simulates a non-race IntegrityError (no winner row)
            raise IntegrityError("mock", {}, Exception("unexpected constraint"))

        with patch.object(Session, "commit", commit_that_fails_cold):
            with pytest.raises(IntegrityError):
                _upsert_user("google-unexpected", "err@example.com", "Err", None)


class TestUserThingCreation:
    """Test that a Thing is auto-created for new OAuth users."""

    def test_upsert_user_creates_thing_for_new_user(self, patched_db):
        from backend.database import db

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

    def test_upsert_user_no_duplicate_thing_on_repeat_login(self, patched_db):
        from backend.database import db

        user_id = _upsert_user("google-123", "alice@example.com", "Alice", None)
        _upsert_user("google-123", "alice@example.com", "Alice", None)

        with db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) as c FROM things WHERE user_id = ? AND type_hint = 'person'",
                (user_id,),
            ).fetchone()["c"]

        assert count == 1


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
        """When neither SECRET_KEY nor RELI_API_TOKEN is set, auth is disabled for local dev."""
        with (
            patch("backend.auth.SECRET_KEY", ""),
            patch("backend.auth._API_TOKEN", ""),  # explicit: test the fully-disabled path
        ):
            from backend.main import app

            with TestClient(app) as c:
                resp = c.get("/api/things")
                assert resp.status_code == 200


class TestApiTokenWithoutSecretKey:
    """Staging scenario: RELI_API_TOKEN set, SECRET_KEY absent."""

    @pytest.fixture()
    def staging_client(self, patched_db):
        """TestClient simulating staging: API token set, no SECRET_KEY."""
        with (
            patch("backend.auth.SECRET_KEY", ""),
            patch("backend.auth._API_TOKEN", "staging-token-abc"),
        ):
            from backend.main import app

            with TestClient(app) as c:
                yield c

    def test_unauthenticated_request_rejected_when_api_token_set(self, staging_client):
        """When RELI_API_TOKEN is configured but no Bearer token is provided, reject with 401."""
        resp = staging_client.get("/api/things")
        assert resp.status_code == 401
        assert "Not authenticated" in resp.json()["detail"]

    def test_valid_bearer_token_accepted_when_secret_key_absent(self, staging_client):
        """Valid Bearer token must still work even when SECRET_KEY is not set."""
        resp = staging_client.get(
            "/api/things",
            headers={"Authorization": "Bearer staging-token-abc"},
        )
        # Auth passes (not 401) — actual status depends on whether a user record exists
        assert resp.status_code != 401

    def test_invalid_bearer_token_rejected_when_secret_key_absent(self, staging_client):
        """Invalid Bearer token must receive 401 in staging config."""
        resp = staging_client.get(
            "/api/things",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401
        assert "Invalid API token" in resp.json()["detail"]
