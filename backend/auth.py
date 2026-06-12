"""JWT session authentication for Reli.

Provides require_user() dependency that decodes the JWT from the session cookie
(or Bearer token) and returns the user_id.  Used as a FastAPI dependency on all
protected routes.

Two auth methods are supported:
1. Session cookie (``reli_session``) — used by the web UI (Google OAuth flow).
2. Bearer token (``Authorization: Bearer <RELI_API_TOKEN>``) — used by the MCP
   server and other programmatic clients.  When RELI_API_TOKEN is set and the
   request carries a matching Bearer token, the request is authenticated as the
   user specified by RELI_API_TOKEN_USER_ID (or the first user in the database
   if that setting is empty — single-tenant shortcut).
"""

import logging
import random
import secrets
from datetime import datetime, timezone

import jwt
from fastapi import HTTPException, Request, status
from sqlmodel import Session, select

import backend.db_engine as _engine_mod

from .config import settings
from .db_models import RevokedTokenRecord, UserRecord

_log = logging.getLogger(__name__)

SECRET_KEY = settings.SECRET_KEY
JWT_ALGORITHM = "HS256"
COOKIE_NAME = "reli_session"
_API_TOKEN: str = settings.RELI_API_TOKEN
_API_TOKEN_USER_ID: str = settings.RELI_API_TOKEN_USER_ID


def _resolve_api_token_user() -> str:
    """Return the user_id for API-token authenticated requests.

    If RELI_API_TOKEN_USER_ID is configured, returns that user_id directly.
    Otherwise falls back to the first user in the database (single-tenant shortcut).
    Returns "" if no user can be resolved (falls through to auth-disabled path).
    """
    if _API_TOKEN_USER_ID:
        return _API_TOKEN_USER_ID

    try:
        with Session(_engine_mod.engine) as session:
            record = session.exec(
                select(UserRecord).order_by(UserRecord.created_at).limit(1)  # type: ignore[arg-type]
            ).first()
            return record.id if record else ""
    except Exception:
        _log.warning(
            "Bearer token auth: DB lookup failed, returning empty user_id",
            exc_info=True,
        )
        return ""


def _prune_expired_revocations(db: Session) -> None:
    """Delete expired rows from the revocation table (non-fatal; called opportunistically)."""
    try:
        now = datetime.now(timezone.utc)
        expired = db.exec(select(RevokedTokenRecord).where(RevokedTokenRecord.expires_at <= now)).all()
        for row in expired:
            db.delete(row)
        if expired:
            db.commit()
    except Exception:
        _log.warning("Revocation prune failed (non-fatal)", exc_info=True)


async def require_user(request: Request) -> str:
    """FastAPI dependency that validates the session cookie and returns user_id.

    Returns the user_id (sub claim) from the JWT.
    Raises 401 if the cookie is missing, expired, or invalid.
    """
    if not SECRET_KEY and not _API_TOKEN:
        # No SECRET_KEY and no API token configured — auth is disabled.
        return ""

    # --- Bearer token auth (MCP / programmatic clients) ---
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer ") and _API_TOKEN:
        provided = auth_header[7:]
        if secrets.compare_digest(provided, _API_TOKEN):
            return _resolve_api_token_user()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token",
        )

    if not SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # --- Cookie-based JWT auth (web UI) ---
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM], audience="web")
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        )

    user_id: str = payload.get("sub", "")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session payload",
        )

    # Check revocation blacklist (only for tokens that carry a jti claim)
    jti: str = payload.get("jti", "")
    if jti:
        try:
            with Session(_engine_mod.engine) as db:
                if random.random() < 0.01:
                    _prune_expired_revocations(db)
                revoked = db.get(RevokedTokenRecord, jti)
        except Exception:
            # SECURITY TRADEOFF: fail open to preserve availability during DB outages.
            # Consequence: a revoked token may pass this check if the DB is unreachable.
            # The token will still expire naturally (JWT exp claim).
            revoked = None
            _log.warning("Revocation check failed; allowing request", exc_info=True)

        if revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session revoked",
            )

    return user_id
