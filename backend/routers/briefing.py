"""Daily briefing endpoint — combines checkin-due Things with sweep findings."""

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..auth import require_user
import backend.db_engine as _engine_mod
from ..db_engine import user_filter_clause
from ..db_models import SweepFindingRecord, ThingRecord, ThingRelationshipRecord
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
from .things import _record_to_thing

router = APIRouter(prefix="/briefing", tags=["briefing"])


def _record_to_finding(record: SweepFindingRecord, thing: Thing | None = None) -> SweepFinding:
    return SweepFinding(
        id=record.id,
        thing_id=record.thing_id,
        finding_type=record.finding_type,
        message=record.message,
        priority=record.priority,
        dismissed=bool(record.dismissed),
        created_at=record.created_at,
        expires_at=record.expires_at,
        snoozed_until=record.snoozed_until,
        thing=thing,
    )


@router.get("", response_model=BriefingResponse, summary="Daily Briefing")
def get_briefing(as_of: date | None = None, user_id: str = Depends(require_user)) -> BriefingResponse:
    """Return checkin-due Things and active sweep findings for the daily briefing."""
    target = as_of or date.today()
    cutoff = datetime.combine(target, datetime.max.time()).isoformat()
    now = datetime.now(timezone.utc)

    with Session(_engine_mod.engine) as session:
        # Things with checkin_date due today or earlier
        thing_stmt = (
            select(ThingRecord)
            .where(
                ThingRecord.active == True,
                ThingRecord.checkin_date.is_not(None),  # type: ignore[union-attr]
                ThingRecord.checkin_date <= cutoff,  # type: ignore[operator]
                user_filter_clause(ThingRecord.user_id, user_id),
            )
            .order_by(
                ThingRecord.checkin_date.asc(),  # type: ignore[union-attr]
                ThingRecord.importance.asc(),  # type: ignore[union-attr]
            )
        )
        thing_records = session.exec(thing_stmt).all()

        # Active (not dismissed, not expired, not snoozed) sweep findings with linked Things
        finding_stmt = (
            select(SweepFindingRecord, ThingRecord)
            .outerjoin(ThingRecord, SweepFindingRecord.thing_id == ThingRecord.id)
            .where(
                SweepFindingRecord.dismissed == False,
                (SweepFindingRecord.expires_at.is_(None)) | (SweepFindingRecord.expires_at > now),  # type: ignore[union-attr]
                (SweepFindingRecord.snoozed_until.is_(None)) | (SweepFindingRecord.snoozed_until <= now),  # type: ignore[union-attr]
                user_filter_clause(SweepFindingRecord.user_id, user_id),
            )
            .order_by(
                SweepFindingRecord.priority.asc(),  # type: ignore[union-attr]
                SweepFindingRecord.created_at.desc(),  # type: ignore[union-attr]
            )
        )
        finding_results = session.exec(finding_stmt).all()

    things: list[Thing] = [_record_to_thing(r) for r in thing_records]

    findings: list[SweepFinding] = []
    for finding_rec, thing_rec in finding_results:
        linked_thing = _record_to_thing(thing_rec) if thing_rec else None
        findings.append(_record_to_finding(finding_rec, linked_thing))

    from ..urgency import build_blocker_graph, compute_composite_score, compute_urgency

    # Build blocker graph for urgency computation
    with Session(_engine_mod.engine) as session:
        rel_rows = session.exec(
            select(ThingRelationshipRecord).where(
                ThingRelationshipRecord.relationship_type.in_(["blocks", "depends-on"])  # type: ignore[union-attr]
            )
        ).all()
        uf_things = user_filter_clause(ThingRecord.user_id, user_id)
        all_active = session.exec(
            select(ThingRecord).where(
                ThingRecord.active == True,
                uf_things,
            )
        ).all()

    all_things_map = {
        r.id: {"id": r.id, "importance": r.importance, "active": r.active}
        for r in all_active
    }
    blocker_graph = build_blocker_graph([
        {
            "from_thing_id": r.from_thing_id,
            "to_thing_id": r.to_thing_id,
            "relationship_type": r.relationship_type,
        }
        for r in rel_rows
    ])

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
    now = datetime.now(timezone.utc)

    with Session(_engine_mod.engine) as session:
        # Validate thing_id if provided
        if body.thing_id:
            thing = session.exec(
                select(ThingRecord).where(
                    ThingRecord.id == body.thing_id,
                    user_filter_clause(ThingRecord.user_id, user_id),
                )
            ).first()
            if not thing:
                raise HTTPException(status_code=404, detail=f"Thing {body.thing_id} not found")

        record = SweepFindingRecord(
            id=finding_id,
            thing_id=body.thing_id,
            finding_type=body.finding_type,
            message=body.message,
            priority=body.priority,
            dismissed=False,
            created_at=now,
            expires_at=body.expires_at,
            user_id=user_id or None,
        )
        session.add(record)
        session.commit()
        session.refresh(record)

    return _record_to_finding(record)


@router.patch("/findings/{finding_id}/dismiss", response_model=SweepFinding, summary="Dismiss a sweep finding")
def dismiss_finding(finding_id: str, user_id: str = Depends(require_user)) -> SweepFinding:
    """Dismiss a sweep finding so it no longer appears in the daily briefing."""
    with Session(_engine_mod.engine) as session:
        record = session.exec(
            select(SweepFindingRecord).where(
                SweepFindingRecord.id == finding_id,
                user_filter_clause(SweepFindingRecord.user_id, user_id),
            )
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="Finding not found")

        record.dismissed = True
        session.add(record)
        session.commit()
        session.refresh(record)

    return _record_to_finding(record)


@router.post("/findings/{finding_id}/snooze", response_model=SweepFinding, summary="Snooze a sweep finding")
def snooze_finding(finding_id: str, body: SweepFindingSnooze, user_id: str = Depends(require_user)) -> SweepFinding:
    """Snooze a sweep finding — hide it from the daily briefing until the given date."""
    with Session(_engine_mod.engine) as session:
        record = session.exec(
            select(SweepFindingRecord).where(
                SweepFindingRecord.id == finding_id,
                user_filter_clause(SweepFindingRecord.user_id, user_id),
            )
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="Finding not found")

        record.snoozed_until = body.until
        session.add(record)
        session.commit()
        session.refresh(record)

    return _record_to_finding(record)


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
