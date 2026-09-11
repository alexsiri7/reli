"""The OAuth 2.1 authorization server an MCP client authorises against, restored from the pre-v4 tree.

Implements the MCP authorization spec
(https://modelcontextprotocol.io/specification/draft/basic/authorization):

- ``GET  /.well-known/oauth-protected-resource``   — RFC 9728
- ``GET  /.well-known/oauth-authorization-server`` — RFC 8414
- ``POST /oauth/register``                          — RFC 7591 dynamic client registration
- ``GET  /oauth/authorize``                         — sends the browser to Google, then back to the
  client with an authorization code via :func:`backend.auth.google_callback`
- ``POST /oauth/token``                             — code or refresh token for an ``aud="mcp"`` JWT

PKCE is mandatory and only ``S256`` is accepted; refresh tokens rotate on every use, and presenting
one that has already been rotated away revokes every token from that sign-in (OAuth 2.1 §4.3.1), so
the connector re-authorises. The identity step is Google's: a client never holds a shared secret,
and a token is only ever minted for an account in ``ALLOWED_EMAILS``. The JWT is the only
credential ``/mcp`` accepts.
"""

from __future__ import annotations

import logging
import secrets
import urllib.parse
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlmodel import Session

from . import auth, google_login
from .oauth_state import (
    Store,
    StoreFullError,
    cleanup_and_get,
    cleanup_and_pop,
    cleanup_and_store,
    consume_refresh_token,
    mcp_auth_codes,
    mcp_oauth_sessions,
    mcp_refresh_tokens,
    mcp_registered_clients,
    revoke_refresh_token_family,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["oauth"])

# A sign-in that takes longer than this answers "start again", which is the remedy.
SESSION_TTL_SECONDS = 60 * 10
REFRESH_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30
# A client without a live refresh token is useless, so its registration lives exactly as long.
CLIENT_TTL_SECONDS = REFRESH_TOKEN_TTL_SECONDS

_AT_CAPACITY = "Server is at capacity; try again later"
_CODE_GONE = "Authorization code is invalid or expired: re-authorise the connector"
_REFRESH_TOKEN_GONE = "Refresh token is invalid or expired: re-authorise the connector"
# The only client authentication methods /oauth/token implements: a secret arrives in the form
# body or not at all. Registration refuses any other, so a client is never told to authenticate a
# way that would fail.
TOKEN_ENDPOINT_AUTH_METHODS = ("none", "client_secret_post")
_NO_STORE = {"Cache-Control": "no-store"}


# --- Discovery -------------------------------------------------------------


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
def protected_resource_metadata() -> JSONResponse:
    base = auth.base_url()
    return JSONResponse(
        {
            "resource": f"{base}/mcp/",
            "authorization_servers": [base],
            "scopes_supported": ["mcp"],
        }
    )


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
def authorization_server_metadata() -> JSONResponse:
    base = auth.base_url()
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": list(TOKEN_ENDPOINT_AUTH_METHODS),
            "scopes_supported": ["mcp"],
        }
    )


# --- Registration ----------------------------------------------------------


def _redirect_uri_is_safe(uri: str) -> bool:
    parsed = urllib.parse.urlparse(uri)
    return parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1"))


@router.post("/oauth/register", include_in_schema=False)
async def oauth_register(request: Request) -> JSONResponse:
    """Register a client (RFC 7591). Single-tenant: no approval step.

    This is an unauthenticated write, by design — dynamic registration is how a connector that holds
    no credential yet gets one, and the Google sign-in behind ``/oauth/authorize`` is what gates
    identity. What it can cost is bounded: one of a hundred client slots for thirty days, and a 503
    when they are gone. A registration never yields a token.

    Raises:
        HTTPException 400: A ``redirect_uri`` is not ``https`` (``http`` only for localhost), or
            ``token_endpoint_auth_method`` is one the token endpoint does not implement.
        HTTPException 503: The client store is at capacity.
    """
    body: dict[str, Any] = await request.json()

    auth_method: str = body.get("token_endpoint_auth_method", "client_secret_post")
    if auth_method not in TOKEN_ENDPOINT_AUTH_METHODS:
        logger.warning("MCP OAuth: rejected token_endpoint_auth_method during registration: %r", auth_method)
        raise HTTPException(
            status_code=400,
            detail=f"token_endpoint_auth_method must be one of {', '.join(TOKEN_ENDPOINT_AUTH_METHODS)}: {auth_method}",
        )

    redirect_uris: list[str] = body.get("redirect_uris") or []
    for uri in redirect_uris:
        if not _redirect_uri_is_safe(uri):
            logger.warning("MCP OAuth: rejected redirect_uri with unsafe scheme during registration: %r", uri)
            raise HTTPException(
                status_code=400,
                detail=f"redirect_uri must use https (or http://localhost / http://127.0.0.1 for development): {uri}",
            )

    client_id = str(uuid.uuid4())
    client_secret = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(seconds=CLIENT_TTL_SECONDS)
    client = {
        "client_secret": client_secret,
        "redirect_uris": redirect_uris,
        "client_name": body.get("client_name", ""),
        "grant_types": body.get("grant_types", ["authorization_code"]),
        "response_types": body.get("response_types", ["code"]),
        "token_endpoint_auth_method": auth_method,
        "scope": body.get("scope", "mcp"),
        "expires_at": expires_at,
    }
    with auth._session() as session:
        try:
            cleanup_and_store(session, mcp_registered_clients, client_id, client)
        except StoreFullError as full:
            logger.warning("MCP OAuth: client registration rejected — %s", full)
            raise HTTPException(status_code=503, detail=_AT_CAPACITY) from full

    logger.info("MCP OAuth: registered client %s (%s)", client_id, client["client_name"])

    return JSONResponse(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": client["redirect_uris"],
            "client_name": client["client_name"],
            "grant_types": client["grant_types"],
            "response_types": client["response_types"],
            "token_endpoint_auth_method": client["token_endpoint_auth_method"],
            "scope": client["scope"],
            "client_secret_expires_at": int(expires_at.timestamp()),
        },
        status_code=201,
    )


