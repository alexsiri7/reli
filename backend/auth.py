"""The JWTs Reli mints, the allowlist that decides who gets one, Google's callback, and the web session.

Identity is the Google account: a token's ``sub`` is Google's ``sub`` and its ``email`` is the
allowlisted address. There is no users table — v4 has one ``#User`` Thing and nothing to attach a
second identity to — so the identity lives in the token and in the flow tables that carry it
between the callback and ``POST /oauth/token``.

``GET /api/auth/google/callback`` is the one address Google sends a browser back to, for the MCP
flow of :mod:`backend.mcp_oauth` and for the web view's sign-in that starts at
``GET /api/auth/google``. It resolves ``state`` against the two session stores in
:mod:`backend.oauth_state`: a web state ends in the ``__Host-reli_session`` cookie and a redirect
to ``/``, an MCP state in an authorization code delivered to the client — but only in the browser
that approved it on the consent page — and a state neither knows is a 400.

The web session is that cookie: an ``aud="web"`` JWT the middleware in :mod:`backend.api` decodes
on every ``/api`` request, read through :func:`web_session` so the middleware and
``GET /api/auth/me`` cannot disagree about it. Logout deletes the cookie and records the token's
``jti`` in ``revoked_tokens`` until the token expires, so a copy kept elsewhere dies with the
session (#1699); :func:`is_revoked` is that list's one reading, for ``/api`` and ``/mcp`` alike.
"""

from __future__ import annotations

import contextlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session
from starlette.responses import Response

from . import google_login
from .config import settings
from .db_engine import open_session as open_db_session
from .oauth_state import (
    StoreFullError,
    cleanup_and_get,
    cleanup_and_pop,
    cleanup_and_store,
    mcp_auth_codes,
    mcp_oauth_sessions,
    revoked_tokens,
    web_oauth_sessions,
)

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
MCP_AUDIENCE = "mcp"
WEB_AUDIENCE = "web"
WEB_JWT_EXPIRY_SECONDS = 60 * 60 * 24 * 7
# Short because nothing revokes a minted MCP JWT: revoking a refresh-token family stops the next
# refresh, and the hour is how long an access token already in the wrong hands outlives that.
# The connector refreshes transparently, so the user never sees the turnover.
MCP_JWT_EXPIRY_SECONDS = 60 * 60
_EXPIRY_SECONDS_BY_AUDIENCE = {WEB_AUDIENCE: WEB_JWT_EXPIRY_SECONDS, MCP_AUDIENCE: MCP_JWT_EXPIRY_SECONDS}
# RFC 6819 §4.1.1: an authorization code lives just long enough to be exchanged.
MCP_AUTH_CODE_TTL_SECONDS = 60
# A web sign-in that takes longer than this answers "start again", which is the remedy.
WEB_SIGN_IN_TTL_SECONDS = 60 * 10
# The ``__Host-`` prefix has the browser refuse the cookie unless it arrives ``Secure``, with
# ``Path=/`` and no ``Domain`` — the contract both call sites below meet.
SESSION_COOKIE = "__Host-reli_session"
# Binds an MCP sign-in to the browser that approved it on the consent page (#1701): the callback
# honours an MCP state only alongside this cookie naming it. Same ``__Host-`` contract as above.
MCP_FLOW_COOKIE = "__Host-reli_mcp_flow"

#: Every setting the Google sign-in needs; an empty one — or a ``SECRET_KEY`` too short to sign
#: with — closes the sign-in with a 501 naming it.
SIGN_IN_SETTINGS: tuple[str, ...] = (
    "SECRET_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_AUTH_REDIRECT_URI",
    "ALLOWED_EMAILS",
)

_INVITE_ONLY = "This Reli is invite-only: sign in with the Google account listed in ALLOWED_EMAILS on the deploy."
_ACCOUNT_NOT_ALLOWED = "Account is not allowed: " + _INVITE_ONLY
_NOT_SIGNED_IN = "Not signed in: sign in with Google at /."
_SESSION_EXPIRED = "Session expired: sign in with Google at / again."
_SESSION_INVALID = "Invalid session: sign in with Google at / again."
_SESSION_REVOKED = "Session revoked: sign in with Google at / again."
_AT_CAPACITY = "Server is at capacity; try again later"
_CROSS_ORIGIN = "Refused: this request did not come from Reli's own page."
_NOT_THIS_BROWSER = "Sign-in was not approved from this browser: start again from the connector."


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


