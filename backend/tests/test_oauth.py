"""Tests for MCP OAuth 2.1 endpoints (issue #297)."""
from __future__ import annotations

import base64
import hashlib
import secrets
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def oauth_client(patched_db):
    """TestClient with SECRET_KEY configured."""
    with patch("backend.auth.SECRET_KEY", "test-secret-key-32-bytes-padding!"):
        from backend.main import app

        with TestClient(app, follow_redirects=False) as c:
            yield c


@pytest.fixture()
def open_client(patched_db):
    """TestClient without SECRET_KEY (dev/open mode)."""
    from backend.main import app

    with TestClient(app, follow_redirects=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier + code_challenge (S256)."""
    verifier = secrets.token_urlsafe(43)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


# ---------------------------------------------------------------------------
# Well-known metadata endpoints
# ---------------------------------------------------------------------------


class TestWellKnownEndpoints:
    def test_protected_resource_metadata(self, open_client):
        resp = open_client.get("/.well-known/oauth-protected-resource")
        assert resp.status_code == 200
        data = resp.json()
        assert "/mcp" in data["resource"]
        assert data["authorization_servers"][0] in data["resource"]
        assert "mcp" in data["scopes_supported"]

    def test_authorization_server_metadata(self, open_client):
        resp = open_client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200
        data = resp.json()
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "S256" in data["code_challenge_methods_supported"]
        assert "authorization_code" in data["grant_types_supported"]
        assert "code" in data["response_types_supported"]

    def test_metadata_urls_are_consistent(self, open_client):
        """authorization_endpoint and token_endpoint share the same issuer."""
        resp = open_client.get("/.well-known/oauth-authorization-server")
        data = resp.json()
        assert data["authorization_endpoint"].startswith(data["issuer"])
        assert data["token_endpoint"].startswith(data["issuer"])


# ---------------------------------------------------------------------------
# /oauth/authorize
# ---------------------------------------------------------------------------


class TestOAuthAuthorize:
    def test_missing_google_oauth_config_returns_501(self, open_client):
        with (
            patch("backend.routers.oauth.GOOGLE_CLIENT_ID", "", create=True),
        ):
            from backend.routers import auth as auth_module

            with patch.object(auth_module, "GOOGLE_CLIENT_ID", ""):
                _, challenge = _pkce_pair()
                resp = open_client.get(
                    "/oauth/authorize",
                    params={
                        "redirect_uri": "http://localhost:12345/callback",
                        "code_challenge": challenge,
                        "code_challenge_method": "S256",
                    },
                )
                assert resp.status_code == 501

    def test_missing_redirect_uri_returns_400(self, open_client):
        _, challenge = _pkce_pair()
        from backend.routers import auth as auth_module

        with (
            patch.object(auth_module, "GOOGLE_CLIENT_ID", "fake-id"),
            patch.object(auth_module, "GOOGLE_CLIENT_SECRET", "fake-secret"),
        ):
            resp = open_client.get(
                "/oauth/authorize",
                params={"code_challenge": challenge},
            )
            assert resp.status_code == 400

    def test_missing_code_challenge_returns_400(self, open_client):
        from backend.routers import auth as auth_module

        with (
            patch.object(auth_module, "GOOGLE_CLIENT_ID", "fake-id"),
            patch.object(auth_module, "GOOGLE_CLIENT_SECRET", "fake-secret"),
        ):
            resp = open_client.get(
                "/oauth/authorize",
                params={"redirect_uri": "http://localhost:12345/callback"},
            )
            assert resp.status_code == 400

    def test_unsupported_code_challenge_method_returns_400(self, open_client):
        from backend.routers import auth as auth_module

        with (
            patch.object(auth_module, "GOOGLE_CLIENT_ID", "fake-id"),
            patch.object(auth_module, "GOOGLE_CLIENT_SECRET", "fake-secret"),
        ):
            resp = open_client.get(
                "/oauth/authorize",
                params={
                    "redirect_uri": "http://localhost:12345/callback",
                    "code_challenge": "abc",
                    "code_challenge_method": "plain",
                },
            )
            assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /oauth/token
# ---------------------------------------------------------------------------


class TestOAuthToken:
    def test_valid_code_returns_jwt(self, patched_db):
        """A valid auth code + correct PKCE verifier returns a JWT."""
        from backend.oauth_state import store_auth_code

        verifier, challenge = _pkce_pair()
        code = store_auth_code(
            user_id="u-test-123",
            email="test@example.com",
            code_challenge=challenge,
            code_challenge_method="S256",
            redirect_uri="http://localhost:12345/callback",
        )

        with patch("backend.routers.auth.SECRET_KEY", "test-secret-key-32-bytes-padding!"):
            from backend.main import app

            with TestClient(app) as c:
                resp = c.post(
                    "/oauth/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "code_verifier": verifier,
                        "client_id": "mcp-client",
                        "redirect_uri": "http://localhost:12345/callback",
                    },
                )

        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

        # JWT should decode to the correct user
        payload = jwt.decode(
            data["access_token"],
            "test-secret-key-32-bytes-padding!",
            algorithms=["HS256"],
        )
        assert payload["sub"] == "u-test-123"
        assert payload["email"] == "test@example.com"

    def test_wrong_code_verifier_rejected(self, patched_db):
        from backend.oauth_state import store_auth_code

        _, challenge = _pkce_pair()
        code = store_auth_code(
            user_id="u-test-123",
            email="test@example.com",
            code_challenge=challenge,
            code_challenge_method="S256",
            redirect_uri="http://localhost:12345/callback",
        )

        with patch("backend.routers.auth.SECRET_KEY", "test-secret-key-32-bytes-padding!"):
            from backend.main import app

            with TestClient(app) as c:
                resp = c.post(
                    "/oauth/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "code_verifier": "wrong-verifier",
                    },
                )

        assert resp.status_code == 400
        assert "invalid_grant" in resp.json()["detail"]

    def test_invalid_code_rejected(self, patched_db):
        from backend.main import app

        with TestClient(app) as c:
            resp = c.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": "nonexistent-code",
                    "code_verifier": "anything",
                },
            )
        assert resp.status_code == 400

    def test_code_is_single_use(self, patched_db):
        """Auth codes must be consumed on first use."""
        from backend.oauth_state import store_auth_code

        verifier, challenge = _pkce_pair()
        code = store_auth_code(
            user_id="u-test-123",
            email="test@example.com",
            code_challenge=challenge,
            code_challenge_method="S256",
            redirect_uri="http://localhost:12345/callback",
        )

        with patch("backend.routers.auth.SECRET_KEY", "test-secret-key-32-bytes-padding!"):
            from backend.main import app

            with TestClient(app) as c:
                payload = {
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": verifier,
                }
                first = c.post("/oauth/token", data=payload)
                second = c.post("/oauth/token", data=payload)

        assert first.status_code == 200
        assert second.status_code == 400

    def test_unsupported_grant_type_rejected(self, open_client):
        resp = open_client.post(
            "/oauth/token",
            data={
                "grant_type": "client_credentials",
                "code": "any",
                "code_verifier": "any",
            },
        )
        assert resp.status_code == 400
        assert "unsupported_grant_type" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# MCP OAuth full flow (state storage round-trip)
# ---------------------------------------------------------------------------


class TestOAuthStateStorage:
    def test_store_and_pop_mcp_flow(self):
        from backend.oauth_state import pop_mcp_flow, store_mcp_flow

        verifier, challenge = _pkce_pair()
        google_state = store_mcp_flow(
            redirect_uri="http://localhost:12345/callback",
            original_state="client-state-xyz",
            code_challenge=challenge,
            code_challenge_method="S256",
            client_id="mcp",
        )

        flow = pop_mcp_flow(google_state)
        assert flow is not None
        assert flow.redirect_uri == "http://localhost:12345/callback"
        assert flow.original_state == "client-state-xyz"
        assert flow.code_challenge == challenge

    def test_pop_mcp_flow_is_single_use(self):
        from backend.oauth_state import pop_mcp_flow, store_mcp_flow

        google_state = store_mcp_flow(
            redirect_uri="http://localhost:12345/callback",
            original_state="s",
            code_challenge="c",
            code_challenge_method="S256",
            client_id="mcp",
        )
        assert pop_mcp_flow(google_state) is not None
        assert pop_mcp_flow(google_state) is None

    def test_pop_nonexistent_flow_returns_none(self):
        from backend.oauth_state import pop_mcp_flow

        assert pop_mcp_flow("does-not-exist") is None

    def test_store_and_pop_auth_code(self):
        from backend.oauth_state import pop_auth_code, store_auth_code

        verifier, challenge = _pkce_pair()
        code = store_auth_code(
            user_id="u-abc",
            email="a@b.com",
            code_challenge=challenge,
            code_challenge_method="S256",
            redirect_uri="http://localhost:12345/callback",
        )
        entry = pop_auth_code(code)
        assert entry is not None
        assert entry.user_id == "u-abc"
        assert entry.email == "a@b.com"
        assert entry.code_challenge == challenge

    def test_auth_code_is_single_use(self):
        from backend.oauth_state import pop_auth_code, store_auth_code

        _, challenge = _pkce_pair()
        code = store_auth_code(
            user_id="u-abc",
            email="a@b.com",
            code_challenge=challenge,
            code_challenge_method="S256",
            redirect_uri="http://localhost:12345/callback",
        )
        assert pop_auth_code(code) is not None
        assert pop_auth_code(code) is None


# ---------------------------------------------------------------------------
# MCP JWT middleware integration
# ---------------------------------------------------------------------------


class TestMCPJWTAuth:
    """Integration tests: JWT from /oauth/token works against the MCP middleware."""

    _SECRET = "test-secret-key-32-bytes-padding!!"

    def _make_jwt(self) -> str:
        payload = {"sub": "u-test", "email": "test@example.com", "exp": 9999999999}
        return jwt.encode(payload, self._SECRET, algorithm="HS256")

    def test_valid_jwt_passes_mcp_middleware(self):
        from backend.mcp_server import _TokenAuthMiddleware
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route
        from fastapi.testclient import TestClient

        def echo(request: Request) -> PlainTextResponse:
            return PlainTextResponse("ok")

        inner = Starlette(routes=[Route("/", echo)])
        wrapped = _TokenAuthMiddleware(inner, self._SECRET)
        client = TestClient(wrapped)

        token = self._make_jwt()
        resp = client.get("/", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_expired_jwt_rejected_by_mcp_middleware(self):
        from backend.mcp_server import _TokenAuthMiddleware
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route
        from fastapi.testclient import TestClient

        def echo(request: Request) -> PlainTextResponse:
            return PlainTextResponse("ok")

        inner = Starlette(routes=[Route("/", echo)])
        wrapped = _TokenAuthMiddleware(inner, self._SECRET)
        client = TestClient(wrapped)

        expired_payload = {"sub": "u-test", "email": "test@example.com", "exp": 1}
        expired_token = jwt.encode(expired_payload, self._SECRET, algorithm="HS256")
        resp = client.get("/", headers={"Authorization": f"Bearer {expired_token}"})
        assert resp.status_code == 401
