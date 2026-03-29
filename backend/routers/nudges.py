"""Nudge banners — dismiss and preference-signal endpoints for in-app nudges."""

import json
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import require_user
from ..database import db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/nudges", tags=["nudges"])

_DISMISSED_KEY = "dismissed_nudges"
_STOPPED_KEYS_KEY = "stopped_nudge_keys"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_setting(conn, user_id: str, key: str) -> list:
    row = conn.execute(
        "SELECT value FROM user_settings WHERE user_id = ? AND key = ?",
        (user_id, key),
    ).fetchone()
    if row and row["value"]:
        try:
            return json.loads(row["value"])
        except (ValueError, TypeError):
            return []
    return []


def _set_setting(conn, user_id: str, key: str, value: list) -> None:
    conn.execute(
        """INSERT INTO user_settings (user_id, key, value, updated_at)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP""",
        (user_id, key, json.dumps(value)),
    )


# ── Models ───────────────────────────────────────────────────────────────────


class DismissRequest(BaseModel):
    thing_id: str
    date_key: str


class StopRequest(BaseModel):
    date_key: str


class NudgePreferences(BaseModel):
    dismissed_nudges: list[str]
    stopped_nudge_keys: list[str]


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/preferences", response_model=NudgePreferences, summary="Get nudge preferences")
def get_nudge_preferences(user_id: str = Depends(require_user)) -> NudgePreferences:
    """Return the user's dismissed nudges and stopped nudge keys."""
    with db() as conn:
        dismissed = _get_setting(conn, user_id, _DISMISSED_KEY)
        stopped = _get_setting(conn, user_id, _STOPPED_KEYS_KEY)
    return NudgePreferences(dismissed_nudges=dismissed, stopped_nudge_keys=stopped)


@router.post("/dismiss", summary="Dismiss a nudge")
def dismiss_nudge(body: DismissRequest, user_id: str = Depends(require_user)) -> dict:
    """Dismiss a specific nudge banner. Stores thing_id:date_key in user settings."""
    nudge_id = f"{body.thing_id}:{body.date_key}"
    with db() as conn:
        dismissed = _get_setting(conn, user_id, _DISMISSED_KEY)
        if nudge_id not in dismissed:
            dismissed.append(nudge_id)
            # Keep last 200 dismissed nudge IDs to avoid unbounded growth
            if len(dismissed) > 200:
                dismissed = dismissed[-200:]
            _set_setting(conn, user_id, _DISMISSED_KEY, dismissed)
    logger.info("User %s dismissed nudge %s", user_id, nudge_id)
    return {"ok": True}


@router.post("/stop", summary="Stop a nudge type (negative preference signal)")
def stop_nudge_type(body: StopRequest, user_id: str = Depends(require_user)) -> dict:
    """Record a negative preference signal: stop showing nudges for this date_key type."""
    with db() as conn:
        stopped = _get_setting(conn, user_id, _STOPPED_KEYS_KEY)
        if body.date_key not in stopped:
            stopped.append(body.date_key)
            _set_setting(conn, user_id, _STOPPED_KEYS_KEY, stopped)
    logger.info("User %s stopped nudge type %s", user_id, body.date_key)
    return {"ok": True}


@router.delete("/stop/{date_key}", summary="Re-enable a stopped nudge type")
def reenable_nudge_type(date_key: str, user_id: str = Depends(require_user)) -> dict:
    """Re-enable nudges for a previously stopped date_key."""
    with db() as conn:
        stopped = _get_setting(conn, user_id, _STOPPED_KEYS_KEY)
        stopped = [k for k in stopped if k != date_key]
        _set_setting(conn, user_id, _STOPPED_KEYS_KEY, stopped)
    return {"ok": True}
