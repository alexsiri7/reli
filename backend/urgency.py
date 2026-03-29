"""Urgency computation engine for Reli briefings.

Urgency is computed dynamically — never stored. It answers "how soon does this
need attention?" based on temporal signals, blocker chains, and staleness.

Combined with the stored ``importance`` field ("how bad if this doesn't get
done?"), urgency produces a composite score that drives briefing ranking:

    score = (4 - importance) * urgency

High importance + high urgency = "the one thing."
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any


# ── Weight constants ─────────────────────────────────────────────────────────

_W_CHECKIN = 0.4  # max weight from checkin proximity
_W_BLOCKERS = 0.3  # max weight from blocking chains
_W_STALENESS = 0.15  # max weight from staleness
_W_CHILDREN = 0.15  # max weight from child task progress


def _parse_date(value: Any) -> date | None:
    """Best-effort parse of a date string to a date object."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except (ValueError, TypeError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    """Best-effort parse to a timezone-aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


# ── Core computation ─────────────────────────────────────────────────────────


def compute_urgency(
    thing: dict[str, Any],
    today: date,
    blocker_graph: dict[str, set[str]] | None = None,
    all_things: dict[str, dict[str, Any]] | None = None,
) -> tuple[float, list[str]]:
    """Compute urgency score (0.0–1.0) and human-readable reasons.

    Parameters
    ----------
    thing : dict
        A Thing dict (from the DB row).
    today : date
        The reference date (usually date.today()).
    blocker_graph : dict, optional
        Mapping of thing_id → set of thing_ids that it blocks.
    all_things : dict, optional
        Mapping of thing_id → thing dict, for looking up blocked things.

    Returns
    -------
    (urgency, reasons) : tuple[float, list[str]]
        urgency is 0.0 (not urgent) to 1.0 (critically urgent).
        reasons is a list of human-readable explanations.
    """
    score = 0.0
    reasons: list[str] = []

    # ── Checkin proximity ────────────────────────────────────────────────
    checkin = _parse_date(thing.get("checkin_date"))
    if checkin is not None:
        delta = (checkin - today).days
        if delta <= -7:
            s = _W_CHECKIN
            reasons.append(f"Check-in overdue by {-delta}d")
        elif delta < 0:
            s = 0.3
            reasons.append(f"Check-in overdue by {-delta}d")
        elif delta == 0:
            s = 0.25
            reasons.append("Check-in due today")
        elif delta == 1:
            s = 0.2
            reasons.append("Check-in due tomorrow")
        elif delta <= 3:
            s = 0.15
            reasons.append(f"Check-in in {delta}d")
        elif delta <= 7:
            s = 0.1
            reasons.append(f"Check-in in {delta}d")
        else:
            s = 0.0
        score += s

    # ── Blocker chains ───────────────────────────────────────────────────
    if blocker_graph and all_things:
        thing_id = thing.get("id", "")
        blocked_ids = blocker_graph.get(thing_id, set())
        active_blocked = {
            bid for bid in blocked_ids
            if all_things.get(bid, {}).get("active", 0)
        }
        if active_blocked:
            n = len(active_blocked)
            s = min(_W_BLOCKERS, n * 0.1)
            reasons.append(f"Blocks {n} other thing{'s' if n != 1 else ''}")
            # Extra boost if blocking high-importance things
            for bid in active_blocked:
                imp = all_things[bid].get("importance", 2)
                if imp is not None and imp <= 1:
                    s = min(_W_BLOCKERS, s + 0.1)
                    reasons.append("Blocks a high-importance item")
                    break
            score += s

    # ── Staleness ────────────────────────────────────────────────────────
    updated_at = _parse_datetime(thing.get("updated_at"))
    if updated_at:
        days_since = (datetime.now(timezone.utc) - updated_at).days
        if days_since > 0:
            s = min(_W_STALENESS, days_since / 30.0 * _W_STALENESS)
            if s >= 0.05:
                reasons.append(f"Not updated in {days_since}d")
            score += s

    # ── Child task progress ──────────────────────────────────────────────
    children_count = thing.get("children_count")
    completed_count = thing.get("completed_count")
    if children_count and children_count > 0 and completed_count is not None:
        ratio = completed_count / children_count
        if ratio > 0.7:
            # Nearly done — momentum boost
            s = _W_CHILDREN
            reasons.append(
                f"{completed_count}/{children_count} subtasks done — almost there"
            )
            score += s
        elif ratio > 0.3:
            s = _W_CHILDREN * 0.5
            score += s

    return min(1.0, score), reasons


def compute_composite_score(importance: int, urgency: float) -> float:
    """Compute the composite briefing score.

    Higher = more deserving of attention.
    importance 0 (critical) gets weight 4; importance 4 (backlog) gets weight 0.
    """
    return (4 - importance) * urgency


def build_blocker_graph(
    relationships: list[dict[str, Any]],
) -> dict[str, set[str]]:
    """Build a blocker graph from relationship rows.

    A relationship of type "blocks" or "depends-on" means:
    - "A blocks B" → A must be done before B → A appears in graph[A] = {B}
    - "A depends-on B" → B must be done before A → B appears in graph[B] = {A}

    Returns mapping: thing_id → set of thing_ids that it blocks.
    """
    graph: dict[str, set[str]] = {}
    for rel in relationships:
        rtype = rel.get("relationship_type", "")
        from_id = rel.get("from_thing_id", "")
        to_id = rel.get("to_thing_id", "")
        if rtype == "blocks":
            graph.setdefault(from_id, set()).add(to_id)
        elif rtype == "depends-on":
            graph.setdefault(to_id, set()).add(from_id)
    return graph
