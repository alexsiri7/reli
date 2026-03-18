"""Conflict detection endpoint — real-time blocker and scheduling conflict alerts."""

from fastapi import APIRouter, Depends, Query

from ..auth import require_user
from ..conflict_detector import ConflictAlert, detect_all_conflicts
from ..models import ConflictAlertResponse
from .settings import get_user_proactivity_level

router = APIRouter(prefix="/conflicts", tags=["conflicts"])

# Severity thresholds per proactivity level
_SEVERITY_FILTER: dict[str, set[str]] = {
    "off": set(),
    "low": {"critical"},
    "medium": {"critical", "warning"},
    "high": {"critical", "warning", "info"},
}


def _filter_by_proactivity(alerts: list[ConflictAlert], level: str) -> list[ConflictAlert]:
    allowed = _SEVERITY_FILTER.get(level, _SEVERITY_FILTER["medium"])
    return [a for a in alerts if a.severity in allowed]


@router.get("", response_model=list[ConflictAlertResponse], summary="Conflict Alerts")
def get_conflicts(
    window: int = Query(14, ge=1, le=90, description="Look-ahead window in days for deadline detection"),
    user_id: str = Depends(require_user),
) -> list[ConflictAlertResponse]:
    """Detect blockers, schedule overlaps, and deadline conflicts in real-time."""
    level = get_user_proactivity_level(user_id)
    if level == "off":
        return []

    alerts = detect_all_conflicts(user_id=user_id, window_days=window)
    filtered = _filter_by_proactivity(alerts, level)
    return [
        ConflictAlertResponse(
            alert_type=a.alert_type,
            severity=a.severity,
            message=a.message,
            thing_ids=a.thing_ids,
            thing_titles=a.thing_titles,
        )
        for a in filtered
    ]
