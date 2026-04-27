"""OAuth 2.1 endpoints for MCP client authentication.

Implements the MCP Authorization spec (https://modelcontextprotocol.io/specification/draft/basic/authorization):
  - GET  /.well-known/oauth-protected-resource   (RFC 9728)
  - GET  /.well-known/oauth-authorization-server (RFC 8414)
  - GET  /oauth/authorize  — redirect to Google, then back to client with auth code
  - POST /oauth/token      — exchange auth code + PKCE verifier for JWT
  - POST /oauth/register   — dynamic client registration (RFC 7591)
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..config import settings
from ..oauth_state import (
    cleanup_and_pop,
    cleanup_and_store,
    mcp_auth_codes,
    mcp_oauth_sessions,
    mcp_refresh_tokens,
    mcp_registered_clients,
)
from .auth import AUTH_SCOPES, GOOGLE_REDIRECT_URI, JWT_EXPIRY_SECONDS, _client_config, _create_jwt

logger = logging.getLogger(__name__)

router = APIRouter(tags=["oauth"])

AUTH_CODE_TTL_SECONDS = 60 * 10  # 10 minutes


def _base_url() -> str:
    """Return the application base URL (scheme + host, no trailing slash)."""
    if settings.RELI_BASE_URL:
        return settings.RELI_BASE_URL.rstrip("/")
    # Derive from the Google auth redirect URI by stripping the path
    uri = settings.GOOGLE_AUTH_REDIRECT_URI  # e.g. https://reli.example.com/api/auth/google/callback
    parts = uri.split("/")
    return "/".join(parts[:3])  # scheme://host


# ---------------------------------------------------------------------------
# RFC 9728: Protected Resource Metadata
# ---------------------------------------------------------------------------


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
def protected_resource_metadata() -> JSONResponse:
    base = _base_url()
    return JSONResponse(
        {
            "resource": f"{base}/mcp/",
            "authorization_servers": [base],
            "scopes_supported": ["mcp"],
        }
    )


# ---------------------------------------------------------------------------
# RFC 8414: Authorization Server Metadata
# ---------------------------------------------------------------------------


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
def authorization_server_metadata() -> JSONResponse:
    base = _base_url()
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["mcp"],
        }
    )


# ---------------------------------------------------------------------------
# RFC 7591: Dynamic Client Registration
# ---------------------------------------------------------------------------


@router.post("/oauth/register", include_in_schema=False)
async def oauth_register(request: Request) -> JSONResponse:
    """Register a new OAuth client dynamically (RFC 7591).

    Single-tenant: accepts any registration request and stores the client
    in memory. No approval flow needed.
    """
    body = await request.json()

    client_id = str(uuid.uuid4())
    client_secret = secrets.token_urlsafe(32)

    client = {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uris": body.get("redirect_uris", []),
        "client_name": body.get("client_name", ""),
        "grant_types": body.get("grant_types", ["authorization_code"]),
        "response_types": body.get("response_types", ["code"]),
        "token_endpoint_auth_method": body.get("token_endpoint_auth_method", "client_secret_post"),
        "scope": body.get("scope", "mcp"),
    }
    cleanup_and_store(mcp_registered_clients, client_id, client)

    logger.info("MCP OAuth: registered client %s (%s)", client_id, client.get("client_name"))

    return JSONResponse(
        content={
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": client["redirect_uris"],
            "client_name": client["client_name"],
            "grant_types": client["grant_types"],
            "response_types": client["response_types"],
            "token_endpoint_auth_method": client["token_endpoint_auth_method"],
            "scope": client["scope"],
        },
        status_code=201,
    )


# ---------------------------------------------------------------------------
# Authorization endpoint
# ---------------------------------------------------------------------------


@router.get("/oauth/authorize", include_in_schema=False)
def oauth_authorize(
    client_id: str = "",
    redirect_uri: str = "",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    scope: str = "mcp",
    response_type: str = "code",
) -> RedirectResponse:
    """Receive MCP client OAuth params, start Google login, redirect back with auth code."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
    if not settings.SECRET_KEY:
        raise HTTPException(status_code=501, detail="SECRET_KEY not configured")
    if response_type != "code":
        raise HTTPException(status_code=400, detail="Only response_type=code is supported")
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="Only code_challenge_method=S256 is supported")
    if not redirect_uri:
        raise HTTPException(status_code=400, detail="redirect_uri is required")
    registered = mcp_registered_clients.get(client_id)
    if not registered:
        raise HTTPException(status_code=400, detail="Unknown client_id — register first via POST /oauth/register")
    if redirect_uri not in registered.get("redirect_uris", []):
        raise HTTPException(status_code=400, detail="redirect_uri not registered for this client")
    if not code_challenge:
        raise HTTPException(status_code=400, detail="code_challenge is required (PKCE required)")

    from google_auth_oauthlib.flow import Flow

    server_state = secrets.token_urlsafe(32)
    flow = Flow.from_client_config(_client_config(), scopes=AUTH_SCOPES)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=server_state,
    )

    cleanup_and_store(
        mcp_oauth_sessions,
        server_state,
        {
            "client_state": state,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "client_id": client_id,
            "scope": scope,
            "google_code_verifier": flow.code_verifier or "",
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=AUTH_CODE_TTL_SECONDS),
        },
    )

    return RedirectResponse(url=str(auth_url), status_code=302)


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------


