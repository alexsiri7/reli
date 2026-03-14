"""Gmail read-only integration: OAuth2 flow and message endpoints."""

import base64
import os
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

router = APIRouter(prefix="/gmail", tags=["gmail"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
# Token file lives alongside the SQLite DB
_DATA_DIR = Path(os.environ.get("DATA_DIR", str(Path(__file__).parent.parent)))
TOKEN_PATH = _DATA_DIR / "gmail_token.json"


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


def _save_token(creds: Any) -> None:
    """Persist OAuth2 credentials to disk."""
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())


def _load_creds() -> Any:
    """Load and refresh credentials. Returns None if not connected."""
    if not TOKEN_PATH.exists():
        return None

    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), GMAIL_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        _save_token(creds)
    if not creds.valid:
        return None
    return creds


def _get_service() -> Any:
    """Build Gmail API service. Raises 401 if not connected."""
    creds = _load_creds()
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
def gmail_status() -> GmailStatus:
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Gmail integration not configured (missing GOOGLE_CLIENT_ID)")

    creds = _load_creds()
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
def gmail_auth_url(request: Request) -> dict[str, str]:
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
def gmail_callback(request: Request, code: str = Query(...), error: str | None = Query(None)) -> RedirectResponse:
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
    _save_token(flow.credentials)

    # Redirect to the app root after successful auth
    return RedirectResponse(url="/")


@router.delete("/disconnect", status_code=204, summary="Disconnect Gmail")
def gmail_disconnect() -> None:
    """Remove stored Gmail credentials."""
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()


# ---------------------------------------------------------------------------
# Gmail data endpoints
# ---------------------------------------------------------------------------


@router.get("/messages", response_model=list[GmailMessage], summary="List recent Gmail messages")
def list_messages(
    q: str | None = Query(None, description="Gmail search query (e.g. 'from:boss subject:report')"),
    max_results: int = Query(20, ge=1, le=100),
) -> list[GmailMessage]:
    """List recent emails, optionally filtered by Gmail search query."""
    service = _get_service()

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
def get_message(message_id: str) -> GmailMessage:
    """Fetch a single email by ID with full body."""
    service = _get_service()
    try:
        msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Message not found: {e}")
    return _parse_message(msg)


@router.get("/threads/{thread_id}", response_model=GmailThread, summary="Read a Gmail thread")
def get_thread(thread_id: str) -> GmailThread:
    """Fetch all messages in a thread."""
    service = _get_service()
    try:
        thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Thread not found: {e}")

    thread_messages = [_parse_message(m) for m in thread.get("messages", [])]
    subject = thread_messages[0].subject if thread_messages else "(no subject)"

    return GmailThread(id=thread_id, subject=subject, messages=thread_messages)
