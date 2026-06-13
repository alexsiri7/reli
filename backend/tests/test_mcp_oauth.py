"""Tests for MCP OAuth 2.1 endpoints and scheme handling."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def mcp_client(patched_db):
    from backend.main import app

    with TestClient(app, follow_redirects=False) as c:
        yield c


class TestOAuthMetadataScheme:
    """Metadata endpoints must return https:// URLs when RELI_BASE_URL is set."""

    def test_authorization_server_metadata_uses_reli_base_url(self, mcp_client):
        with patch("backend.routers.mcp_oauth.settings") as mock_settings:
            mock_settings.RELI_BASE_URL = "https://reli.interstellarai.net"
            mock_settings.GOOGLE_AUTH_REDIRECT_URI = "https://reli.interstellarai.net/api/auth/google/callback"
            resp = mcp_client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200
        data = resp.json()
        assert data["issuer"].startswith("https://")
        assert data["authorization_endpoint"].startswith("https://")
        assert data["token_endpoint"].startswith("https://")

    def test_authorization_server_metadata_derives_https_from_redirect_uri(self, mcp_client):
        with patch("backend.routers.mcp_oauth.settings") as mock_settings:
            mock_settings.RELI_BASE_URL = ""
            mock_settings.GOOGLE_AUTH_REDIRECT_URI = "https://reli.interstellarai.net/api/auth/google/callback"
            resp = mcp_client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200
        data = resp.json()
        assert data["issuer"] == "https://reli.interstellarai.net"
        assert data["authorization_endpoint"] == "https://reli.interstellarai.net/oauth/authorize"

    def test_protected_resource_metadata_uses_https(self, mcp_client):
        with patch("backend.routers.mcp_oauth.settings") as mock_settings:
            mock_settings.RELI_BASE_URL = "https://reli.interstellarai.net"
            mock_settings.GOOGLE_AUTH_REDIRECT_URI = "https://reli.interstellarai.net/api/auth/google/callback"
            resp = mcp_client.get("/.well-known/oauth-protected-resource")
        assert resp.status_code == 200
        data = resp.json()
        assert data["resource"].startswith("https://")


