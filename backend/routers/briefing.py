"""Daily briefing endpoint — combines checkin-due Things with sweep findings."""

import json
import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_user, user_filter
from ..database import db
from ..models import (
    BriefingItem,
    BriefingPreferences,
    BriefingResponse,
    MorningBriefing,
    MorningBriefingContent,
    SweepFinding,
    SweepFindingCreate,
    SweepFindingSnooze,
    Thing,
    WeeklyBriefing,
    WeeklyBriefingContent,
)
from ..morning_briefing import (
    generate_morning_briefing,
    get_briefing_preferences,
    get_latest_morning_briefing,
    save_briefing_preferences,
    store_morning_briefing,
)
from ..weekly_briefing import (
    generate_weekly_briefing,
    get_latest_weekly_briefing,
    store_weekly_briefing,
)
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
               ORDER BY checkin_date ASC, importance ASC""",
            [cutoff, *uf_params],
        ).fetchall()

        # Active (not dismissed, not expired, not snoozed) sweep findings
        finding_rows = conn.execute(
            f"""SELECT sf.*, t.id AS t_id, t.title AS t_title, t.type_hint AS t_type_hint,
                      t.parent_id AS t_parent_id, t.checkin_date AS t_checkin_date,
                      t.importance AS t_importance, t.active AS t_active, t.surface AS t_surface,
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
                importance=r["t_importance"],
                active=bool(r["t_active"]),
                surface=bool(r["t_surface"]),
                data=json.loads(r["t_data"]) if isinstance(r["t_data"], str) and r["t_data"] else r["t_data"],
                created_at=r["t_created_at"],
                updated_at=r["t_updated_at"],
                last_referenced=r["t_last_referenced"],
            )
        findings.append(_row_to_finding(r, linked_thing))

    from ..urgency import build_blocker_graph, compute_composite_score, compute_urgency

    # Build blocker graph for urgency computation
    with db() as conn:
        rel_rows = conn.execute(
            """SELECT from_thing_id, to_thing_id, relationship_type
               FROM thing_relationships
               WHERE relationship_type IN ('blocks', 'depends-on')""",
        ).fetchall()
        all_active = conn.execute(
            f"SELECT id, importance, active FROM things WHERE active = 1{uf_sql}",
            [*uf_params],
        ).fetchall()

    all_things_map = {r["id"]: dict(r) for r in all_active}
    blocker_graph = build_blocker_graph([dict(r) for r in rel_rows])

    # Score each thing
    scored: list[BriefingItem] = []
    for thing in things:
        thing_dict = thing.model_dump()
        imp: int = thing.importance if thing.importance is not None else 2
        urgency, reasons = compute_urgency(thing_dict, target, blocker_graph, all_things_map)
        composite = compute_composite_score(imp, urgency)
        scored.append(BriefingItem(
            thing=thing_dict,
            importance=imp,
            urgency=round(urgency, 2),
            score=round(composite, 2),
            reasons=reasons,
        ))

    scored.sort(key=lambda x: x.score, reverse=True)

    the_one_thing = scored[0] if scored else None
    secondary = scored[1:6] if len(scored) > 1 else []
    parking_lot: list[dict[str, Any]] = [
        {"thing_id": s.thing["id"], "title": s.thing["title"],
         "importance": s.importance, "urgency": s.urgency}
        for s in scored[6:]
    ] if len(scored) > 6 else []

    return BriefingResponse(
        date=target.isoformat(),
        the_one_thing=the_one_thing,
        secondary=secondary,
        parking_lot=parking_lot,
        findings=findings,
        total=len(scored) + len(findings),
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


@router.get("/morning", response_model=MorningBriefing, summary="Get morning briefing")
def get_morning_briefing(as_of: date | None = None, user_id: str = Depends(require_user)) -> MorningBriefing:
    """Return the latest pre-generated morning briefing.

    If no pre-generated briefing exists, generates one on-the-fly.
    """
    result = get_latest_morning_briefing(user_id, as_of=as_of)

    if not result:
        # Generate on-the-fly if no stored briefing exists
        target = as_of or date.today()
        content = generate_morning_briefing(user_id, target_date=target)
        store_morning_briefing(user_id, content, briefing_date=target)
        result = get_latest_morning_briefing(user_id, as_of=target)

    if not result:
        raise HTTPException(status_code=500, detail="Failed to generate morning briefing")

    return MorningBriefing(
        id=result["id"],
        briefing_date=result["briefing_date"],
        content=MorningBriefingContent(**result["content"]),
        generated_at=result["generated_at"],
    )


@router.get("/preferences", response_model=BriefingPreferences, summary="Get briefing preferences")
def get_preferences(user_id: str = Depends(require_user)) -> BriefingPreferences:
    """Return the user's morning briefing preferences."""
    return get_briefing_preferences(user_id)


@router.put("/preferences", response_model=BriefingPreferences, summary="Update briefing preferences")
def update_preferences(body: BriefingPreferences, user_id: str = Depends(require_user)) -> BriefingPreferences:
    """Update the user's morning briefing preferences."""
    save_briefing_preferences(user_id, body)
    return body


@router.get("/weekly", response_model=WeeklyBriefing, summary="Get weekly digest")
def get_weekly_briefing(user_id: str = Depends(require_user)) -> WeeklyBriefing:
    """Return the weekly digest for the current week.

    Generates on-the-fly if no stored digest exists for this week.
    """
    result = get_latest_weekly_briefing(user_id)

    # Generate if missing or stale (not from this week)
    today = date.today()
    from datetime import timedelta
    current_week_start = today - timedelta(days=today.weekday())

    if not result or result["week_start"] != current_week_start.isoformat():
        content = generate_weekly_briefing(user_id, week_start=current_week_start)
        store_weekly_briefing(user_id, content)
        result = get_latest_weekly_briefing(user_id)

    if not result:
        raise HTTPException(status_code=500, detail="Failed to generate weekly briefing")

    return WeeklyBriefing(
        id=result["id"],
        week_start=result["week_start"],
        content=WeeklyBriefingContent(**result["content"]),
        generated_at=result["generated_at"],
    )
