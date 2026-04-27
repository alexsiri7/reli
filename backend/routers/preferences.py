"""Preference feedback endpoint."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

import backend.db_engine as _engine_mod

from ..auth import require_user
from ..db_engine import user_filter_clause
from ..db_models import ThingRecord

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
    now = datetime.now(timezone.utc)

    with Session(_engine_mod.engine) as session:
        record = session.exec(
            select(ThingRecord).where(
                ThingRecord.id == thing_id,
                ThingRecord.type_hint == "preference",
                ThingRecord.active,
                user_filter_clause(ThingRecord.user_id, user_id),
            )
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="Preference not found")

        raw_data = record.data
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

        record.data = data
        record.updated_at = now
        session.add(record)
        session.commit()
    return {"id": thing_id, "updated": True}