# --- Authorization ---------------------------------------------------------


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
    """Take the client's request, remember it, and send the browser to Google.

    Refuses up front — 501 naming every empty setting — when the sign-in cannot complete, so nobody
    is sent through Google only to be bounced at the callback.
    """
    missing = auth.missing_sign_in_settings()
    if missing:
        logger.error("MCP OAuth: authorize refused, sign-in not configured: %s", ", ".join(missing))
        raise HTTPException(status_code=501, detail=auth.not_configured_detail(missing))
    if response_type != "code":
        raise HTTPException(status_code=400, detail="Only response_type=code is supported")
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="Only code_challenge_method=S256 is supported")
    if not redirect_uri:
        raise HTTPException(status_code=400, detail="redirect_uri is required")
    if not code_challenge:
        raise HTTPException(status_code=400, detail="code_challenge is required (PKCE required)")

    with auth._session() as session:
        registered = cleanup_and_get(session, mcp_registered_clients, client_id)
        if registered is None:
            raise HTTPException(status_code=400, detail="Unknown client_id — register first via POST /oauth/register")
        if redirect_uri not in registered["redirect_uris"]:
            raise HTTPException(status_code=400, detail="redirect_uri not registered for this client")

        server_state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        try:
            cleanup_and_store(
                session,
                mcp_oauth_sessions,
                server_state,
                {
                    "client_state": state,
                    "redirect_uri": redirect_uri,
                    "code_challenge": code_challenge,
                    "code_challenge_method": code_challenge_method,
                    "client_id": client_id,
                    "scope": scope,
                    "google_code_verifier": code_verifier,
                    "expires_at": datetime.now(UTC) + timedelta(seconds=SESSION_TTL_SECONDS),
                },
            )
        except StoreFullError as full:
            logger.warning("MCP OAuth: authorize refused for client %s — %s", client_id, full)
            raise HTTPException(status_code=503, detail=_AT_CAPACITY) from full

    return RedirectResponse(url=google_login.authorization_url(server_state, code_verifier), status_code=302)


# --- Tokens ----------------------------------------------------------------


class _TokenError(Exception):
    """An RFC 6749 §5.2 refusal: ``error_description`` is the field a client is specified to surface."""

    def __init__(self, status: int, error: str, description: str) -> None:
        super().__init__(description)
        self.status = status
        self.error = error
        self.description = description

    def response(self) -> JSONResponse:
        return JSONResponse(
            {"error": self.error, "error_description": self.description}, status_code=self.status, headers=_NO_STORE
        )


def _invalid_grant(description: str) -> _TokenError:
    return _TokenError(400, "invalid_grant", description)


def _validate_client_secret(session: Session, client_id: str, client_secret: str) -> None:
    """A confidential client must present its secret; a public one (``none``) has none to present."""
    client = cleanup_and_get(session, mcp_registered_clients, client_id)
    if client is None:
        raise _TokenError(400, "invalid_client", "Unknown client_id: register again via POST /oauth/register")
    if client["token_endpoint_auth_method"] == "none":
        return
    if not client_secret or not secrets.compare_digest(client_secret, client["client_secret"]):
        raise _TokenError(401, "invalid_client", "Invalid client credentials: re-register the connector")


