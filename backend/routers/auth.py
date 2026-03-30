"""Google OAuth2 login + JWT session authentication."""

import json
import logging
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from google_auth_oauthlib.flow import Flow

from sqlmodel import Session

import backend.db_engine as _engine_mod
from ..db_models import UserRecord, ThingRecord

from ..config import settings
from ..oauth_state import (
    cleanup_and_get,
    cleanup_and_pop,
    cleanup_and_store,
    mcp_auth_codes,
    mcp_oauth_sessions,
)
from ..vector_store import upsert_thing

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
_pending_flows_lock = threading.Lock()

MCP_AUTH_CODE_TTL_SECONDS = 60 * 10  # 10 minutes


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
    now = datetime.now(timezone.utc)
    user_id: str
    with Session(_engine_mod.engine) as session:
        from sqlmodel import select
        existing = session.exec(
            select(UserRecord).where(UserRecord.google_id == google_id)
        ).first()
        if existing:
            user_id = existing.id
            existing.email = email
            existing.name = name
            existing.picture = picture
            existing.updated_at = now
            session.add(existing)
            session.commit()
        else:
            user_id = f"u-{uuid.uuid4().hex[:12]}"
            user_record = UserRecord(
                id=user_id,
                email=email,
                google_id=google_id,
                name=name,
                picture=picture,
                created_at=now,
                updated_at=now,
            )
            session.add(user_record)
            session.commit()
            _create_user_thing_sqlmodel(session, user_id, name, email, google_id, now)
    return user_id


def _create_user_thing_sqlmodel(
    session: Session, user_id: str, name: str, email: str, google_id: str, now: datetime
) -> None:
    """Create a Thing representing the user as their anchor node. SQLModel version."""
    record = ThingRecord(
        title=name,
        type_hint="person",
        importance=2,
        active=True,
        surface=False,
        data={"email": email, "google_id": google_id},
        created_at=now,
        updated_at=now,
        user_id=user_id,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    try:
        upsert_thing(record.model_dump())
    except Exception:
        logger.warning("Failed to index user Thing %s in vector store", record.id)


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
    with _pending_flows_lock:
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

    # Restore PKCE code_verifier from the auth request.
    # For MCP OAuth flows the verifier is stored in mcp_oauth_sessions instead.
    with _pending_flows_lock:
        code_verifier = _pending_flows.pop(state, None)
    if not code_verifier:
        mcp_session = cleanup_and_get(mcp_oauth_sessions, state)
        if mcp_session:
            code_verifier = mcp_session.get("google_code_verifier", "")
    if code_verifier:
        flow.code_verifier = code_verifier

    # Google returns scopes in expanded URI form; tell oauthlib to accept it
    import os as _os

    _os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

    try:
        flow.fetch_token(code=code)
    except Exception:
        logger.exception("Google OAuth callback failed")
        raise HTTPException(status_code=502, detail="Authentication failed. Please try again.")

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

    # Enforce invite-only allowlist
    allowed = settings.allowed_emails_set
    if allowed and email.lower() not in allowed:
        logger.warning("OAuth rejected: %s not in ALLOWED_EMAILS", email)
        return RedirectResponse(url="/?error=invite_only")

    user_id = _upsert_user(google_id, email, name, picture)

    # Detect MCP OAuth flow: state was generated by /oauth/authorize
    mcp_session = cleanup_and_pop(mcp_oauth_sessions, state)
    if mcp_session:
        # Issue a short-lived auth code for the MCP client to exchange
        auth_code = secrets.token_urlsafe(32)
        cleanup_and_store(mcp_auth_codes, auth_code, {
            "user_id": user_id,
            "email": email,
            "code_challenge": mcp_session["code_challenge"],
            "code_challenge_method": mcp_session["code_challenge_method"],
            "redirect_uri": mcp_session["redirect_uri"],
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=MCP_AUTH_CODE_TTL_SECONDS),
        })
        client_redirect = mcp_session["redirect_uri"]
        client_state = mcp_session.get("client_state", "")
        sep = "&" if "?" in client_redirect else "?"
        location = f"{client_redirect}{sep}code={auth_code}"
        if client_state:
            location += f"&state={client_state}"
        logger.info("MCP OAuth: redirecting to client with auth code, redirect_uri=%s", client_redirect)
        return RedirectResponse(url=location, status_code=302)

    # Standard web UI flow: set JWT session cookie
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
    with Session(_engine_mod.engine) as session:
        user = session.get(UserRecord, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
    }


@router.post("/logout", summary="Log out")
def logout(response: Response) -> dict:
    """Clear the session cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"status": "logged_out"}
