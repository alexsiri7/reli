"""The JWTs Reli mints, the allowlist that decides who gets one, Google's callback, and the web session.

Identity is the Google account: a token's ``sub`` is Google's ``sub`` and its ``email`` is the
allowlisted address. There is no users table — v4 has one ``#User`` Thing and nothing to attach a
second identity to — so the identity lives in the token and in the flow tables that carry it
between the callback and ``POST /oauth/token``.

``GET /api/auth/google/callback`` is the one address Google sends a browser back to, for the MCP
flow of :mod:`backend.mcp_oauth` and for the web view's sign-in that starts at
``GET /api/auth/google``. It resolves ``state`` against the two session stores in
:mod:`backend.oauth_state`: a web state ends in the ``reli_session`` cookie and a redirect to
``/``, an MCP state in an authorization code delivered to the client, and a state neither knows is
a 400.

The web session is that cookie: an ``aud="web"`` JWT the middleware in :mod:`backend.api` decodes
on every ``/api`` request, read through :func:`web_session` so the middleware and
``GET /api/auth/me`` cannot disagree about it. Logout deletes the cookie; there is no revocation
list, so a token lives out its seven days if a copy is kept, which the ``httponly`` flag exists to
prevent.
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
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session
from starlette.responses import Response

from . import google_login
from .config import settings
from .db_engine import get_engine
from .oauth_state import (
    StoreFullError,
    cleanup_and_pop,
    cleanup_and_store,
    mcp_auth_codes,
    mcp_oauth_sessions,
    web_oauth_sessions,
)

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = 60 * 60 * 24 * 7
MCP_AUDIENCE = "mcp"
WEB_AUDIENCE = "web"
# RFC 6819 §4.1.1: an authorization code lives just long enough to be exchanged.
MCP_AUTH_CODE_TTL_SECONDS = 60
# A web sign-in that takes longer than this answers "start again", which is the remedy.
WEB_SIGN_IN_TTL_SECONDS = 60 * 10
SESSION_COOKIE = "reli_session"

#: Every setting the Google sign-in needs; an empty one closes the sign-in with a 501 naming it.
SIGN_IN_SETTINGS: tuple[str, ...] = (
    "SECRET_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_AUTH_REDIRECT_URI",
    "ALLOWED_EMAILS",
)

_INVITE_ONLY = "This Reli is invite-only: sign in with the Google account listed in ALLOWED_EMAILS on the deploy."
_NOT_SIGNED_IN = "Not signed in: sign in with Google at /."
_SESSION_EXPIRED = "Session expired: sign in with Google at / again."
_SESSION_INVALID = "Invalid session: sign in with Google at / again."
_AT_CAPACITY = "Server is at capacity; try again later"


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

    ``jti`` is kept from the pre-v4 token shape: nothing reads it, but a revocation list, should
    logout ever need one, would key on it.
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


class SessionRefused(Exception):
    """A ``reli_session`` cookie was presented and did not admit the request. The message is the remedy."""


def web_session(request: Request) -> dict[str, Any] | None:
    """The claims of the request's ``reli_session`` cookie, or ``None`` when it carries none.

    Raises:
        SessionRefused: The cookie is there but expired, not this Reli's, or unverifiable because
            ``SECRET_KEY`` is empty — each with the sentence a person should see.
    """
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        return None
    if not settings.SECRET_KEY:
        raise SessionRefused(not_configured_detail(["SECRET_KEY"]))
    try:
        return decode_jwt(token, WEB_AUDIENCE)
    except jwt.ExpiredSignatureError as expired:
        raise SessionRefused(_SESSION_EXPIRED) from expired
    except jwt.InvalidTokenError as invalid:
        raise SessionRefused(_SESSION_INVALID) from invalid


def _cookie_secure() -> bool:
    """``Secure`` whenever the deploy is reached over https, which the base URL's scheme records."""
    return base_url().startswith("https://")


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


def _sign_in_view(error: str) -> RedirectResponse:
    """Send the browser to the web view's sign-in with a code it turns into a sentence."""
    return RedirectResponse(url=f"/?{urlencode({'error': error})}", status_code=302)


