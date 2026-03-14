"""Google Calendar read-only integration using OAuth2."""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from .database import db

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# OAuth client credentials — set via environment variables
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/calendar/callback")


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
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return str(auth_url)


def exchange_code(code: str) -> Credentials:
    """Exchange authorization code for credentials and store them."""
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    flow.fetch_token(code=code)
    creds: Credentials = flow.credentials
    _save_credentials(creds)
    return creds


def _save_credentials(creds: Credentials) -> None:
    """Store credentials in SQLite."""
    expiry_str = creds.expiry.isoformat() if creds.expiry else None
    scopes_str = json.dumps(list(creds.scopes)) if creds.scopes else None
    now = datetime.now(timezone.utc).isoformat()

    with db() as conn:
        conn.execute(
            """INSERT INTO google_tokens (id, access_token, refresh_token, token_uri,
               client_id, client_secret, expiry, scopes, updated_at)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               access_token=excluded.access_token,
               refresh_token=COALESCE(excluded.refresh_token, google_tokens.refresh_token),
               token_uri=excluded.token_uri,
               client_id=excluded.client_id,
               client_secret=excluded.client_secret,
               expiry=excluded.expiry,
               scopes=excluded.scopes,
               updated_at=excluded.updated_at""",
            (
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


def _load_credentials() -> Credentials | None:
    """Load stored credentials from SQLite."""
    with db() as conn:
        row = conn.execute("SELECT * FROM google_tokens WHERE id = 1").fetchone()
    if not row:
        return None

    creds = Credentials(
        token=row["access_token"],
        refresh_token=row["refresh_token"],
        token_uri=row["token_uri"],
        client_id=row["client_id"],
        client_secret=row["client_secret"],
    )
    if row["expiry"]:
        creds.expiry = datetime.fromisoformat(row["expiry"]).replace(tzinfo=None)

    return creds


def get_credentials() -> Credentials | None:
    """Load credentials and refresh if expired. Returns None if not connected."""
    creds = _load_credentials()
    if not creds:
        return None

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds)
        except Exception:
            # Token refresh failed — user needs to re-authorize
            return None

    if not creds.valid:
        return None

    return creds


def disconnect() -> None:
    """Remove stored credentials."""
    with db() as conn:
        conn.execute("DELETE FROM google_tokens WHERE id = 1")


def is_connected() -> bool:
    """Check if we have valid Google Calendar credentials."""
    return get_credentials() is not None


def fetch_upcoming_events(
    max_results: int = 20,
    days_ahead: int = 7,
) -> list[dict[str, Any]]:
    """Fetch upcoming calendar events. Returns empty list if not connected."""
    creds = get_credentials()
    if not creds:
        return []

    service = build("calendar", "v3", credentials=creds)

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