def _issue_token_response(
    session: Session, subject: str, email: str, client_id: str, scope: str, family_id: str
) -> JSONResponse:
    """An access token and a fresh refresh token, RFC 6749 §5.1, never cached."""
    access_token = auth.create_jwt(subject, email, audience=auth.MCP_AUDIENCE)
    refresh_token = secrets.token_urlsafe(32)
    try:
        cleanup_and_store(
            session,
            mcp_refresh_tokens,
            refresh_token,
            {
                "subject": subject,
                "email": email,
                "client_id": client_id,
                "scope": scope,
                "family_id": family_id,
                "expires_at": datetime.now(UTC) + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS),
            },
        )
    except StoreFullError as full:
        logger.warning("MCP OAuth: token issuance refused for client %s — %s", client_id, full)
        raise HTTPException(status_code=503, detail=_AT_CAPACITY) from full

    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": auth.JWT_EXPIRY_SECONDS,
            "refresh_token": refresh_token,
            "scope": scope,
        },
        headers=_NO_STORE,
    )


def _authenticated_grant(
    session: Session, store: Store, key: str, client_id: str, client_secret: str, gone: str
) -> dict[str, Any]:
    """The grant under *key*, not yet consumed, once the client it was issued to has authenticated.

    The client is authenticated before the grant is consumed (RFC 6749 §3.2.1 puts client
    authentication ahead of processing the grant), so a wrong secret leaves a still-valid code or
    refresh token for its holder to redeem instead of burning it. The grant is bound to the client
    that asked for it, so an injected code exchanges for nothing. Each exchange then consumes the
    grant its own way, and only what that consume returns may mint a token: for a refresh token
    the row found here may already be consumed.

    Raises:
        _TokenError: ``invalid_grant`` when the grant is gone or belongs to another client;
            ``invalid_client`` from :func:`_validate_client_secret`.
    """
    grant = cleanup_and_get(session, store, key)
    if grant is None:
        raise _invalid_grant(gone)
    if not client_id or client_id != grant["client_id"]:
        raise _invalid_grant("client_id mismatch: re-authorise the connector")
    _validate_client_secret(session, client_id, client_secret)
    return grant


def _exchange_refresh_token(session: Session, refresh_token: str, client_id: str, client_secret: str) -> JSONResponse:
    """Rotate *refresh_token*; a token presented twice revokes its whole family.

    Nothing may commit between :func:`consume_refresh_token` and the replacement's
    :func:`cleanup_and_store` inside :func:`_issue_token_response`: the two commit together, which
    is what lets a concurrent redeem of the same token revoke the replacement as well.
    """
    if not refresh_token:
        raise _invalid_grant("refresh_token is required")
    grant = _authenticated_grant(
        session, mcp_refresh_tokens, refresh_token, client_id, client_secret, gone=_REFRESH_TOKEN_GONE
    )
    consumed = consume_refresh_token(session, refresh_token)
    if consumed is None:
        revoked = revoke_refresh_token_family(session, grant["family_id"])
        logger.warning(
            "MCP OAuth: refresh token reuse for client %s — revoked %d token(s) in its family", client_id, revoked
        )
        raise _invalid_grant(
            "Refresh token already used: every token from that sign-in is revoked, re-authorise the connector"
        )
    return _issue_token_response(
        session,
        consumed["subject"],
        consumed["email"],
        consumed["client_id"],
        consumed["scope"],
        family_id=consumed["family_id"],
    )


def _exchange_authorization_code(
    session: Session, code: str, redirect_uri: str, client_id: str, client_secret: str, code_verifier: str
) -> JSONResponse:
    _authenticated_grant(session, mcp_auth_codes, code, client_id, client_secret, gone=_CODE_GONE)
    consumed = cleanup_and_pop(session, mcp_auth_codes, code)
    if consumed is None:
        raise _invalid_grant(_CODE_GONE)
    if redirect_uri != consumed["redirect_uri"]:
        raise _invalid_grant("redirect_uri mismatch: re-authorise the connector")

    if consumed["code_challenge_method"] == "S256":
        if not code_verifier:
            raise _invalid_grant("code_verifier is required")
        if google_login.s256_challenge(code_verifier) != consumed["code_challenge"]:
            raise _invalid_grant("PKCE verification failed: re-authorise the connector")

    return _issue_token_response(
        session,
        consumed["subject"],
        consumed["email"],
        consumed["client_id"],
        consumed["scope"],
        family_id=str(uuid.uuid4()),
    )


@router.post("/oauth/token", include_in_schema=False)
async def oauth_token(
    grant_type: str = Form(...),
    code: str = Form(default=""),
    redirect_uri: str = Form(default=""),
    client_id: str = Form(default=""),
    client_secret: str = Form(default=""),
    code_verifier: str = Form(default=""),
    refresh_token: str = Form(default=""),
) -> JSONResponse:
    """Exchange an authorization code, or rotate a refresh token, for an ``aud="mcp"`` JWT."""
    try:
        with auth._session() as session:
            if grant_type == "refresh_token":
                return _exchange_refresh_token(session, refresh_token, client_id, client_secret)
            if grant_type != "authorization_code":
                raise _TokenError(400, "unsupported_grant_type", "Only authorization_code and refresh_token")
            return _exchange_authorization_code(session, code, redirect_uri, client_id, client_secret, code_verifier)
    except _TokenError as refused:
        return refused.response()
