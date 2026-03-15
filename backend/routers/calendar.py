"""Google Calendar read-only integration endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from ..google_calendar import (
    disconnect,
    exchange_code,
    fetch_upcoming_events,
    get_auth_url,
    is_configured,
    is_connected,
)

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/status", summary="Google Calendar connection status")
def calendar_status() -> dict[str, bool]:
    """Check whether Google Calendar is configured and connected."""
    return {
        "configured": is_configured(),
        "connected": is_connected(),
    }


@router.get("/auth", summary="Start Google Calendar OAuth flow")
def calendar_auth() -> dict[str, str]:
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
) -> RedirectResponse:
    """Handle the OAuth2 callback from Google."""
    if error:
        # Redirect to frontend with error
        return RedirectResponse(url=f"/?calendar_error={error}")

    try:
        exchange_code(code, state=state)
    except Exception as exc:
        return RedirectResponse(url=f"/?calendar_error={exc}")

    # Redirect back to the app with success indicator
    return RedirectResponse(url="/?calendar_connected=true")


@router.get("/events", summary="Fetch upcoming calendar events")
def calendar_events(
    max_results: int = Query(20, ge=1, le=100),
    days_ahead: int = Query(7, ge=1, le=30),
) -> dict[str, Any]:
    """Fetch upcoming events from the user's Google Calendar."""
    if not is_connected():
        raise HTTPException(status_code=401, detail="Google Calendar not connected")

    events = fetch_upcoming_events(max_results=max_results, days_ahead=days_ahead)
    return {"events": events, "count": len(events)}


@router.delete("/disconnect", summary="Disconnect Google Calendar")
def calendar_disconnect() -> dict[str, str]:
    """Remove stored Google Calendar credentials."""
    disconnect()
    return {"status": "disconnected"}
