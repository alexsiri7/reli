from sqlmodel import Session

"""Gmail read-only integration: OAuth2 flow and message endpoints."""

import base64
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ..auth import require_user
from ..config import settings
import backend.db_engine as _engine_mod
from ..db_engine import _exec

router = APIRouter(prefix="/gmail", tags=["gmail"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GOOGLE_CLIENT_ID = settings.GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET = settings.GOOGLE_CLIENT_SECRET
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
# Legacy token file path — used only for migration fallback
TOKEN_PATH = Path(settings.DATA_DIR) / "gmail_token.json"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class GmailStatus(BaseModel):
    connected: bool
    email: str | None = None


class GmailMessage(BaseModel):
    id: str
    thread_id: str
    subject: str
    sender: str
    to: str
    date: str
    snippet: str
    body: str | None = None
    labels: list[str] = []


class GmailThread(BaseModel):
    id: str
    subject: str
    messages: list[GmailMessage]


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def _save_token(creds: Any, user_id: str = "") -> None:
    """Persist OAuth2 credentials to the google_tokens table."""
    expiry_str = creds.expiry.isoformat() if creds.expiry else None
    scopes_str = json.dumps(list(creds.scopes)) if creds.scopes else None
    now = datetime.now(timezone.utc).isoformat()
    uid = user_id or None  # Store NULL when auth is disabled (empty string)

    with Session(_engine_mod.engine) as session:
        _exec(session, 
            """INSERT INTO google_tokens (user_id, service, access_token, refresh_token,
               token_uri, client_id, client_secret, expiry, scopes, updated_at)
               VALUES (?, 'gmail', ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, service) DO UPDATE SET
               access_token=excluded.access_token,
               refresh_token=COALESCE(excluded.refresh_token, google_tokens.refresh_token),
               token_uri=excluded.token_uri,
               client_id=excluded.client_id,
               client_secret=excluded.client_secret,
               expiry=excluded.expiry,
               scopes=excluded.scopes,
               updated_at=excluded.updated_at""",
            (
                uid,
                creds.token,
                creds.refresh_token,
                creds.token_uri,
                creds.client_id,
                creds.client_secret,
                expiry_str,
                scopes_str,
                now,
            ),
        )


        session.commit()
def _load_creds(user_id: str = "") -> Any:
    """Load and refresh credentials. Returns None if not connected.

    Checks the google_tokens table first, falls back to legacy gmail_token.json
    for migration, then stores it in the DB.
    """
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.credentials import Credentials

    uid = user_id or None

    # Try DB first — match by user_id (NULL when auth disabled)
    with Session(_engine_mod.engine) as session:
        if uid is None:
            row = _exec(session, "SELECT * FROM google_tokens WHERE user_id IS NULL AND service = 'gmail'").fetchone()
        else:
            row = _exec(session, "SELECT * FROM google_tokens WHERE user_id = ? AND service = 'gmail'", (uid,)).fetchone()

    if row:
        creds = Credentials(
            token=row.access_token,
            refresh_token=row.refresh_token,
            token_uri=row.token_uri,
            client_id=row.client_id,
            client_secret=row.client_secret,
        )
        if row.expiry:
            creds.expiry = datetime.fromisoformat(row.expiry).replace(tzinfo=None)
    elif TOKEN_PATH.exists():
        # Migrate legacy file-based token to DB
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), GMAIL_SCOPES)
        _save_token(creds, user_id=user_id)
        TOKEN_PATH.unlink()  # Remove legacy file after migration
    else:
        return None

    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        _save_token(creds, user_id=user_id)
    if not creds.valid:
        return None
    return creds


def _get_service(user_id: str = "") -> Any:
    """Build Gmail API service. Raises 401 if not connected."""
    creds = _load_creds(user_id=user_id)
    if creds is None:
        raise HTTPException(status_code=401, detail="Gmail not connected. Please authorize first.")
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds)


def _parse_message(msg: dict[str, Any]) -> GmailMessage:
    """Parse a Gmail API message resource into our model."""
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    date_str = headers.get("date", "")
    try:
        dt = parsedate_to_datetime(date_str)
        date_str = dt.isoformat()
    except Exception:
        pass

    body = _extract_body(msg.get("payload", {}))
    labels = msg.get("labelIds", [])

    return GmailMessage(
        id=msg["id"],
        thread_id=msg["threadId"],
        subject=headers.get("subject", "(no subject)"),
        sender=headers.get("from", ""),
        to=headers.get("to", ""),
        date=date_str,
        snippet=msg.get("snippet", ""),
        body=body,
        labels=labels,
    )


