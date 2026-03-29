"""Preference feedback endpoint."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import require_user, user_filter
from ..database import db

router = APIRouter(prefix="/preferences", tags=["preferences"])


class PreferenceFeedback(BaseModel):
    accurate: bool


def _confidence_text_up(level: str) -> str:
    if level == "emerging":
        return "moderate"
    if level == "moderate":
        return "strong"
    return "strong"


def _confidence_text_down(level: str) -> str:
    if level == "strong":
        return "moderate"
    if level == "moderate":
        return "emerging"
    return "emerging"


@router.post("/{thing_id}/feedback", summary="Submit feedback on a learned preference")
def preference_feedback(
    thing_id: str,
    body: PreferenceFeedback,
    user_id: str = Depends(require_user),
) -> dict:
    """Adjust a preference's confidence based on user feedback.

    'accurate: true' (That's right) boosts confidence.
    'accurate: false' (Not really) reduces confidence.
    """
    uf_sql, uf_params = user_filter(user_id)
    now = datetime.now(timezone.utc).isoformat()

    with db() as conn:
        row = conn.execute(
            f"SELECT * FROM things WHERE id = ? AND type_hint = 'preference' AND active = 1{uf_sql}",
            [thing_id, *uf_params],
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Preference not found")

        raw_data = row["data"]
        try:
            data = json.loads(raw_data) if isinstance(raw_data, str) else (raw_data or {})
        except (json.JSONDecodeError, TypeError):
            data = {}

        if not isinstance(data, dict):
            data = {}

        if "patterns" in data and isinstance(data["patterns"], list):
            # Communication-style preference: adjust all pattern confidence levels
            for p in data["patterns"]:
                if isinstance(p, dict) and "confidence" in p:
                    if body.accurate:
                        p["confidence"] = _confidence_text_up(p.get("confidence", "emerging"))
                        p["observations"] = p.get("observations", 1) + 1
                    else:
                        p["confidence"] = _confidence_text_down(p.get("confidence", "emerging"))
        elif "confidence" in data and isinstance(data["confidence"], (int, float)):
            # Regular preference: adjust float confidence
            current = float(data["confidence"])
            if body.accurate:
                data["confidence"] = min(1.0, round(current + 0.1, 2))
            else:
                data["confidence"] = max(0.0, round(current - 0.15, 2))
        else:
            # No confidence field — initialize it
            data["confidence"] = 0.6 if body.accurate else 0.3

        conn.execute(
            "UPDATE things SET data = ?, updated_at = ? WHERE id = ?",
            (json.dumps(data), now, thing_id),
        )

    return {"id": thing_id, "updated": True}
