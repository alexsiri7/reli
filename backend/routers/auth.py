"""Google OAuth2 login + JWT session authentication."""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from google_auth_oauthlib.flow import Flow

from ..config import settings
from ..database import db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

GOOGLE_CLIENT_ID = settings.GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET = settings.GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI = settings.GOOGLE_AUTH_REDIRECT_URI
AUTH_SCOPES = ["openid", "email", "profile"]

# JWT settings
SECRET_KEY = settings.SECRET_KEY
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = 60 * 60 * 24 * 7  # 7 days
COOKIE_NAME = "reli_session"

# PKCE state storage: state -> code_verifier (single-process, in-memory)
_pending_flows: dict[str, str] = {}


def _client_config() -> dict:
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }


def _create_jwt(user_id: str, email: str) -> str:
    """Create a signed JWT for the given user."""
    import jwt

    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now.timestamp() + JWT_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def _decode_jwt(token: str) -> dict[str, str]:
    """Decode and validate a JWT. Raises on invalid/expired tokens."""
    import jwt

    result: dict[str, str] = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    return result


def _upsert_user(google_id: str, email: str, name: str, picture: str | None) -> str:
    """Create or update a user from Google profile info. Returns user_id."""
    import json

    now = datetime.now(timezone.utc).isoformat()
    user_id: str
    with db() as conn:
        row = conn.execute("SELECT id FROM users WHERE google_id = ?", (google_id,)).fetchone()
        if row:
            user_id = row["id"]
            conn.execute(
                "UPDATE users SET email = ?, name = ?, picture = ?, updated_at = ? WHERE id = ?",
                (email, name, picture, now, user_id),
            )
        else:
            user_id = f"u-{uuid.uuid4().hex[:12]}"
            conn.execute(
                """INSERT INTO users (id, email, google_id, name, picture, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, email, google_id, name, picture, now, now),
            )
            # Auto-create the User Thing — anchor node for all user context
            thing_id = str(uuid.uuid4())
            data_json = json.dumps({"email": email, "google_id": google_id})
            conn.execute(
                """INSERT INTO things
                   (id, title, type_hint, surface, data, created_at, updated_at, user_id)
                   VALUES (?, ?, 'person', 0, ?, ?, ?, ?)""",
                (thing_id, name, data_json, now, now, user_id),
            )
            logger.info("Created User Thing %s for new user %s", thing_id, user_id)
    return user_id


@router.get("/google", summary="Start Google OAuth flow")
def google_login() -> dict:
    """Return the Google OAuth2 authorization URL."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
    if not SECRET_KEY:
        raise HTTPException(status_code=501, detail="SECRET_KEY not configured")

    flow = Flow.from_client_config(_client_config(), scopes=AUTH_SCOPES)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    # Store PKCE code_verifier for the callback
    _pending_flows[state] = flow.code_verifier or ""
    return {"auth_url": str(auth_url)}


@router.get("/google/callback", include_in_schema=False)
def google_callback(code: str, state: str = "") -> RedirectResponse:
    """Exchange authorization code for tokens, create session."""
    if not SECRET_KEY:
        raise HTTPException(status_code=501, detail="SECRET_KEY not configured")

    logger.info("OAuth callback: redirect_uri=%s, code=%s...", GOOGLE_REDIRECT_URI, code[:20])

    flow = Flow.from_client_config(_client_config(), scopes=AUTH_SCOPES)
    flow.redirect_uri = GOOGLE_REDIRECT_URI

    # Restore PKCE code_verifier from the auth request
    code_verifier = _pending_flows.pop(state, None)
    if code_verifier:
        flow.code_verifier = code_verifier

    # Google returns scopes in expanded URI form; tell oauthlib to accept it
    import os as _os

    _os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        logger.error("OAuth token exchange failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Google login failed: {exc}")

    # Verify and extract user info from the id_token
    credentials = flow.credentials
    id_info = google_id_token.verify_oauth2_token(
        credentials.id_token,
        google_requests.Request(),
        GOOGLE_CLIENT_ID,
    )

    google_id = id_info["sub"]
    email = id_info.get("email", "")
    name = id_info.get("name", email)
    picture = id_info.get("picture")

    user_id = _upsert_user(google_id, email, name, picture)
    token = _create_jwt(user_id, email)

    redirect = RedirectResponse(url="/")
    redirect.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=GOOGLE_REDIRECT_URI.startswith("https://"),
        samesite="lax",
        max_age=JWT_EXPIRY_SECONDS,
        path="/",
    )
    return redirect


@router.get("/me", summary="Get current user")
def get_current_user(request: Request) -> dict:
    """Return the current user's profile from their JWT session cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = _decode_jwt(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    user_id = payload.get("sub")
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="User not found")

    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "picture": row["picture"],
    }


@router.post("/logout", summary="Log out")
def logout(response: Response) -> dict:
    """Clear the session cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"status": "logged_out"}