def _extract_body(payload: dict[str, Any]) -> str | None:
    """Extract plain-text body from a message payload, walking MIME parts."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        result = _extract_body(part)
        if result:
            return result
    return None


# ---------------------------------------------------------------------------
# OAuth2 endpoints
# ---------------------------------------------------------------------------


@router.get("/status", response_model=GmailStatus, summary="Check Gmail connection status")
def gmail_status(user_id: str = Depends(require_user)) -> GmailStatus:
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Gmail integration not configured (missing GOOGLE_CLIENT_ID)")

    creds = _load_creds(user_id=user_id)
    if creds is None:
        return GmailStatus(connected=False)

    try:
        from googleapiclient.discovery import build

        service = build("gmail", "v1", credentials=creds)
        profile = service.users().getProfile(userId="me").execute()
        return GmailStatus(connected=True, email=profile.get("emailAddress"))
    except Exception:
        return GmailStatus(connected=False)


@router.get("/auth-url", summary="Get Gmail OAuth2 authorization URL")
def gmail_auth_url(request: Request, user_id: str = Depends(require_user)) -> dict[str, str]:
    """Generate the Google OAuth2 consent URL."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Gmail integration not configured")

    from google_auth_oauthlib.flow import Flow

    # Determine redirect URI from request
    redirect_uri = str(request.base_url).rstrip("/") + "/api/gmail/callback"

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=GMAIL_SCOPES,
        redirect_uri=redirect_uri,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return {"auth_url": auth_url}


@router.get("/callback", summary="Handle OAuth2 callback from Google")
def gmail_callback(
    request: Request,
    code: str = Query(...),
    error: str | None = Query(None),
    user_id: str = Depends(require_user),
) -> RedirectResponse:
    """Exchange authorization code for tokens and store them."""
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Gmail integration not configured")

    from google_auth_oauthlib.flow import Flow

    redirect_uri = str(request.base_url).rstrip("/") + "/api/gmail/callback"

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=GMAIL_SCOPES,
        redirect_uri=redirect_uri,
    )
    flow.fetch_token(code=code)
    _save_token(flow.credentials, user_id=user_id)

    # Redirect to the app root after successful auth
    return RedirectResponse(url="/")


@router.delete("/disconnect", status_code=204, summary="Disconnect Gmail")
def gmail_disconnect(user_id: str = Depends(require_user)) -> None:
    """Remove stored Gmail credentials for the current user."""
    uid = user_id or None
    with Session(_engine_mod.engine) as session:
        if uid is None:
            _exec(session, "DELETE FROM google_tokens WHERE user_id IS NULL AND service = 'gmail'")
        else:
            _exec(session, "DELETE FROM google_tokens WHERE user_id = ? AND service = 'gmail'", (uid,))
        session.commit()
    # Also clean up legacy file if it exists
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()


# ---------------------------------------------------------------------------
# Gmail data endpoints
# ---------------------------------------------------------------------------


@router.get("/messages", response_model=list[GmailMessage], summary="List recent Gmail messages")
def list_messages(
    q: str | None = Query(None, description="Gmail search query (e.g. 'from:boss subject:report')"),
    max_results: int = Query(20, ge=1, le=100),
    user_id: str = Depends(require_user),
) -> list[GmailMessage]:
    """List recent emails, optionally filtered by Gmail search query."""
    service = _get_service(user_id=user_id)

    kwargs: dict[str, Any] = {"userId": "me", "maxResults": max_results}
    if q:
        kwargs["q"] = q

    result = service.users().messages().list(**kwargs).execute()
    message_ids = result.get("messages", [])

    if not message_ids:
        return []

    messages = []
    for msg_ref in message_ids:
        msg = service.users().messages().get(userId="me", id=msg_ref["id"], format="full").execute()
        messages.append(_parse_message(msg))

    return messages


@router.get("/messages/{message_id}", response_model=GmailMessage, summary="Read a specific email")
def get_message(message_id: str, user_id: str = Depends(require_user)) -> GmailMessage:
    """Fetch a single email by ID with full body."""
    service = _get_service(user_id=user_id)
    try:
        msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Message not found: {e}")
    return _parse_message(msg)


@router.get("/threads/{thread_id}", response_model=GmailThread, summary="Read a Gmail thread")
def get_thread(thread_id: str, user_id: str = Depends(require_user)) -> GmailThread:
    """Fetch all messages in a thread."""
    service = _get_service(user_id=user_id)
    try:
        thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Thread not found: {e}")

    thread_messages = [_parse_message(m) for m in thread.get("messages", [])]
    subject = thread_messages[0].subject if thread_messages else "(no subject)"

    return GmailThread(id=thread_id, subject=subject, messages=thread_messages)
