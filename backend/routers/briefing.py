"""Daily briefing endpoint — combines checkin-due Things with sweep findings."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, HTTPException

from ..database import db
from ..models import BriefingResponse, SweepFinding, SweepFindingCreate, Thing
from .things import _row_to_thing

router = APIRouter(prefix="/briefing", tags=["briefing"])


def _row_to_finding(row, thing: Thing | None = None) -> SweepFinding:
    return SweepFinding(
        id=row["id"],
        thing_id=row["thing_id"],
        finding_type=row["finding_type"],
        message=row["message"],
        priority=row["priority"],
        dismissed=bool(row["dismissed"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        thing=thing,
    )


@router.get("", response_model=BriefingResponse, summary="Daily Briefing")
def get_briefing(as_of: date | None = None) -> BriefingResponse:
    """Return checkin-due Things and active sweep findings for the daily briefing."""
    target = as_of or date.today()
    cutoff = datetime.combine(target, datetime.max.time()).isoformat()
    now = datetime.utcnow().isoformat()

    with db() as conn:
        # Things with checkin_date due today or earlier
        thing_rows = conn.execute(
            """SELECT * FROM things
               WHERE active = 1
                 AND checkin_date IS NOT NULL
                 AND checkin_date <= ?
               ORDER BY checkin_date ASC, priority ASC""",
            (cutoff,),
        ).fetchall()

        # Active (not dismissed, not expired) sweep findings
        finding_rows = conn.execute(
            """SELECT sf.*, t.id AS t_id, t.title AS t_title, t.type_hint AS t_type_hint,
                      t.parent_id AS t_parent_id, t.checkin_date AS t_checkin_date,
                      t.priority AS t_priority, t.active AS t_active, t.surface AS t_surface,
                      t.data AS t_data, t.created_at AS t_created_at,
                      t.updated_at AS t_updated_at, t.last_referenced AS t_last_referenced
               FROM sweep_findings sf
               LEFT JOIN things t ON sf.thing_id = t.id
               WHERE sf.dismissed = 0
                 AND (sf.expires_at IS NULL OR sf.expires_at > ?)
               ORDER BY sf.priority ASC, sf.created_at DESC""",
            (now,),
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
                data=r["t_data"],
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


@router.post("/findings", response_model=SweepFinding, status_code=201)
def create_finding(body: SweepFindingCreate) -> SweepFinding:
    """Create a new sweep finding."""
    finding_id = f"sf-{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()

    with db() as conn:
        # Validate thing_id if provided
        if body.thing_id:
            row = conn.execute("SELECT id FROM things WHERE id = ?", (body.thing_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Thing {body.thing_id} not found")

        conn.execute(
            """INSERT INTO sweep_findings
               (id, thing_id, finding_type, message, priority, dismissed, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, 0, ?, ?)""",
            (finding_id, body.thing_id, body.finding_type, body.message, body.priority, now, body.expires_at),
        )

        row = conn.execute("SELECT * FROM sweep_findings WHERE id = ?", (finding_id,)).fetchone()

    return _row_to_finding(row)


@router.patch("/findings/{finding_id}/dismiss", response_model=SweepFinding)
def dismiss_finding(finding_id: str) -> SweepFinding:
    """Dismiss a sweep finding."""
    with db() as conn:
        row = conn.execute("SELECT * FROM sweep_findings WHERE id = ?", (finding_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Finding not found")

        conn.execute("UPDATE sweep_findings SET dismissed = 1 WHERE id = ?", (finding_id,))
        row = conn.execute("SELECT * FROM sweep_findings WHERE id = ?", (finding_id,)).fetchone()

    return _row_to_finding(row)