def is_same_origin(request: Request) -> bool:
    """Whether the request came from a page Reli served.

    A browser sends ``Origin`` on every POST, same-origin included, and never lets script override
    it, so it tells Reli's own page apart from any other — a sibling subdomain included, which the
    session cookie's ``SameSite=Lax`` treats as the same site and lets through (#1698).
    """
    return request.headers.get("origin") == base_url()


def require_same_origin(request: Request) -> None:
    """Refuse a cookie-authenticated write a page other than Reli's own sent."""
    if not is_same_origin(request):
        raise HTTPException(status_code=403, detail=_CROSS_ORIGIN)


def _sign_in_setting_present(name: str) -> bool:
    if name == "SECRET_KEY":
        return settings.secret_key_configured
    return bool(getattr(settings, name))


def missing_sign_in_settings() -> list[str]:
    """The names in ``SIGN_IN_SETTINGS`` that are empty, read per call so a value set later is seen.

    ``SECRET_KEY`` is also missing when it is shorter than ``MIN_SECRET_KEY_BYTES``: a key that
    short signs brute-forceable tokens, so it closes the sign-in as an empty one does (#1534).
    """
    return [name for name in SIGN_IN_SETTINGS if not _sign_in_setting_present(name)]


def not_configured_detail(missing: list[str]) -> str:
    """The one sentence every 501 uses. The names are not secrets: this repository is public."""
    return (
        f"Google sign-in is not configured on this deploy: a human sets {', '.join(missing)} "
        "(CLAUDE.md, Google sign-in)."
    )


def is_allowed(email: str) -> bool:
    return email.lower() in settings.allowed_emails


def create_jwt(subject: str, email: str, audience: str) -> str:
    """A token for *subject*, only for *audience*, good for ``MCP_JWT_EXPIRY_SECONDS`` or
    ``WEB_JWT_EXPIRY_SECONDS`` as *audience* says, issued by this deploy's ``base_url()`` and named
    by the ``jti`` that :func:`is_revoked` looks up.
    """
    issued_at = int(datetime.now(UTC).timestamp())
    claims = {
        "iss": base_url(),
        "sub": subject,
        "email": email,
        "aud": audience,
        "iat": issued_at,
        "exp": issued_at + _EXPIRY_SECONDS_BY_AUDIENCE[audience],
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str, audience: str) -> dict[str, Any]:
    """The claims of a token this Reli minted for *audience*.

    ``iss`` is checked against ``base_url()`` so that another deploy sharing ``SECRET_KEY`` — staging
    beside production — cannot mint a token this one accepts (#1697).

    Raises:
        jwt.ExpiredSignatureError: The token is past its ``exp``.
        jwt.InvalidTokenError: Anything else — wrong signature, audience or issuer, missing claims.
    """
    claims: dict[str, Any] = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[JWT_ALGORITHM],
        audience=audience,
        issuer=base_url(),
        options={"require": ["exp", "aud", "iss", "sub", "jti"]},
    )
    return claims


def is_revoked(claims: dict[str, Any]) -> bool:
    """Whether logout ended the token *claims* were decoded from."""
    with open_db_session() as session:
        return cleanup_and_get(session, revoked_tokens, str(claims["jti"])) is not None


def _revoke(claims: dict[str, Any]) -> None:
    """Put the token *claims* were decoded from on the revocation list until its own ``exp``.

    Raises:
        StoreFullError: ``revoked_tokens`` holds ``MAX_ENTRIES`` live rows.
    """
    with open_db_session() as session:
        cleanup_and_store(
            session, revoked_tokens, str(claims["jti"]), {"expires_at": datetime.fromtimestamp(claims["exp"], UTC)}
        )


class SessionRefused(Exception):
    """A ``__Host-reli_session`` cookie was presented and did not admit the request. The message is the remedy."""


def web_session(request: Request) -> dict[str, Any] | None:
    """The claims of the request's ``__Host-reli_session`` cookie, or ``None`` when it carries none.

    Raises:
        SessionRefused: The cookie is there but expired, not this Reli's, unverifiable because
            ``SECRET_KEY`` is empty or too short, names an account no longer in
            ``ALLOWED_EMAILS``, or was ended by logout — each with the sentence a person should see.
    """
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        return None
    if not settings.secret_key_configured:
        raise SessionRefused(not_configured_detail(["SECRET_KEY"]))
    try:
        claims = decode_jwt(token, WEB_AUDIENCE)
    except jwt.ExpiredSignatureError as expired:
        raise SessionRefused(_SESSION_EXPIRED) from expired
    except jwt.InvalidTokenError as invalid:
        raise SessionRefused(_SESSION_INVALID) from invalid
    if not is_allowed(str(claims.get("email", ""))):
        raise SessionRefused(_INVITE_ONLY)
    if is_revoked(claims):
        raise SessionRefused(_SESSION_REVOKED)
    return claims