class TestMcpOAuthCors:
    """MCP OAuth endpoints allow cross-origin requests only from allowed origins."""

    def test_oauth_token_cors_preflight(self, mcp_client):
        resp = mcp_client.options(
            "/oauth/token",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert resp.status_code == 204
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_oauth_register_cors_preflight(self, mcp_client):
        resp = mcp_client.options(
            "/oauth/register",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert resp.status_code == 204
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_well_known_cors_preflight(self, mcp_client):
        resp = mcp_client.options(
            "/.well-known/oauth-authorization-server",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 204
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_oauth_token_post_has_cors_header(self, mcp_client):
        resp = mcp_client.post(
            "/oauth/token",
            data={"grant_type": "authorization_code", "code": "fake"},
            headers={"Origin": "http://localhost:5173"},
        )
        # Should fail with 400 (bad code) but still have CORS headers
        assert resp.status_code == 400
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_allowlisted_origin_is_reflected(self, mcp_client, monkeypatch):
        """When MCP_CORS_ORIGINS is set, only listed origins are reflected."""
        import backend.main as main_module

        monkeypatch.setattr(main_module, "_mcp_allowed_origins", {"https://claude.ai"})
        resp = mcp_client.options(
            "/oauth/token",
            headers={
                "Origin": "https://claude.ai",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "https://claude.ai"

    def test_non_allowlisted_origin_gets_no_cors_header(self, mcp_client, monkeypatch):
        """Origins not in the allowlist get no CORS header, blocking browser access."""
        import backend.main as main_module

        monkeypatch.setattr(main_module, "_mcp_allowed_origins", {"https://claude.ai"})
        resp = mcp_client.options(
            "/oauth/token",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-origin") is None

    def test_no_origin_header_gets_no_cors_header(self, mcp_client, monkeypatch):
        """Requests without an Origin header get no CORS header (non-browser clients unaffected)."""
        import backend.main as main_module

        monkeypatch.setattr(main_module, "_mcp_allowed_origins", {"https://claude.ai"})
        resp = mcp_client.options(
            "/oauth/token",
            headers={"Access-Control-Request-Method": "POST"},  # no Origin header
        )
        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao == ""

    def test_unlisted_origin_gets_no_cors_header_by_default(self, mcp_client):
        """An unknown origin must not receive Access-Control-Allow-Origin in default config."""
        resp = mcp_client.options(
            "/oauth/token",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-origin") is None

    def test_no_origin_header_request_passes_through(self, mcp_client):
        """Non-browser clients without Origin header can still reach MCP endpoints."""
        resp = mcp_client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") is None

    def test_mcp_cors_origins_parsed_from_env(self, monkeypatch):
        """MCP_CORS_ORIGINS string is split, stripped, and deduplicated correctly."""
        import backend.config as cfg_module

        monkeypatch.setenv("MCP_CORS_ORIGINS", " https://claude.ai , https://example.com ")
        new_settings = cfg_module.Settings()
        result = {o.strip() for o in new_settings.MCP_CORS_ORIGINS.split(",") if o.strip()}
        assert result == {"https://claude.ai", "https://example.com"}

    def test_mcp_cors_origins_whitespace_only_yields_empty_set(self, monkeypatch):
        """A whitespace-only MCP_CORS_ORIGINS must produce an empty set (wildcard mode)."""
        import backend.config as cfg_module

        monkeypatch.setenv("MCP_CORS_ORIGINS", "   ")
        new_settings = cfg_module.Settings()
        result = {o.strip() for o in new_settings.MCP_CORS_ORIGINS.split(",") if o.strip()}
        assert result == set()

    def test_api_route_does_not_get_permissive_cors(self, mcp_client):
        """Non-OAuth routes should NOT allow arbitrary origins."""
        resp = mcp_client.options(
            "/api/health",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # Should NOT have access-control-allow-origin for an unknown origin
        acao = resp.headers.get("access-control-allow-origin", "")
        assert "evil.example.com" not in acao


class TestMcpRedirectScheme:
    """The /mcp redirect must use the config-derived base URL, not request.url.

    When running behind a TLS-terminating proxy, request.url.scheme is 'http'.
    The redirect must use the production https:// URL from settings.
    """

    def test_mcp_redirect_uses_base_url_not_request_url(self, mcp_client):
        """GET /mcp should redirect to /mcp/ using the configured https base URL."""
        with patch("backend.routers.mcp_oauth.settings") as mock_settings:
            mock_settings.RELI_BASE_URL = "https://reli.interstellarai.net"
            mock_settings.GOOGLE_AUTH_REDIRECT_URI = "https://reli.interstellarai.net/api/auth/google/callback"
            resp = mcp_client.get("/mcp")
        assert resp.status_code == 307
        location = resp.headers["location"]
        assert location == "https://reli.interstellarai.net/mcp/"
        assert location.startswith("https://"), f"Expected https redirect, got: {location}"

    def test_mcp_redirect_does_not_use_http_from_request(self, mcp_client):
        """Verify the redirect location is NOT derived from request.url (which would be http://)."""
        with patch("backend.routers.mcp_oauth.settings") as mock_settings:
            mock_settings.RELI_BASE_URL = "https://reli.interstellarai.net"
            mock_settings.GOOGLE_AUTH_REDIRECT_URI = "https://reli.interstellarai.net/api/auth/google/callback"
            # TestClient sends requests as http://testserver — if we were using request.url
            # the redirect would incorrectly go to http://testserver/mcp/
            resp = mcp_client.get("/mcp")
        assert resp.status_code == 307
        location = resp.headers["location"]
        assert "testserver" not in location, "redirect used request.url (testserver) instead of settings"
        assert "http://" not in location, f"redirect incorrectly uses http://: {location}"


class TestOAuthRegisterRedirectUriValidation:
    """POST /oauth/register must enforce redirect_uri scheme rules (accept https/localhost, reject others)."""

    def test_register_accepts_https_redirect_uri(self, mcp_client):
        resp = mcp_client.post(
            "/oauth/register",
            json={"redirect_uris": ["https://legitimate.example.com/callback"], "client_name": "test"},
        )
        assert resp.status_code == 201

    def test_register_accepts_http_localhost(self, mcp_client):
        resp = mcp_client.post(
            "/oauth/register",
            json={"redirect_uris": ["http://localhost:8080/callback"], "client_name": "test"},
        )
        assert resp.status_code == 201

    def test_register_accepts_http_127_0_0_1(self, mcp_client):
        resp = mcp_client.post(
            "/oauth/register",
            json={"redirect_uris": ["http://127.0.0.1:3000/callback"], "client_name": "test"},
        )
        assert resp.status_code == 201

    def test_register_rejects_http_external_host(self, mcp_client):
        resp = mcp_client.post(
            "/oauth/register",
            json={"redirect_uris": ["http://evil.com/steal"], "client_name": "test"},
        )
        assert resp.status_code == 400
        assert "redirect_uri must use https" in resp.json()["detail"]

    def test_register_rejects_javascript_scheme(self, mcp_client):
        resp = mcp_client.post(
            "/oauth/register",
            json={"redirect_uris": ["javascript:alert(1)"], "client_name": "test"},
        )
        assert resp.status_code == 400
        assert "redirect_uri must use https" in resp.json()["detail"]

    def test_register_rejects_schemeless_uri(self, mcp_client):
        # urllib.parse yields scheme="" for bare strings; the else branch rejects it
        resp = mcp_client.post(
            "/oauth/register",
            json={"redirect_uris": ["notavalidurl"], "client_name": "test"},
        )
        assert resp.status_code == 400
        assert "redirect_uri must use https" in resp.json()["detail"]

    def test_register_accepts_empty_redirect_uris(self, mcp_client):
        resp = mcp_client.post(
            "/oauth/register",
            json={"redirect_uris": [], "client_name": "test"},
        )
        assert resp.status_code == 201

    def test_register_accepts_null_redirect_uris_as_empty(self, mcp_client):
        # null redirect_uris is treated the same as an absent key (empty list)
        # and must not cause a 500 TypeError
        resp = mcp_client.post(
            "/oauth/register",
            json={"redirect_uris": None, "client_name": "test"},
        )
        assert resp.status_code == 201

    def test_register_rejects_mixed_valid_and_invalid_uris(self, mcp_client):
        """A single invalid URI in the list must reject the whole registration."""
        resp = mcp_client.post(
            "/oauth/register",
            json={
                "redirect_uris": ["https://good.example.com/callback", "http://evil.com/steal"],
                "client_name": "test",
            },
        )
        assert resp.status_code == 400

    def test_register_rejects_invalid_uri_regardless_of_position(self, mcp_client):
        """Validation applies even when the invalid URI is not first."""
        resp = mcp_client.post(
            "/oauth/register",
            json={
                "redirect_uris": ["http://evil.com/steal", "https://good.example.com/callback"],
                "client_name": "test",
            },
        )
        assert resp.status_code == 400


class TestMcpTokenAudience:
    """Tokens issued via /oauth/token must carry aud='mcp'."""

    def _make_code_challenge(self, verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    def test_oauth_token_response_has_mcp_audience(self, patched_db):
        """Access tokens from the /oauth/token endpoint must have aud='mcp'."""
        from backend.main import app
        from backend.oauth_state import cleanup_and_store, mcp_auth_codes, mcp_registered_clients
        from backend.routers.auth import JWT_ALGORITHM

        secret = "test-secret-key-mcp-audience"
        code_verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        auth_code = "test-auth-code-aud-check"

        # Register the client as a public client (PKCE flow — no secret required)
        cleanup_and_store(
            mcp_registered_clients,
            "test-client-id",
            {
                "client_id": "test-client-id",
                "client_secret": "",
                "client_name": "test-client",
                "token_endpoint_auth_method": "none",
                "redirect_uris": ["https://client.example.com/callback"],
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "scope": "mcp",
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=600),
            },
        )

        cleanup_and_store(
            mcp_auth_codes,
            auth_code,
            {
                "user_id": "u-test-001",
                "email": "test@example.com",
                "code_challenge": self._make_code_challenge(code_verifier),
                "code_challenge_method": "S256",
                "redirect_uri": "https://client.example.com/callback",
                "client_id": "test-client-id",
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=600),
            },
        )

        with patch("backend.routers.auth.SECRET_KEY", secret):
            with TestClient(app) as c:
                resp = c.post(
                    "/oauth/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": auth_code,
                        "redirect_uri": "https://client.example.com/callback",
                        "client_id": "test-client-id",
                        "code_verifier": code_verifier,
                    },
                )

        assert resp.status_code == 200
        access_token = resp.json()["access_token"]
        payload = pyjwt.decode(access_token, secret, algorithms=[JWT_ALGORITHM], audience="mcp")
        assert payload["aud"] == "mcp"
        assert payload["sub"] == "u-test-001"


class TestValidateClientSecret:
    """Tests for _validate_client_secret (SEC-03)."""

    def _register_client(self, client_id: str, secret: str, auth_method: str) -> None:
        from backend.oauth_state import cleanup_and_store, mcp_registered_clients

        cleanup_and_store(
            mcp_registered_clients,
            client_id,
            {
                "client_id": client_id,
                "client_secret": secret,
                "client_name": "test",
                "token_endpoint_auth_method": auth_method,
                "redirect_uris": ["https://example.com/cb"],
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "scope": "mcp",
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=600),
            },
        )

    def test_unknown_client_returns_400(self, patched_db):
        from fastapi import HTTPException

        from backend.routers.mcp_oauth import _validate_client_secret

        with pytest.raises(HTTPException) as exc:
            _validate_client_secret("nonexistent-client", "any-secret")
        assert exc.value.status_code == 400

    def test_public_client_skips_secret_check(self, patched_db):
        from backend.routers.mcp_oauth import _validate_client_secret

        self._register_client("pub-client", "", "none")
        # Should not raise even with empty secret
        _validate_client_secret("pub-client", "")

    def test_confidential_client_rejects_wrong_secret(self, patched_db):
        from fastapi import HTTPException

        from backend.routers.mcp_oauth import _validate_client_secret

        self._register_client("conf-client", "correct-secret", "client_secret_post")
        with pytest.raises(HTTPException) as exc:
            _validate_client_secret("conf-client", "wrong-secret")
        assert exc.value.status_code == 401

    def test_confidential_client_rejects_missing_secret(self, patched_db):
        from fastapi import HTTPException

        from backend.routers.mcp_oauth import _validate_client_secret

        self._register_client("conf-client2", "correct-secret", "client_secret_post")
        with pytest.raises(HTTPException) as exc:
            _validate_client_secret("conf-client2", "")
        assert exc.value.status_code == 401

    def test_confidential_client_accepts_correct_secret(self, patched_db):
        from backend.routers.mcp_oauth import _validate_client_secret

        self._register_client("conf-client3", "correct-secret", "client_secret_post")
        # Should not raise
        _validate_client_secret("conf-client3", "correct-secret")


class TestOAuthAuthorizeGenericError:
    """oauth_authorize() must return generic 501 text — no env var names in response (CWE-209)."""

    @pytest.mark.parametrize(
        "client_id,client_secret,secret_key,expected_log_key",
        [
            ("", "secret", "key", "GOOGLE_CLIENT_ID"),
            ("client-id", "", "key", "GOOGLE_CLIENT_SECRET"),
            ("client-id", "secret", "", "SECRET_KEY"),
        ],
    )
    def test_returns_generic_error(self, mcp_client, client_id, client_secret, secret_key, expected_log_key):
        with (
            patch("backend.routers.mcp_oauth.settings") as mock_settings,
            patch("backend.routers.mcp_oauth.logger") as mock_logger,
        ):
            mock_settings.GOOGLE_CLIENT_ID = client_id
            mock_settings.GOOGLE_CLIENT_SECRET = client_secret
            mock_settings.SECRET_KEY = secret_key
            resp = mcp_client.get("/oauth/authorize?client_id=x&redirect_uri=http://localhost")
        assert resp.status_code == 501
        assert resp.json()["detail"] == "Authentication service unavailable"
        mock_logger.error.assert_called_once()
        assert expected_log_key in mock_logger.error.call_args[0][0]
