"""JWT session authentication for Reli.

Provides require_user() dependency that decodes the JWT from the session cookie
(or Bearer token) and returns the user_id.  Used as a FastAPI dependency on all
protected routes.

Two auth methods are supported:
1. Session cookie (``reli_session``) — used by the web UI (Google OAuth flow).
2. Bearer token (``Authorization: Bearer <RELI_API_TOKEN>``) — used by the MCP
   server and other programmatic clients.  When RELI_API_TOKEN is set and the
   request carries a matching Bearer token, the request is authenticated as the
   first user in the database (single-tenant shortcut).
"""

import jwt
from fastapi import HTTPException, Request, status

from .config import settings

SECRET_KEY = settings.SECRET_KEY
JWT_ALGORITHM = "HS256"
COOKIE_NAME = "reli_session"
_API_TOKEN: str = settings.RELI_API_TOKEN


def _resolve_api_token_user() -> str:
    """Return the user_id for API-token authenticated requests.

    For single-tenant deployments the token represents the sole user.
    Returns the first user_id found in the database, or "" if none exist
    (which falls through to the auth-disabled path).
    """
    from sqlmodel import Session, select

    import backend.db_engine as _engine_mod

    from .db_models import UserRecord

    try:
        with Session(_engine_mod.engine) as session:
            record = session.exec(
                select(UserRecord).order_by(UserRecord.created_at).limit(1)  # type: ignore[arg-type]
            ).first()
            return record.id if record else ""
    except Exception:
        return ""


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
        if provided == _API_TOKEN:
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
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
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

    return user_id
