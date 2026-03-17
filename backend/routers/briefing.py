"""Daily briefing endpoint — combines checkin-due Things with sweep findings."""

import json
import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_user, user_filter
from ..database import db
from ..models import (
    BatchNotification,
    BriefingResponse,
    StalenessReport,
    SweepFinding,
    SweepFindingCreate,
    SweepFindingSnooze,
    Thing,
)
from .settings import get_user_stale_days
from .things import _row_to_thing

router = APIRouter(prefix="/briefing", tags=["briefing"])


def _row_to_finding(row: Any, thing: Thing | None = None) -> SweepFinding:
    return SweepFinding(
        id=row["id"],
        thing_id=row["thing_id"],
        finding_type=row["finding_type"],
        message=row["message"],
        priority=row["priority"],
        dismissed=bool(row["dismissed"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        snoozed_until=row["snoozed_until"],
        thing=thing,
    )


@router.get("", response_model=BriefingResponse, summary="Daily Briefing")
def get_briefing(as_of: date | None = None, user_id: str = Depends(require_user)) -> BriefingResponse:
    """Return checkin-due Things and active sweep findings for the daily briefing."""
    target = as_of or date.today()
    cutoff = datetime.combine(target, datetime.max.time()).isoformat()
    now = datetime.utcnow().isoformat()

    uf_sql, uf_params = user_filter(user_id)
    sf_uf_sql, sf_uf_params = user_filter(user_id, "sf")

    with db() as conn:
        # Things with checkin_date due today or earlier
        thing_rows = conn.execute(
            f"""SELECT * FROM things
               WHERE active = 1
                 AND checkin_date IS NOT NULL
                 AND checkin_date <= ?{uf_sql}
               ORDER BY checkin_date ASC, priority ASC""",
            [cutoff, *uf_params],
        ).fetchall()

        # Active (not dismissed, not expired, not snoozed) sweep findings
        finding_rows = conn.execute(
            f"""SELECT sf.*, t.id AS t_id, t.title AS t_title, t.type_hint AS t_type_hint,
                      t.parent_id AS t_parent_id, t.checkin_date AS t_checkin_date,
                      t.priority AS t_priority, t.active AS t_active, t.surface AS t_surface,
                      t.data AS t_data, t.created_at AS t_created_at,
                      t.updated_at AS t_updated_at, t.last_referenced AS t_last_referenced
               FROM sweep_findings sf
               LEFT JOIN things t ON sf.thing_id = t.id
               WHERE sf.dismissed = 0
                 AND (sf.expires_at IS NULL OR sf.expires_at > ?)
                 AND (sf.snoozed_until IS NULL OR sf.snoozed_until <= ?){sf_uf_sql}
               ORDER BY sf.priority ASC, sf.created_at DESC""",
            [now, now, *sf_uf_params],
        ).fetchall()

    things: list[Thing] = [_row_to_thing(r) for r in thing_rows]

    findings: list[SweepFinding] = []
    for r in finding_rows:
        linked_thing = None
        if r["t_id"]:
            linked_thing = Thing(
                id=r["t_id"],
                title=r["t_title"],
                type_hint=r["t_type_hint"],
                parent_id=r["t_parent_id"],
                checkin_date=r["t_checkin_date"],
                priority=r["t_priority"],
                active=bool(r["t_active"]),
                surface=bool(r["t_surface"]),
                data=json.loads(r["t_data"]) if isinstance(r["t_data"], str) and r["t_data"] else r["t_data"],
                created_at=r["t_created_at"],
                updated_at=r["t_updated_at"],
                last_referenced=r["t_last_referenced"],
            )
        findings.append(_row_to_finding(r, linked_thing))

    return BriefingResponse(
        date=target.isoformat(),
        things=things,
        findings=findings,
        total=len(things) + len(findings),
    )


@router.post("/findings", response_model=SweepFinding, status_code=201, summary="Create a sweep finding")
def create_finding(body: SweepFindingCreate, user_id: str = Depends(require_user)) -> SweepFinding:
    """Create a new sweep finding, optionally linked to a Thing."""
    finding_id = f"sf-{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()

    with db() as conn:
        # Validate thing_id if provided
        if body.thing_id:
            uf_sql, uf_params = user_filter(user_id)
            row = conn.execute(f"SELECT id FROM things WHERE id = ?{uf_sql}", [body.thing_id, *uf_params]).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Thing {body.thing_id} not found")

        conn.execute(
            """INSERT INTO sweep_findings
               (id, thing_id, finding_type, message, priority, dismissed, created_at, expires_at, user_id)
               VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)""",
            (
                finding_id,
                body.thing_id,
                body.finding_type,
                body.message,
                body.priority,
                now,
                body.expires_at,
                user_id or None,
            ),
        )

        row = conn.execute("SELECT * FROM sweep_findings WHERE id = ?", (finding_id,)).fetchone()

    return _row_to_finding(row)


@router.patch("/findings/{finding_id}/dismiss", response_model=SweepFinding, summary="Dismiss a sweep finding")
def dismiss_finding(finding_id: str, user_id: str = Depends(require_user)) -> SweepFinding:
    """Dismiss a sweep finding so it no longer appears in the daily briefing."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        row = conn.execute(f"SELECT * FROM sweep_findings WHERE id = ?{uf_sql}", [finding_id, *uf_params]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Finding not found")

        conn.execute(f"UPDATE sweep_findings SET dismissed = 1 WHERE id = ?{uf_sql}", [finding_id, *uf_params])
        row = conn.execute("SELECT * FROM sweep_findings WHERE id = ?", (finding_id,)).fetchone()

    return _row_to_finding(row)


@router.post("/findings/{finding_id}/snooze", response_model=SweepFinding, summary="Snooze a sweep finding")
def snooze_finding(finding_id: str, body: SweepFindingSnooze, user_id: str = Depends(require_user)) -> SweepFinding:
    """Snooze a sweep finding — hide it from the daily briefing until the given date."""
    uf_sql, uf_params = user_filter(user_id)
    with db() as conn:
        row = conn.execute(f"SELECT * FROM sweep_findings WHERE id = ?{uf_sql}", [finding_id, *uf_params]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Finding not found")

        conn.execute(
            f"UPDATE sweep_findings SET snoozed_until = ? WHERE id = ?{uf_sql}",
            [body.until.isoformat(), finding_id, *uf_params],
        )
        row = conn.execute("SELECT * FROM sweep_findings WHERE id = ?", (finding_id,)).fetchone()

    return _row_to_finding(row)


@router.get("/staleness", response_model=StalenessReport, summary="Staleness & neglect report")
def get_staleness_report(as_of: date | None = None, user_id: str = Depends(require_user)) -> StalenessReport:
    """Return a dedicated staleness report for daily planning/review.

    Groups findings into overdue (past checkin_date), neglected (truly forgotten),
    and stale (inactive but not neglected). Uses the user's configured stale_days.
    """
    target = as_of or date.today()
    now = datetime.utcnow().isoformat()
    stale_days = get_user_stale_days(user_id)

    sf_uf_sql, sf_uf_params = user_filter(user_id, "sf")

    with db() as conn:
        finding_rows = conn.execute(
            f"""SELECT sf.*, t.id AS t_id, t.title AS t_title, t.type_hint AS t_type_hint,
                      t.parent_id AS t_parent_id, t.checkin_date AS t_checkin_date,
                      t.priority AS t_priority, t.active AS t_active, t.surface AS t_surface,
                      t.data AS t_data, t.created_at AS t_created_at,
                      t.updated_at AS t_updated_at, t.last_referenced AS t_last_referenced
               FROM sweep_findings sf
               LEFT JOIN things t ON sf.thing_id = t.id
               WHERE sf.dismissed = 0
                 AND sf.finding_type IN ('overdue', 'neglected', 'stale')
                 AND (sf.expires_at IS NULL OR sf.expires_at > ?)
                 AND (sf.snoozed_until IS NULL OR sf.snoozed_until <= ?){sf_uf_sql}
               ORDER BY sf.priority ASC, sf.created_at DESC""",
            [now, now, *sf_uf_params],
        ).fetchall()

    overdue: list[SweepFinding] = []
    neglected: list[SweepFinding] = []
    stale: list[SweepFinding] = []

    for r in finding_rows:
        linked_thing = None
        if r["t_id"]:
            linked_thing = Thing(
                id=r["t_id"],
                title=r["t_title"],
                type_hint=r["t_type_hint"],
                parent_id=r["t_parent_id"],
                checkin_date=r["t_checkin_date"],
                priority=r["t_priority"],
                active=bool(r["t_active"]),
                surface=bool(r["t_surface"]),
                data=json.loads(r["t_data"]) if isinstance(r["t_data"], str) and r["t_data"] else r["t_data"],
                created_at=r["t_created_at"],
                updated_at=r["t_updated_at"],
                last_referenced=r["t_last_referenced"],
            )
        finding = _row_to_finding(r, linked_thing)
        if finding.finding_type == "overdue":
            overdue.append(finding)
        elif finding.finding_type == "neglected":
            neglected.append(finding)
        else:
            stale.append(finding)

    total = len(overdue) + len(neglected) + len(stale)
    return StalenessReport(
        date=target.isoformat(),
        stale_days=stale_days,
        overdue=overdue,
        neglected=neglected,
        stale=stale,
        total=total,
    )


@router.get("/notifications", response_model=BatchNotification, summary="Batch notification summary")
def get_batch_notification(as_of: date | None = None, user_id: str = Depends(require_user)) -> BatchNotification:
    """Generate a batch notification summary of all items needing attention.

    Suitable for email digests, push notifications, or any batch alerting system.
    Returns counts and a human-readable summary of overdue, neglected, stale, and
    other active findings.
    """
    target = as_of or date.today()
    now = datetime.utcnow().isoformat()

    sf_uf_sql, sf_uf_params = user_filter(user_id, "sf")

    with db() as conn:
        finding_rows = conn.execute(
            f"""SELECT sf.*, t.id AS t_id, t.title AS t_title, t.type_hint AS t_type_hint,
                      t.parent_id AS t_parent_id, t.checkin_date AS t_checkin_date,
                      t.priority AS t_priority, t.active AS t_active, t.surface AS t_surface,
                      t.data AS t_data, t.created_at AS t_created_at,
                      t.updated_at AS t_updated_at, t.last_referenced AS t_last_referenced
               FROM sweep_findings sf
               LEFT JOIN things t ON sf.thing_id = t.id
               WHERE sf.dismissed = 0
                 AND (sf.expires_at IS NULL OR sf.expires_at > ?)
                 AND (sf.snoozed_until IS NULL OR sf.snoozed_until <= ?){sf_uf_sql}
               ORDER BY sf.priority ASC, sf.created_at DESC""",
            [now, now, *sf_uf_params],
        ).fetchall()

    items: list[SweepFinding] = []
    overdue_count = 0
    neglected_count = 0
    stale_count = 0
    other_count = 0

    for r in finding_rows:
        linked_thing = None
        if r["t_id"]:
            linked_thing = Thing(
                id=r["t_id"],
                title=r["t_title"],
                type_hint=r["t_type_hint"],
                parent_id=r["t_parent_id"],
                checkin_date=r["t_checkin_date"],
                priority=r["t_priority"],
                active=bool(r["t_active"]),
                surface=bool(r["t_surface"]),
                data=json.loads(r["t_data"]) if isinstance(r["t_data"], str) and r["t_data"] else r["t_data"],
                created_at=r["t_created_at"],
                updated_at=r["t_updated_at"],
                last_referenced=r["t_last_referenced"],
            )
        finding = _row_to_finding(r, linked_thing)
        items.append(finding)

        if finding.finding_type == "overdue":
            overdue_count += 1
        elif finding.finding_type == "neglected":
            neglected_count += 1
        elif finding.finding_type == "stale":
            stale_count += 1
        else:
            other_count += 1

    # Build human-readable summary
    parts: list[str] = []
    if overdue_count:
        parts.append(f"{overdue_count} overdue")
    if neglected_count:
        parts.append(f"{neglected_count} neglected")
    if stale_count:
        parts.append(f"{stale_count} stale")
    if other_count:
        parts.append(f"{other_count} other")

    if parts:
        summary = f"You have {', '.join(parts)} item{'s' if len(items) != 1 else ''} needing attention."
    else:
        summary = "All clear — nothing needs your attention right now."

    return BatchNotification(
        date=target.isoformat(),
        overdue_count=overdue_count,
        neglected_count=neglected_count,
        stale_count=stale_count,
        finding_count=other_count,
        summary=summary,
        items=items,
    )