def client_redirect(redirect_uri: str, client_state: str, **params: str) -> RedirectResponse:
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
    with open_db_session() as session:
        cleanup_and_store(
            session,
            web_oauth_sessions,
            state,
            {
                "google_code_verifier": code_verifier,
                "expires_at": datetime.now(UTC) + timedelta(seconds=WEB_SIGN_IN_TTL_SECONDS),
            },
        )

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


@router.post("/logout", include_in_schema=False, status_code=204, dependencies=[Depends(require_same_origin)])
def logout(request: Request) -> Response:
    """Delete the cookie and revoke the token it carries, so a copy of it kept elsewhere stops working too.

    A cookie this Reli cannot verify is deleted without a revocation: nothing would accept it anyway.
    """
    token = request.cookies.get(SESSION_COOKIE, "")
    claims = None
    if token and settings.secret_key_configured:
        with contextlib.suppress(jwt.InvalidTokenError):
            claims = decode_jwt(token, WEB_AUDIENCE)
    if claims is not None:
        try:
            _revoke(claims)
        except StoreFullError as full:
            logger.warning("Logout refused: %s", full)
            raise HTTPException(status_code=503, detail=_AT_CAPACITY) from full
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=True)
    return response


def _finish_web_sign_in(flow: dict[str, Any], code: str, error: str) -> RedirectResponse:
    """The web branch of the callback: a cookie and ``/``, or ``/?error=`` with why not.

    A Google refusal at the exchange is the one outcome answered in place, as a 502 whose detail
    names the human step: the view turns only known codes from its URL into text, never a sentence
    the URL supplies.
    """
    if error:
        logger.info("Web sign-in cancelled at Google (%r)", error)
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
        max_age=WEB_JWT_EXPIRY_SECONDS,
        path="/",
        httponly=True,
        samesite="lax",
        secure=True,
    )
    return response


def _finish_mcp_sign_in(session: Session, flow: dict[str, Any], code: str, error: str) -> RedirectResponse:
    """The MCP branch of the callback: an authorization code delivered to the client, or why not.

    A cancelled sign-in or an account outside the allowlist is delivered to the client's redirect
    URI as an ``access_denied`` error (RFC 6749 §4.1.2.1), because that is where the person is.
    """
    if error:
        logger.info("MCP sign-in cancelled at Google (%r)", error)
        return client_redirect(
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
        return client_redirect(
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

    logger.info("MCP sign-in complete for client %r, redirecting to %r", flow["client_id"], flow["redirect_uri"])
    return client_redirect(flow["redirect_uri"], flow["client_state"], code=auth_code)


@router.get("/google/callback", include_in_schema=False)
def google_callback(request: Request, code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    """Where Google sends the browser after the sign-in, for better or worse.

    A web sign-in ends here with the session cookie and a redirect to ``/``, or at ``/?error=``.

    The MCP flow ends here with a short-lived authorization code delivered to the client's
    redirect URI (RFC 6749 §4.1.2); a cancelled sign-in or an account outside the allowlist is
    delivered there too, as an ``access_denied`` error (§4.1.2.1), because the client's redirect
    URI is where the person actually is.

    The MCP branch is honoured only in the browser that clicked Continue on that flow's consent
    page, which set ``MCP_FLOW_COOKIE`` to its state. Anywhere else it is a 400 in place, never a
    redirect: an attacker can read their own client's state off their own consent page, and a
    callback link built from it would otherwise send whoever opened it to the attacker's redirect
    URI (#1701).
    """
    with open_db_session() as session:
        web_flow = cleanup_and_pop(session, web_oauth_sessions, state)
        if web_flow is not None:
            return _finish_web_sign_in(web_flow, code, error)

        flow = cleanup_and_pop(session, mcp_oauth_sessions, state)
        if flow is None:
            raise HTTPException(status_code=400, detail="Invalid or expired sign-in state: start the sign-in again.")
        # Not compare_digest: it raises on the non-ASCII state an attacker can put in the URL.
        if request.cookies.get(MCP_FLOW_COOKIE) != state:
            logger.warning(
                "MCP sign-in refused: the callback reached a browser that did not approve client %r", flow["client_id"]
            )
            raise HTTPException(status_code=400, detail=_NOT_THIS_BROWSER)
        response = _finish_mcp_sign_in(session, flow, code, error)
    response.delete_cookie(MCP_FLOW_COOKIE, path="/", httponly=True, samesite="lax", secure=True)
    return response
