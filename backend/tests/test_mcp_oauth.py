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
