"""JWT session authentication for Reli.

Provides require_user() dependency that decodes the JWT from the session cookie
and returns the user_id. Used as a FastAPI dependency on all protected routes.
"""

import jwt
from fastapi import HTTPException, Request, status

from .settings import settings

SECRET_KEY = settings.secret_key
JWT_ALGORITHM = "HS256"
COOKIE_NAME = "reli_session"


async def require_user(request: Request) -> str:
    """FastAPI dependency that validates the session cookie and returns user_id.

    Returns the user_id (sub claim) from the JWT.
    Raises 401 if the cookie is missing, expired, or invalid.
    """
    if not SECRET_KEY:
        # No SECRET_KEY configured — auth is disabled, allow all requests.
        # This preserves backward compatibility for local development.
        return ""

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


def user_filter(user_id: str, table_alias: str = "") -> tuple[str, list[str]]:
    """Return a SQL WHERE fragment and params to filter by user_id.

    When user_id is empty (auth disabled), returns empty filter.
    Usage: sql += user_filter_sql; params.extend(user_filter_params)
    """
    if not user_id:
        return "", []
    prefix = f"{table_alias}." if table_alias else ""
    return f" AND ({prefix}user_id = ? OR {prefix}user_id IS NULL)", [user_id]
