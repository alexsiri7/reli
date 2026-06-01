"""Tests for JWT session authentication."""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from backend.config import Settings
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

    def test_upsert_user_creates_thing_for_new_user(self, patched_db, db):

        user_id = _upsert_user("google-123", "alice@example.com", "Alice", None)

        with db() as conn:
            thing = conn.execute(
                "SELECT * FROM things WHERE user_id = ? AND type_hint = 'person'",
                (user_id,),
            ).fetchone()

        assert thing is not None
        assert thing["title"] == "Alice"
        assert thing["surface"] == 0
        # PII is stored in UserRecord, not Thing.data; data must be NULL (or JSON null)
        # SQLAlchemy's JSON column stores Python None as either SQL NULL or the JSON literal 'null'
        raw_data = thing["data"]
        assert raw_data is None or raw_data == "null", f"Expected NULL data, got: {raw_data!r}"

    def test_upsert_user_no_duplicate_thing_on_repeat_login(self, patched_db, db):

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

    def test_create_jwt_claims_are_integers(self):
        """iat and exp must be int (RFC 7519 NumericDate), not datetime or float."""
        import jwt as pyjwt

        with patch("backend.routers.auth.SECRET_KEY", "test-secret"):
            from backend.routers.auth import JWT_ALGORITHM, JWT_EXPIRY_SECONDS, _create_jwt

            token = _create_jwt("u-abc123", "user@example.com")
            payload = pyjwt.decode(token, "test-secret", algorithms=[JWT_ALGORITHM])

            assert isinstance(payload["iat"], int), f"iat must be int, got {type(payload['iat'])}"
            assert isinstance(payload["exp"], int), f"exp must be int, got {type(payload['exp'])}"
            assert payload["exp"] > payload["iat"]
            assert payload["exp"] - payload["iat"] == JWT_EXPIRY_SECONDS, (
                f"exp-iat delta should be {JWT_EXPIRY_SECONDS}, got {payload['exp'] - payload['iat']}"
            )

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


class TestCookieSecureFlag:
    """Test that COOKIE_SECURE env var controls the cookie secure attribute."""

    def test_cookie_secure_true_by_default(self):
        s = Settings(SECRET_KEY="x", ALLOWED_EMAILS="")
        assert s.cookie_secure_bool is True

    def test_cookie_secure_false_when_disabled(self):
        s = Settings(SECRET_KEY="x", ALLOWED_EMAILS="", COOKIE_SECURE="false")
        assert s.cookie_secure_bool is False

    def test_cookie_secure_false_variants(self):
        for val in ("false", "False", "FALSE", "0", "no"):
            s = Settings(SECRET_KEY="x", ALLOWED_EMAILS="", COOKIE_SECURE=val)
            assert s.cookie_secure_bool is False, f"Expected False for COOKIE_SECURE={val!r}"

    def test_cookie_secure_true_variants(self):
        for val in ("true", "True", "TRUE", "1", "yes"):
            s = Settings(SECRET_KEY="x", ALLOWED_EMAILS="", COOKIE_SECURE=val)
            assert s.cookie_secure_bool is True, f"Expected True for COOKIE_SECURE={val!r}"


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


class TestOAuthAllowlistRejection:
    """Test that OAuth allowlist rejection does not log the user's email (SEC-021)."""

    def test_oauth_rejection_log_contains_no_email(self, patched_db, caplog):
        """Verify the allowlist rejection log line never leaks the user's email address."""
        fake_id_info = {
            "sub": "google-123",
            "email": "blocked@example.com",
            "name": "Blocked User",
            "picture": None,
        }
        fake_state = "test-state-value"
        fake_flow_entry = {
            "code_verifier": "fake-code-verifier",
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=600),
        }

        mock_flow = MagicMock()
        mock_flow.fetch_token.return_value = None
        mock_flow.credentials.id_token = "fake-token"
        mock_flow.code_verifier = None

        with (
            patch("backend.routers.auth.SECRET_KEY", "test-secret-key"),
            patch("backend.routers.auth.GOOGLE_CLIENT_ID", "fake-client-id"),
            patch("backend.routers.auth._pending_flows", {fake_state: fake_flow_entry}),
            patch("backend.routers.auth.Flow.from_client_config", return_value=mock_flow),
            patch(
                "backend.routers.auth.google_id_token.verify_oauth2_token",
                return_value=fake_id_info,
            ),
            patch(
                "backend.config.Settings.allowed_emails_set",
                new_callable=lambda: property(lambda self: {"allowed@example.com"}),
            ),
            caplog.at_level(logging.WARNING, logger="backend.routers.auth"),
        ):
            from backend.main import app

            with TestClient(app, follow_redirects=False) as client:
                resp = client.get(f"/api/auth/google/callback?code=fake-code&state={fake_state}")

        assert resp.status_code in (302, 307)
        assert "blocked@example.com" not in caplog.text


class TestOAuthCallbackDoesNotLogCode:
    """Regression test for CWE-532: authorization code must not appear in logs."""

    def test_google_callback_does_not_log_authorization_code(self, patched_db, caplog):
        """The INFO log at callback entry must not include any fragment of the auth code."""
        fake_state = "test-state-value"
        fake_code = "supersecretauthcode123456"
        fake_flow_entry = {
            "code_verifier": "fake-verifier",
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=600),
        }

        mock_flow = MagicMock()
        mock_flow.fetch_token.return_value = None
        mock_flow.credentials.id_token = "fake-token"
        mock_flow.code_verifier = None

        fake_id_info = {
            "sub": "google-001",
            "email": "allowed@example.com",
            "name": "Test User",
            "picture": None,
        }

        with (
            patch("backend.routers.auth.SECRET_KEY", "test-secret-key"),
            patch("backend.routers.auth.GOOGLE_CLIENT_ID", "fake-client-id"),
            patch("backend.routers.auth._pending_flows", {fake_state: fake_flow_entry}),
            patch("backend.routers.auth.Flow.from_client_config", return_value=mock_flow),
            patch(
                "backend.routers.auth.google_id_token.verify_oauth2_token",
                return_value=fake_id_info,
            ),
            patch(
                "backend.config.Settings.allowed_emails_set",
                new_callable=lambda: property(lambda self: {"allowed@example.com"}),
            ),
            caplog.at_level(logging.INFO, logger="backend.routers.auth"),
        ):
            from backend.main import app

            with TestClient(app, follow_redirects=False) as client:
                client.get(f"/api/auth/google/callback?code={fake_code}&state={fake_state}")

        assert fake_code not in caplog.text, (
            f"Authorization code appeared in logs — CWE-532 regression: {caplog.text!r}"
        )
        assert fake_code[:20] not in caplog.text, (
            f"Authorization code prefix appeared in logs — CWE-532 regression: {caplog.text!r}"
        )