router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignInStart(BaseModel):
    auth_url: str


class SessionOut(BaseModel):
    email: str


@router.get("/google", include_in_schema=False)
def google_sign_in() -> SignInStart:
    """Where to send the browser to sign in to the web view; the sign-in view navigates there.

    Answered as JSON rather than a redirect so the view can show the 501 — naming every empty
    setting — instead of landing on it.
    """
    missing = missing_sign_in_settings()
    if missing:
        logger.error("Web sign-in refused, not configured: %s", ", ".join(missing))
        raise HTTPException(status_code=501, detail=not_configured_detail(missing))

    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    with _session() as session:
        try:
            cleanup_and_store(
                session,
                web_oauth_sessions,
                state,
                {
                    "google_code_verifier": code_verifier,
                    "expires_at": datetime.now(UTC) + timedelta(seconds=WEB_SIGN_IN_TTL_SECONDS),
                },
            )
        except StoreFullError as full:
            logger.warning("Web sign-in refused: %s", full)
            raise HTTPException(status_code=503, detail=_AT_CAPACITY) from full

    return SignInStart(auth_url=google_login.authorization_url(state, code_verifier))


@router.get("/me", include_in_schema=False)
def current_session(request: Request) -> SessionOut:
    """Who the cookie says is signed in: the view's "am I signed in" probe, 401 with the remedy if not."""
    try:
        claims = web_session(request)
    except SessionRefused as refused:
        raise HTTPException(status_code=401, detail=str(refused)) from refused
    if claims is None:
        raise HTTPException(status_code=401, detail=_NOT_SIGNED_IN)
    return SessionOut(email=str(claims.get("email", "")))


@router.post("/logout", include_in_schema=False, status_code=204)
def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=_cookie_secure())
    return response


def _finish_web_sign_in(flow: dict[str, Any], code: str, error: str) -> RedirectResponse:
    """The web branch of the callback: a cookie and ``/``, or ``/?error=`` with why not.

    A Google refusal at the exchange is the one outcome answered in place, as a 502 whose detail
    names the human step: the view turns only known codes from its URL into text, never a sentence
    the URL supplies.
    """
    if error:
        logger.info("Web sign-in cancelled at Google (%s)", error)
        return _sign_in_view("cancelled")

    try:
        identity = google_login.exchange_code(code, flow["google_code_verifier"])
    except google_login.GoogleSignInFailed as failed:
        logger.error("Web sign-in failed at the Google exchange: %s", failed)
        raise HTTPException(status_code=502, detail=str(failed)) from failed

    if not is_allowed(identity.email):
        logger.warning("Google sign-in refused: account not in ALLOWED_EMAILS")
        return _sign_in_view("invite_only")

    logger.info("Web sign-in complete")
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        SESSION_COOKIE,
        create_jwt(identity.subject, identity.email, WEB_AUDIENCE),
        max_age=JWT_EXPIRY_SECONDS,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
    )
    return response


@router.get("/google/callback", include_in_schema=False)
def google_callback(code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    """Where Google sends the browser after the sign-in, for better or worse.

    A web sign-in ends here with the session cookie and a redirect to ``/``, or at ``/?error=``.

    The MCP flow ends here with a short-lived authorization code delivered to the client's
    redirect URI (RFC 6749 §4.1.2); a cancelled sign-in or an account outside the allowlist is
    delivered there too, as an ``access_denied`` error (§4.1.2.1), because the client's redirect
    URI is where the person actually is.
    """
    with _session() as session:
        web_flow = cleanup_and_pop(session, web_oauth_sessions, state)
        if web_flow is not None:
            return _finish_web_sign_in(web_flow, code, error)

        flow = cleanup_and_pop(session, mcp_oauth_sessions, state)
        if flow is None:
            raise HTTPException(status_code=400, detail="Invalid or expired sign-in state: start the sign-in again.")

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
            raise HTTPException(status_code=503, detail=_AT_CAPACITY) from full

        logger.info("MCP sign-in complete, redirecting to client at %s", flow["redirect_uri"])
        return _client_redirect(flow["redirect_uri"], flow["client_state"], code=auth_code)
