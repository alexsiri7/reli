"""In-app proactive nudge banners — time-sensitive insights surfaced to the user."""

import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_user, user_filter
from ..database import db
from ..models import Nudge, NudgeDismissRequest

router = APIRouter(prefix="/nudges", tags=["nudges"])

_MAX_NUDGES_PER_DAY = 3


def _get_daily_nudge_count(conn, user_id: str) -> int:
    """Count nudges shown today (not yet dismissed or freshly dismissed)."""
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM nudge_dismissals WHERE user_id = ? AND date(dismissed_at) = ?",
        (user_id, today),
    ).fetchone()
    return row["cnt"] if row else 0


def _was_dismissed(conn, user_id: str, source_id: str) -> bool:
    """Check if this nudge source was already dismissed (ever, or stop-these'd)."""
    row = conn.execute(
        "SELECT action FROM nudge_dismissals WHERE user_id = ? AND nudge_source_id = ? ORDER BY dismissed_at DESC LIMIT 1",
        (user_id, source_id),
    ).fetchone()
    if not row:
        return False
    # 'stop-these' suppresses permanently; 'dismiss' only suppresses for today
    if row["action"] == "stop-these":
        return True
    # Regular dismiss: check if it was today
    today_row = conn.execute(
        "SELECT id FROM nudge_dismissals WHERE user_id = ? AND nudge_source_id = ? AND date(dismissed_at) = ? AND action = 'dismiss'",
        (user_id, source_id, date.today().isoformat()),
    ).fetchone()
    return today_row is not None


@router.get("", response_model=list[Nudge], summary="Get active nudge banners")
def get_nudges(user_id: str = Depends(require_user)) -> list[Nudge]:
    """Return up to 3 proactive nudge banners for today."""
    uf_sql, uf_params = user_filter(user_id)
    now = datetime.utcnow().isoformat()
    today = date.today().isoformat()

    nudges: list[Nudge] = []

    with db() as conn:
        # Check daily limit from already-seen nudges
        seen_today = _get_daily_nudge_count(conn, user_id)
        remaining = _MAX_NUDGES_PER_DAY - seen_today

        if remaining <= 0:
            return []

        # Source 1: proactive surfaces (upcoming dates)
        from .proactive import _scan_data
        rows = conn.execute(
            f"SELECT * FROM things WHERE data IS NOT NULL AND data != '{{}}' AND data != 'null'{uf_sql}",
            uf_params,
        ).fetchall()

        import json
        for row in rows:
            if len(nudges) >= remaining:
                break
            data = row["data"]
            if not data:
                continue
            try:
                data_dict = json.loads(data) if isinstance(data, str) else data
            except (json.JSONDecodeError, TypeError):
                continue
            hits = _scan_data(data_dict, date.today(), window=3)
            for _key, reason, days_away in hits:
                source_id = f"proactive:{row['id']}:{_key}"
                if _was_dismissed(conn, user_id, source_id):
                    continue
                nudges.append(Nudge(
                    id=source_id,
                    source="proactive",
                    source_id=source_id,
                    message=f"{row['title']}: {reason}",
                    action_label="View",
                    thing_id=row["id"],
                    dismissed=False,
                    created_at=datetime.utcnow(),
                ))
                if len(nudges) >= remaining:
                    break

        # Source 2: high-priority sweep findings (priority 1)
        sf_uf_sql, sf_uf_params = user_filter(user_id, "sf")
        finding_rows = conn.execute(
            f"""SELECT sf.id, sf.message, sf.thing_id, sf.priority
                FROM sweep_findings sf
                WHERE sf.dismissed = 0
                  AND sf.priority <= 1
                  AND (sf.expires_at IS NULL OR sf.expires_at > ?)
                  AND (sf.snoozed_until IS NULL OR sf.snoozed_until <= ?){sf_uf_sql}
                ORDER BY sf.priority ASC, sf.created_at DESC
                LIMIT 5""",
            [now, now, *sf_uf_params],
        ).fetchall()

        for row in finding_rows:
            if len(nudges) >= remaining:
                break
            source_id = f"sweep:{row['id']}"
            if _was_dismissed(conn, user_id, source_id):
                continue
            nudges.append(Nudge(
                id=source_id,
                source="sweep",
                source_id=source_id,
                message=row["message"],
                action_label="Review",
                thing_id=row["thing_id"],
                dismissed=False,
                created_at=datetime.utcnow(),
            ))

    return nudges[:_MAX_NUDGES_PER_DAY]


@router.post("/{nudge_id:path}/dismiss", summary="Dismiss a nudge")
def dismiss_nudge(
    nudge_id: str,
    body: NudgeDismissRequest,
    user_id: str = Depends(require_user),
) -> dict:
    """Dismiss a nudge. action='stop-these' creates a negative preference signal."""
    record_id = str(uuid.uuid4())
    # Extract source from nudge_id
    parts = nudge_id.split(":", 1)
    source = parts[0] if len(parts) > 1 else "unknown"

    with db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO nudge_dismissals (id, user_id, nudge_source, nudge_source_id, action, dismissed_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (record_id, user_id, source, nudge_id, body.action),
        )

        if body.action == "stop-these":
            # Also record a negative preference signal on the user's preference thing if one exists
            pref_row = conn.execute(
                "SELECT id, data FROM things WHERE type_hint = 'preference' AND user_id = ? LIMIT 1",
                (user_id,),
            ).fetchone()
            if pref_row:
                import json as _json
                pref_data = {}
                try:
                    pref_data = _json.loads(pref_row["data"] or "{}")
                except Exception:
                    pass
                suppressed = pref_data.get("suppressed_nudge_types", [])
                if source not in suppressed:
                    suppressed.append(source)
                    pref_data["suppressed_nudge_types"] = suppressed
                    conn.execute(
                        "UPDATE things SET data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (_json.dumps(pref_data), pref_row["id"]),
                    )

    return {"ok": True, "action": body.action}