REFRESH_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


def _issue_token_response(user_id: str, email: str, client_id: str, scope: str) -> JSONResponse:
    """Create an access token + refresh token and return the RFC 6749 token response."""
    access_token = _create_jwt(user_id, email)

    refresh_token = secrets.token_urlsafe(32)
    cleanup_and_store(
        mcp_refresh_tokens,
        refresh_token,
        {
            "user_id": user_id,
            "email": email,
            "client_id": client_id,
            "scope": scope,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS),
        },
    )

    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": JWT_EXPIRY_SECONDS,
            "refresh_token": refresh_token,
            "scope": scope,
        }
    )


@router.post("/oauth/token", include_in_schema=False)
async def oauth_token(
    grant_type: str = Form(...),
    code: str = Form(default=""),
    redirect_uri: str = Form(default=""),
    client_id: str = Form(default=""),
    code_verifier: str = Form(default=""),
    refresh_token: str = Form(default=""),
) -> JSONResponse:
    """Exchange authorization code or refresh token for a JWT bearer token."""
    if grant_type == "refresh_token":
        if not refresh_token:
            raise HTTPException(status_code=400, detail="refresh_token is required")
        session = cleanup_and_pop(mcp_refresh_tokens, refresh_token)
        if not session:
            raise HTTPException(status_code=400, detail="Invalid or expired refresh_token")
        if datetime.now(timezone.utc) > session["expires_at"]:
            raise HTTPException(status_code=400, detail="Refresh token expired")
        return _issue_token_response(session["user_id"], session["email"], session["client_id"], session["scope"])

    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="Unsupported grant_type")

    session = cleanup_and_pop(mcp_auth_codes, code)
    if not session:
        raise HTTPException(status_code=400, detail="Invalid or expired authorization code")

    if datetime.now(timezone.utc) > session["expires_at"]:
        raise HTTPException(status_code=400, detail="Authorization code expired")

    if redirect_uri != session["redirect_uri"]:
        raise HTTPException(status_code=400, detail="redirect_uri mismatch")

    if session.get("code_challenge_method") == "S256":
        if not code_verifier:
            raise HTTPException(status_code=400, detail="code_verifier is required")
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        if computed != session["code_challenge"]:
            raise HTTPException(status_code=400, detail="PKCE verification failed")

    return _issue_token_response(
        session["user_id"],
        session["email"],
        client_id,
        session.get("scope", "mcp"),
    )
