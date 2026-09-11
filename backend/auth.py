"""The JWTs Reli mints, the allowlist that decides who gets one, and Google's callback.

Identity is the Google account: a token's ``sub`` is Google's ``sub`` and its ``email`` is the
allowlisted address. There is no users table — v4 has one ``#User`` Thing and nothing to attach a
second identity to — so the identity lives in the token and in the two flow tables that carry it
between the callback and ``POST /oauth/token``.

``GET /api/auth/google/callback`` is the one address Google sends a browser back to, for the MCP
flow built here and for the web view's sign-in (#1449) when it lands. Here it resolves ``state``
against the MCP sessions in :mod:`backend.oauth_state` and answers the client; a state it does not
know is a 400.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

import jwt
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from . import google_login
from .config import settings
from .db_engine import get_engine
from .oauth_state import StoreFullError, cleanup_and_pop, cleanup_and_store, mcp_auth_codes, mcp_oauth_sessions

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = 60 * 60 * 24 * 7
MCP_AUDIENCE = "mcp"
# RFC 6819 §4.1.1: an authorization code lives just long enough to be exchanged.
MCP_AUTH_CODE_TTL_SECONDS = 60

#: Every setting the Google sign-in needs; an empty one closes the sign-in with a 501 naming it.
SIGN_IN_SETTINGS: tuple[str, ...] = (
    "SECRET_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_AUTH_REDIRECT_URI",
    "ALLOWED_EMAILS",
)

_INVITE_ONLY = "This Reli is invite-only: sign in with the Google account listed in ALLOWED_EMAILS on the deploy."


def base_url() -> str:
    """The issuer and the base of every absolute URL the authorization server hands out.

    ``RELI_BASE_URL`` when set, else the scheme and host of ``GOOGLE_AUTH_REDIRECT_URI``, else
    ``""`` — which callers treat as "relative".
    """
    if settings.RELI_BASE_URL:
        return settings.RELI_BASE_URL.rstrip("/")
    parts = urlsplit(settings.GOOGLE_AUTH_REDIRECT_URI)
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return ""


def missing_sign_in_settings() -> list[str]:
    """The names in ``SIGN_IN_SETTINGS`` that are empty, read per call so a value set later is seen."""
    return [name for name in SIGN_IN_SETTINGS if not getattr(settings, name)]


def not_configured_detail(missing: list[str]) -> str:
    """The one sentence every 501 uses. The names are not secrets: this repository is public."""
    return (
        f"Google sign-in is not configured on this deploy: a human sets {', '.join(missing)} "
        "(CLAUDE.md, Google sign-in)."
    )


def is_allowed(email: str) -> bool:
    return email.lower() in settings.allowed_emails


def create_jwt(subject: str, email: str, audience: str) -> str:
    """A token for *subject*, good for ``JWT_EXPIRY_SECONDS`` and only for *audience*.

    ``jti`` is kept from the pre-v4 shape because the web view's logout revocation (#1449) keys on it.
    """
    issued_at = int(datetime.now(UTC).timestamp())
    claims = {
        "sub": subject,
        "email": email,
        "aud": audience,
        "iat": issued_at,
        "exp": issued_at + JWT_EXPIRY_SECONDS,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str, audience: str) -> dict[str, Any]:
    """The claims of a token this Reli minted for *audience*.

    Raises:
        jwt.ExpiredSignatureError: The token is past its ``exp``.
        jwt.InvalidTokenError: Anything else — wrong signature, wrong audience, missing claims.
    """
    claims: dict[str, Any] = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[JWT_ALGORITHM],
        audience=audience,
        options={"require": ["exp", "aud", "sub"]},
    )
    return claims


@contextmanager
def _session() -> Iterator[Session]:
    """The session a route here or in :mod:`backend.mcp_oauth` runs in; tests bind it to the fixture session."""
    with Session(get_engine()) as session:
        yield session


def _client_redirect(redirect_uri: str, client_state: str, **params: str) -> RedirectResponse:
    """Send the browser back to the client with *params* and, when the client sent one, its state."""
    query = dict(params)
    if client_state:
        query["state"] = client_state
    separator = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(url=f"{redirect_uri}{separator}{urlencode(query)}", status_code=302)


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/google/callback", include_in_schema=False)
def google_callback(code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    """Where Google sends the browser after the sign-in, for better or worse.

    The MCP flow ends here with a short-lived authorization code delivered to the client's
    redirect URI (RFC 6749 §4.1.2); a cancelled sign-in or an account outside the allowlist is
    delivered there too, as an ``access_denied`` error (§4.1.2.1), because the client's redirect
    URI is where the person actually is.
    """
    with _session() as session:
        flow = cleanup_and_pop(session, mcp_oauth_sessions, state)
        if flow is None:
            raise HTTPException(
                status_code=400, detail="Invalid or expired sign-in state: start the sign-in again from the connector."
            )

        if error:
            logger.info("MCP sign-in cancelled at Google (%s)", error)
            return _client_redirect(
                flow["redirect_uri"],
                flow["client_state"],
                error="access_denied",
                error_description="Google sign-in was cancelled",
            )

        try:
            identity = google_login.exchange_code(code, flow["google_code_verifier"])
        except google_login.GoogleSignInFailed as failed:
            logger.error("MCP sign-in failed at the Google exchange: %s", failed)
            raise HTTPException(status_code=502, detail=str(failed)) from failed

        if not is_allowed(identity.email):
            logger.warning("Google sign-in refused: account not in ALLOWED_EMAILS")
            return _client_redirect(
                flow["redirect_uri"], flow["client_state"], error="access_denied", error_description=_INVITE_ONLY
            )

        auth_code = secrets.token_urlsafe(32)
        try:
            cleanup_and_store(
                session,
                mcp_auth_codes,
                auth_code,
                {
                    "subject": identity.subject,
                    "email": identity.email,
                    "code_challenge": flow["code_challenge"],
                    "code_challenge_method": flow["code_challenge_method"],
                    "redirect_uri": flow["redirect_uri"],
                    "client_id": flow["client_id"],
                    "scope": flow["scope"],
                    "expires_at": datetime.now(UTC) + timedelta(seconds=MCP_AUTH_CODE_TTL_SECONDS),
                },
            )
        except StoreFullError as full:
            logger.warning("MCP sign-in refused: %s", full)
            raise HTTPException(status_code=503, detail="Server is at capacity; try again later") from full

        logger.info("MCP sign-in complete, redirecting to client at %s", flow["redirect_uri"])
        return _client_redirect(flow["redirect_uri"], flow["client_state"], code=auth_code)
