"""MCP OAuth 2.1 endpoints.

Implements the authorization server role so MCP clients (like Claude Code)
can authenticate via Google Login instead of a pre-shared secret.

Endpoints:
  GET  /.well-known/oauth-protected-resource  — RFC 9728
  GET  /.well-known/oauth-authorization-server — RFC 8414
  GET  /oauth/authorize                        — starts Google OAuth + stores PKCE state
  POST /oauth/token                            — exchanges auth code for JWT bearer token
"""
from __future__ import annotations

import base64
import hashlib
import logging
import urllib.parse

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..oauth_state import pop_auth_code, store_mcp_flow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["oauth"])


def _base_url(request: Request) -> str:
    """Return the public base URL (no trailing slash)."""
    return str(request.base_url).rstrip("/")


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
def protected_resource_metadata(request: Request) -> JSONResponse:
    """RFC 9728: Protected Resource Metadata for the /mcp endpoint."""
    base = _base_url(request)
    return JSONResponse(
        {
            "resource": f"{base}/mcp",
            "authorization_servers": [base],
            "scopes_supported": ["mcp"],
        }
    )


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
def authorization_server_metadata(request: Request) -> JSONResponse:
    """RFC 8414: Authorization Server Metadata."""
    base = _base_url(request)
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["mcp"],
        }
    )


@router.get("/oauth/authorize", include_in_schema=False)
def oauth_authorize(
    client_id: str = "",
    redirect_uri: str = "",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    response_type: str = "code",
    scope: str = "mcp",
) -> RedirectResponse:
    """Start the OAuth 2.1 + PKCE authorization flow via Google login."""
    # Import lazily to avoid any circular-import issues at module load time
    from google_auth_oauthlib.flow import Flow

    from ..routers.auth import (
        AUTH_SCOPES,
        GOOGLE_CLIENT_ID,
        GOOGLE_CLIENT_SECRET,
        GOOGLE_REDIRECT_URI,
        _client_config,
        _pending_flows,
    )

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
    if response_type != "code":
        raise HTTPException(status_code=400, detail="unsupported_response_type")
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="unsupported_code_challenge_method")
    if not redirect_uri:
        raise HTTPException(status_code=400, detail="redirect_uri required")
    if not code_challenge:
        raise HTTPException(status_code=400, detail="PKCE code_challenge required")

    # Persist the MCP OAuth request; get back the google_state to use
    google_state = store_mcp_flow(
        redirect_uri=redirect_uri,
        original_state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        client_id=client_id,
    )

    # Build the Google OAuth URL using google_state as the state param
    flow = Flow.from_client_config(_client_config(), scopes=AUTH_SCOPES)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    auth_url, _ = flow.authorization_url(
        state=google_state,
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    # Store Google PKCE code_verifier so the callback can complete the exchange
    _pending_flows[google_state] = flow.code_verifier or ""

    return RedirectResponse(url=str(auth_url))


@router.post("/oauth/token", include_in_schema=False)
async def oauth_token(
    grant_type: str = Form(...),
    code: str = Form(...),
    code_verifier: str = Form(...),
    client_id: str = Form(default=""),
    redirect_uri: str = Form(default=""),
) -> JSONResponse:
    """Exchange an authorization code for a JWT bearer token (RFC 6749 + PKCE)."""
    from ..routers.auth import _create_jwt

    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="unsupported_grant_type")

    entry = pop_auth_code(code)
    if entry is None:
        raise HTTPException(status_code=400, detail="invalid_grant")

    # Validate PKCE S256: base64url(sha256(code_verifier)) == code_challenge
    if entry.code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="unsupported_code_challenge_method")

    digest = hashlib.sha256(code_verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    if computed != entry.code_challenge:
        raise HTTPException(status_code=400, detail="invalid_grant")

    access_token = _create_jwt(entry.user_id, entry.email)
    return JSONResponse({"access_token": access_token, "token_type": "bearer"})
