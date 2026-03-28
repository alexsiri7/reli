"""Weekly digest — summary of the past week's activity."""

import json
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends

from ..auth import require_user, user_filter
from ..database import db
from ..models import WeeklyDigest, WeeklyDigestContent

router = APIRouter(prefix="/digest", tags=["digest"])


def _get_week_start(d: date) -> date:
    """Return the Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def _build_digest_content(conn, user_id: str, week_start: date) -> WeeklyDigestContent:
    """Aggregate this week's activity into digest content."""
    week_end = week_start + timedelta(days=7)
    ws_iso = week_start.isoformat()
    we_iso = week_end.isoformat()
    uf_sql, uf_params = user_filter(user_id)

    # Things completed this week (active=0, updated this week)
    completed_rows = conn.execute(
        f"""SELECT id, title, type_hint FROM things
            WHERE active = 0
              AND date(updated_at) >= ? AND date(updated_at) < ?{uf_sql}
            ORDER BY updated_at DESC LIMIT 20""",
        [ws_iso, we_iso, *uf_params],
    ).fetchall()
    things_completed = [{"id": r["id"], "title": r["title"], "type": r["type_hint"]} for r in completed_rows]

    # New connections discovered this week
    conn_rows = conn.execute(
        f"""SELECT cs.id, cs.suggested_relationship_type as rel_type,
                  ft.title as from_title, tt.title as to_title
            FROM connection_suggestions cs
            JOIN things ft ON cs.from_thing_id = ft.id
            JOIN things tt ON cs.to_thing_id = tt.id
            WHERE cs.status = 'accepted'
              AND date(cs.resolved_at) >= ? AND date(cs.resolved_at) < ?
              AND cs.user_id = ?
            ORDER BY cs.resolved_at DESC LIMIT 10""",
        [ws_iso, we_iso, user_id],
    ).fetchall()
    new_connections = [
        {"from": r["from_title"], "to": r["to_title"], "relationship": r["rel_type"]}
        for r in conn_rows
    ]

    # Preferences learned/strengthened this week — look in preference things
    pref_rows = conn.execute(
        f"""SELECT id, title, data FROM things
            WHERE type_hint = 'preference'
              AND date(updated_at) >= ? AND date(updated_at) < ?{uf_sql}
            ORDER BY updated_at DESC LIMIT 5""",
        [ws_iso, we_iso, *uf_params],
    ).fetchall()
    preferences_learned: list[dict] = []
    for r in pref_rows:
        try:
            data = json.loads(r["data"] or "{}")
        except Exception:
            data = {}
        patterns = data.get("patterns", [])
        for p in patterns[:3]:
            preferences_learned.append({
                "pattern": p.get("pattern", ""),
                "confidence": p.get("confidence", "emerging"),
            })

    # Upcoming deadlines in the next 7 days
    next_week = (date.today() + timedelta(days=7)).isoformat()
    today_iso = date.today().isoformat()
    deadline_rows = conn.execute(
        f"""SELECT id, title, type_hint FROM things
            WHERE active = 1
              AND checkin_date IS NOT NULL
              AND date(checkin_date) >= ? AND date(checkin_date) <= ?{uf_sql}
            ORDER BY checkin_date ASC LIMIT 10""",
        [today_iso, next_week, *uf_params],
    ).fetchall()
    upcoming_deadlines = [{"id": r["id"], "title": r["title"], "type": r["type_hint"]} for r in deadline_rows]

    # Open questions from sweep findings
    finding_rows = conn.execute(
        f"""SELECT sf.message FROM sweep_findings sf
            WHERE sf.dismissed = 0
              AND sf.finding_type = 'open_question'{user_filter(user_id, 'sf')[0]}
            ORDER BY sf.created_at DESC LIMIT 5""",
        user_filter(user_id, "sf")[1],
    ).fetchall()
    open_questions = [r["message"] for r in finding_rows]

    # Build summary text
    parts = []
    if things_completed:
        parts.append(f"Completed {len(things_completed)} item{'s' if len(things_completed) != 1 else ''}.")
    if new_connections:
        parts.append(f"Discovered {len(new_connections)} new connection{'s' if len(new_connections) != 1 else ''}.")
    if preferences_learned:
        parts.append(f"Strengthened {len(preferences_learned)} preference pattern{'s' if len(preferences_learned) != 1 else ''}.")
    if upcoming_deadlines:
        parts.append(f"{len(upcoming_deadlines)} item{'s' if len(upcoming_deadlines) != 1 else ''} due in the coming week.")
    summary = " ".join(parts) if parts else "A quiet week — Reli is keeping watch."

    return WeeklyDigestContent(
        week_start=ws_iso,
        things_completed=things_completed,
        new_connections=new_connections,
        preferences_learned=preferences_learned,
        upcoming_deadlines=upcoming_deadlines,
        open_questions=open_questions,
        summary=summary,
    )


@router.get("/weekly", response_model=WeeklyDigest, summary="Get weekly digest")
def get_weekly_digest(user_id: str = Depends(require_user)) -> WeeklyDigest:
    """Return the weekly digest for the current week, generating if necessary."""
    week_start = _get_week_start(date.today())
    ws_iso = week_start.isoformat()

    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM weekly_digests WHERE user_id = ? AND week_start = ?",
            (user_id, ws_iso),
        ).fetchone()

        if existing:
            content = WeeklyDigestContent(**json.loads(existing["content"]))
            return WeeklyDigest(
                id=existing["id"],
                week_start=existing["week_start"],
                content=content,
                generated_at=datetime.fromisoformat(existing["generated_at"]),
            )

        # Generate fresh
        content = _build_digest_content(conn, user_id, week_start)
        digest_id = str(uuid.uuid4())
        now = datetime.utcnow()
        conn.execute(
            """INSERT OR REPLACE INTO weekly_digests (id, user_id, week_start, content, generated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (digest_id, user_id, ws_iso, content.model_dump_json(), now.isoformat()),
        )
        return WeeklyDigest(id=digest_id, week_start=ws_iso, content=content, generated_at=now)


@router.post("/weekly/regenerate", response_model=WeeklyDigest, summary="Regenerate weekly digest")
def regenerate_weekly_digest(user_id: str = Depends(require_user)) -> WeeklyDigest:
    """Force-regenerate the weekly digest for the current week."""
    week_start = _get_week_start(date.today())
    ws_iso = week_start.isoformat()

    with db() as conn:
        conn.execute(
            "DELETE FROM weekly_digests WHERE user_id = ? AND week_start = ?",
            (user_id, ws_iso),
        )
        content = _build_digest_content(conn, user_id, week_start)
        digest_id = str(uuid.uuid4())
        now = datetime.utcnow()
        conn.execute(
            """INSERT INTO weekly_digests (id, user_id, week_start, content, generated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (digest_id, user_id, ws_iso, content.model_dump_json(), now.isoformat()),
        )
        return WeeklyDigest(id=digest_id, week_start=ws_iso, content=content, generated_at=now)
