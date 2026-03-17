"""Blocker and conflict detection API endpoint."""

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query

from ..auth import require_user
from ..blocker_detection import BlockerAlert, detect_blockers
from ..models import BlockerAlertResponse

router = APIRouter(prefix="/blockers", tags=["blockers"])


@router.get("", response_model=list[BlockerAlertResponse], summary="Detect blockers and conflicts")
def get_blocker_alerts(
    proactivity: str = Query("medium", description="Proactivity level: off, low, medium, high"),
    user_id: str = Depends(require_user),
) -> list[BlockerAlertResponse]:
    """Return detected blocker alerts at the specified proactivity level."""
    if proactivity not in ("off", "low", "medium", "high"):
        proactivity = "medium"

    alerts = detect_blockers(proactivity_level=proactivity)
    return [
        BlockerAlertResponse(
            alert_type=a.alert_type,
            thing_id=a.thing_id,
            thing_title=a.thing_title,
            message=a.message,
            severity=a.severity,
            related_thing_ids=a.related_thing_ids,
        )
        for a in alerts
    ]
