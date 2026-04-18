"""Google Calendar integration using OAuth2 (read + write)."""

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
import httplib2
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

from sqlmodel import Session, select

from .config import settings
import backend.db_engine as _engine_mod
from .db_models import GoogleTokenRecord
from .token_encryption import decrypt_or_plaintext, encrypt

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# OAuth client credentials
GOOGLE_CLIENT_ID = settings.GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET = settings.GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI = settings.GOOGLE_REDIRECT_URI

# PKCE state storage: state -> code_verifier (single-process, in-memory)
_pending_flows: dict[str, str] = {}
_pending_flows_lock = threading.Lock()


def _client_config() -> dict:
    """Build OAuth client config from environment variables."""
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }


def is_configured() -> bool:
    """Check if Google Calendar OAuth credentials are configured."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def get_auth_url() -> str:
    """Generate the Google OAuth2 authorization URL."""
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    # Store PKCE code_verifier for the callback
    with _pending_flows_lock:
        _pending_flows[state] = flow.code_verifier or ""
    return str(auth_url)


def exchange_code(code: str, state: str = "", user_id: str = "") -> Credentials:
    """Exchange authorization code for credentials and store them."""
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = GOOGLE_REDIRECT_URI

    # Restore PKCE code_verifier from the auth request
    if state:
        with _pending_flows_lock:
            code_verifier = _pending_flows.pop(state, None)
    else:
        code_verifier = None
    if code_verifier:
        flow.code_verifier = code_verifier

    # Google returns scopes in expanded URI form; tell oauthlib to accept it
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

    flow.fetch_token(code=code)
    creds: Credentials = flow.credentials
    _save_credentials(creds, user_id=user_id)
    return creds


def _save_credentials(creds: Credentials, user_id: str = "") -> None:
    """Store credentials in SQLite with sensitive fields encrypted."""
    expiry_str = creds.expiry.isoformat() if creds.expiry else None
    scopes_str = json.dumps(list(creds.scopes)) if creds.scopes else None
    now = datetime.now(timezone.utc).isoformat()
    uid = user_id or None  # Store NULL when auth is disabled (empty string)

    # Encrypt sensitive token fields
    enc_access = encrypt(creds.token) if creds.token else None
    enc_refresh = encrypt(creds.refresh_token) if creds.refresh_token else None
    enc_secret = encrypt(creds.client_secret) if creds.client_secret else ""

    with Session(_engine_mod.engine) as session:
        # Find existing token record
        stmt = select(GoogleTokenRecord).where(
            GoogleTokenRecord.service == "calendar",
        )
        if uid is None:
            stmt = stmt.where(GoogleTokenRecord.user_id.is_(None))  # type: ignore[union-attr]
        else:
            stmt = stmt.where(GoogleTokenRecord.user_id == uid)
        existing = session.exec(stmt).first()

        if existing:
            existing.access_token = enc_access or ""
            if enc_refresh is not None:
                existing.refresh_token = enc_refresh
            existing.token_uri = creds.token_uri
            existing.client_id = creds.client_id
            existing.client_secret = enc_secret
            existing.expiry = expiry_str
            existing.scopes = scopes_str
            existing.updated_at = datetime.now(timezone.utc)
            session.add(existing)
        else:
            record = GoogleTokenRecord(
                user_id=uid,
                service="calendar",
                access_token=enc_access or "",
                refresh_token=enc_refresh,
                token_uri=creds.token_uri,
                client_id=creds.client_id,
                client_secret=enc_secret,
                expiry=expiry_str,
                scopes=scopes_str,
                updated_at=datetime.now(timezone.utc),
            )
            session.add(record)
        session.commit()


def _load_credentials(user_id: str = "") -> Credentials | None:
    """Load stored credentials from SQLite, decrypting sensitive fields.

    Transparently migrates plaintext tokens written before encryption was
    enabled: if decryption fails the value is treated as plaintext and
    re-encrypted on next save.
    """
    uid = user_id or None

    with Session(_engine_mod.engine) as session:
        stmt = select(GoogleTokenRecord).where(
            GoogleTokenRecord.service == "calendar",
        )
        if uid is None:
            stmt = stmt.where(GoogleTokenRecord.user_id.is_(None))  # type: ignore[union-attr]
        else:
            stmt = stmt.where(GoogleTokenRecord.user_id == uid)
        row = session.exec(stmt).first()
    if not row:
        return None

    # Decrypt sensitive fields (handles plaintext migration)
    access_token, access_enc = decrypt_or_plaintext(row.access_token) if row.access_token else (None, True)
    refresh_token, refresh_enc = decrypt_or_plaintext(row.refresh_token) if row.refresh_token else (None, True)
    client_secret, secret_enc = decrypt_or_plaintext(row.client_secret) if row.client_secret else ("", True)

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=row.token_uri,
        client_id=row.client_id,
        client_secret=client_secret,
    )
    if row.expiry:
        creds.expiry = datetime.fromisoformat(row.expiry).replace(tzinfo=None)

    # Migrate: if any field was stored as plaintext, re-save encrypted
    if not (access_enc and refresh_enc and secret_enc):
        _save_credentials(creds, user_id=user_id)

    return creds


def get_credentials(user_id: str = "") -> Credentials | None:
    """Load credentials and refresh if expired. Returns None if not connected."""
    creds = _load_credentials(user_id=user_id)
    if not creds:
        return None

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds, user_id=user_id)
        except Exception:
            logger.warning("Google Calendar token refresh failed", exc_info=True)
            return None

    if not creds.valid:
        return None

    return creds


def disconnect(user_id: str = "") -> None:
    """Remove stored credentials for the given user."""
    uid = user_id or None
    with Session(_engine_mod.engine) as session:
        stmt = select(GoogleTokenRecord).where(
            GoogleTokenRecord.service == "calendar",
        )
        if uid is None:
            stmt = stmt.where(GoogleTokenRecord.user_id.is_(None))  # type: ignore[union-attr]
        else:
            stmt = stmt.where(GoogleTokenRecord.user_id == uid)
        for rec in session.exec(stmt).all():
            session.delete(rec)
        session.commit()


def is_connected(user_id: str = "") -> bool:
    """Check if we have valid Google Calendar credentials."""
    return get_credentials(user_id=user_id) is not None


def fetch_upcoming_events(
    max_results: int = 20,
    days_ahead: int = 7,
    user_id: str = "",
) -> list[dict[str, Any]]:
    """Fetch upcoming calendar events. Returns empty list if not connected."""
    creds = get_credentials(user_id=user_id)
    if not creds:
        return []

    authorized_http = AuthorizedHttp(creds, http=httplib2.Http(timeout=30))
    service = build("calendar", "v3", http=authorized_http)

    now = datetime.now(timezone.utc)
    time_max = now + timedelta(days=days_ahead)

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = []
    for event in events_result.get("items", []):
        start = event.get("start", {})
        end = event.get("end", {})
        events.append(
            {
                "id": event.get("id", ""),
                "summary": event.get("summary", "(No title)"),
                "start": start.get("dateTime") or start.get("date", ""),
                "end": end.get("dateTime") or end.get("date", ""),
                "all_day": "date" in start and "dateTime" not in start,
                "location": event.get("location"),
                "description": event.get("description"),
                "status": event.get("status", "confirmed"),
                "html_link": event.get("htmlLink"),
            }
        )

    return events


def create_event(
    summary: str,
    start: str,
    end: str,
    location: str = "",
    description: str = "",
    user_id: str = "",
) -> dict[str, Any]:
    """Create a calendar event. Returns the created event dict, or empty dict if not connected."""
    creds = get_credentials(user_id=user_id)
    if not creds:
        return {}

    try:
        authorized_http = AuthorizedHttp(creds, http=httplib2.Http(timeout=30))
        service = build("calendar", "v3", http=authorized_http)

        body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start, "timeZone": "UTC"},
            "end": {"dateTime": end, "timeZone": "UTC"},
        }
        if location:
            body["location"] = location
        if description:
            body["description"] = description

        event = service.events().insert(calendarId="primary", body=body).execute()
        return {
            "id": event.get("id", ""),
            "summary": event.get("summary", ""),
            "start": event.get("start", {}).get("dateTime", ""),
            "end": event.get("end", {}).get("dateTime", ""),
            "html_link": event.get("htmlLink", ""),
        }
    except Exception:
        logger.warning("Google Calendar create_event failed", exc_info=True)
        return {}


def update_event(
    event_id: str,
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
    description: str | None = None,
    user_id: str = "",
) -> dict[str, Any]:
    """Update an existing calendar event. Only provided fields are changed.
    Returns the updated event dict, or empty dict if not connected."""
    creds = get_credentials(user_id=user_id)
    if not creds:
        return {}

    try:
        authorized_http = AuthorizedHttp(creds, http=httplib2.Http(timeout=30))
        service = build("calendar", "v3", http=authorized_http)

        # Fetch current event to patch only changed fields
        existing = service.events().get(calendarId="primary", eventId=event_id).execute()

        if summary is not None:
            existing["summary"] = summary
        if start is not None:
            existing.setdefault("start", {})["dateTime"] = start
            existing["start"].setdefault("timeZone", "UTC")
        if end is not None:
            existing.setdefault("end", {})["dateTime"] = end
            existing["end"].setdefault("timeZone", "UTC")
        if location is not None:
            existing["location"] = location
        if description is not None:
            existing["description"] = description

        event = service.events().update(
            calendarId="primary", eventId=event_id, body=existing
        ).execute()
        return {
            "id": event.get("id", ""),
            "summary": event.get("summary", ""),
            "start": event.get("start", {}).get("dateTime", ""),
            "end": event.get("end", {}).get("dateTime", ""),
            "html_link": event.get("htmlLink", ""),
        }
    except Exception:
        logger.warning("Google Calendar update_event failed", exc_info=True)
        return {}
