"""Tests for MCP OAuth 2.1 endpoints and scheme handling."""

from __future__ import annotations

from unittest.mock import patch

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
    """MCP OAuth endpoints must allow cross-origin requests from any MCP client."""

    def test_oauth_token_cors_preflight(self, mcp_client):
        resp = mcp_client.options(
            "/oauth/token",
            headers={
                "Origin": "https://claude.ai",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert resp.status_code == 204
        assert resp.headers.get("access-control-allow-origin") == "https://claude.ai"

    def test_oauth_register_cors_preflight(self, mcp_client):
        resp = mcp_client.options(
            "/oauth/register",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert resp.status_code == 204
        assert resp.headers.get("access-control-allow-origin") == "https://example.com"

    def test_well_known_cors_preflight(self, mcp_client):
        resp = mcp_client.options(
            "/.well-known/oauth-authorization-server",
            headers={
                "Origin": "https://claude.ai",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 204
        assert resp.headers.get("access-control-allow-origin") == "https://claude.ai"

    def test_oauth_token_post_has_cors_header(self, mcp_client):
        resp = mcp_client.post(
            "/oauth/token",
            data={"grant_type": "authorization_code", "code": "fake"},
            headers={"Origin": "https://claude.ai"},
        )
        # Should fail with 400 (bad code) but still have CORS headers
        assert resp.status_code == 400
        assert resp.headers.get("access-control-allow-origin") == "https://claude.ai"

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


class TestGoogleCallbackMcpStateEncoding:
    """MCP OAuth: google_callback must URL-encode client_state in the redirect.

    Regression tests for SEC-031 / GitHub issue #939.
    """

    def _seed_mcp_session(self, state_key: str, client_state: str) -> None:
        """Seed an MCP OAuth session with the given client_state."""
        from datetime import datetime, timedelta, timezone

        from backend.oauth_state import mcp_oauth_sessions

        mcp_oauth_sessions[state_key] = {
            "code_challenge": "test-challenge",
            "code_challenge_method": "S256",
            "redirect_uri": "https://client.example.com/callback",
            "client_id": "test-client",
            "client_state": client_state,
            "google_code_verifier": "test-verifier",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        }

    def _call_callback(self, mcp_client, state_key: str):
        """Call google_callback with mocked Google OAuth internals."""
        from unittest.mock import MagicMock

        mock_credentials = MagicMock()
        mock_credentials.id_token = "fake-id-token"

        mock_flow_instance = MagicMock()
        mock_flow_instance.credentials = mock_credentials

        with (
            patch("backend.routers.auth.SECRET_KEY", "test-secret"),
            patch("backend.routers.auth.Flow") as mock_flow_cls,
            patch("backend.routers.auth.google_id_token") as mock_id_token,
            patch("backend.routers.auth._upsert_user", return_value="u-test"),
            patch("backend.routers.auth.settings") as mock_settings,
        ):
            mock_flow_cls.from_client_config.return_value = mock_flow_instance
            mock_id_token.verify_oauth2_token.return_value = {
                "sub": "google-123",
                "email": "test@example.com",
                "name": "Test User",
                "picture": None,
            }
            mock_settings.allowed_emails_set = set()

            return mcp_client.get(
                f"/api/auth/google/callback?code=fake-auth-code&state={state_key}",
            )

    def test_state_with_special_chars_is_url_encoded(self, mcp_client):
        """State containing & or = must be percent-encoded to prevent param injection."""
        state_key = "test-state-key-1"
        self._seed_mcp_session(state_key, "legit&injected=evil")

        resp = self._call_callback(mcp_client, state_key)

        assert resp.status_code == 302
        location = resp.headers["location"]
        # The raw "&injected=evil" must NOT appear as a separate query param
        assert "injected=evil" not in location
        # The encoded form must be present
        assert "legit%26injected%3Devil" in location

    @pytest.mark.parametrize(
        ("raw_state", "must_contain", "tag"),
        [
            ("a&b=c", "a%26b%3Dc", "ampersand"),
            ("has space", "has%20space", "space"),
            ("has#fragment", "has%23fragment", "hash"),
            ("plus+sign", "plus%2Bsign", "plus"),
        ],
    )
    def test_special_chars_encoded(self, mcp_client, raw_state, must_contain, tag):
        """Various special characters must be percent-encoded in the redirect."""
        state_key = f"test-state-{tag}"
        self._seed_mcp_session(state_key, raw_state)

        resp = self._call_callback(mcp_client, state_key)

        assert resp.status_code == 302
        location = resp.headers["location"]
        assert must_contain in location

    def test_empty_state_omitted_from_redirect(self, mcp_client):
        """When client_state is empty, &state= should not appear in redirect."""
        state_key = "test-state-empty"
        self._seed_mcp_session(state_key, "")

        resp = self._call_callback(mcp_client, state_key)

        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "&state=" not in location
