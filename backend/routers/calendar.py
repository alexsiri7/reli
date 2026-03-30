"""Google Calendar read-only integration endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from ..auth import require_user
from ..google_calendar import (
    disconnect,
    exchange_code,
    fetch_upcoming_events,
    get_auth_url,
    is_configured,
    is_connected,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/status", summary="Google Calendar connection status")
def calendar_status(user_id: str = Depends(require_user)) -> dict[str, bool]:
    """Check whether Google Calendar is configured and connected."""
    return {
        "configured": is_configured(),
        "connected": is_connected(user_id=user_id),
    }


@router.get("/auth", summary="Start Google Calendar OAuth flow")
def calendar_auth(user_id: str = Depends(require_user)) -> dict[str, str]:
    """Return the Google OAuth2 authorization URL."""
    if not is_configured():
        raise HTTPException(
            status_code=400,
            detail="Google Calendar is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )
    return {"auth_url": get_auth_url()}


@router.get("/callback", summary="OAuth2 callback", include_in_schema=False)
def calendar_callback(
    code: str = Query(...),
    state: str = Query(""),
    error: str | None = Query(None),
    user_id: str = Depends(require_user),
) -> RedirectResponse:
    """Handle the OAuth2 callback from Google."""
    if error:
        logger.error("Calendar OAuth returned error: %s", error)
        return RedirectResponse(url="/?calendar_error=oauth_denied")

    try:
        exchange_code(code, state=state, user_id=user_id)
    except Exception:
        logger.exception("Calendar OAuth callback failed")
        return RedirectResponse(url="/?calendar_error=connection_failed")

    # Redirect back to the app with success indicator
    return RedirectResponse(url="/?calendar_connected=true")


@router.get("/events", summary="Fetch upcoming calendar events")
def calendar_events(
    max_results: int = Query(20, ge=1, le=100),
    days_ahead: int = Query(7, ge=1, le=30),
    user_id: str = Depends(require_user),
) -> dict[str, Any]:
    """Fetch upcoming events from the user's Google Calendar."""
    if not is_connected(user_id=user_id):
        raise HTTPException(status_code=401, detail="Google Calendar not connected")

    events = fetch_upcoming_events(max_results=max_results, days_ahead=days_ahead, user_id=user_id)
    return {"events": events, "count": len(events)}


@router.delete("/disconnect", summary="Disconnect Google Calendar")
def calendar_disconnect(user_id: str = Depends(require_user)) -> dict[str, str]:
    """Remove stored Google Calendar credentials for the current user."""
    disconnect(user_id=user_id)
    return {"status": "disconnected"}
