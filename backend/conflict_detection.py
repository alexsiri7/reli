"""Blocker & conflict detection — real-time analysis of Things graph.

Detects:
  - blocked_thing: Active Thing with "depends-on" relationship to another active Thing
  - downstream_impact: Active Things transitively blocked by a blocked Thing
  - schedule_overlap: Things/events with overlapping date ranges
  - deadline_conflict: Dependency has a later deadline than the dependent Thing

Proactivity levels:
  - low: Only critical blockers (priority 1-2)
  - medium: Blockers + deadline conflicts
  - high: All detections including schedule overlaps and downstream impact
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime

from .auth import user_filter
from .database import db

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

# Relationship types that indicate blocking semantics
_BLOCKING_REL_TYPES = {"depends-on", "blocks", "blocked-by"}


@dataclass
class Conflict:
    """A detected conflict or blocker."""

    conflict_type: str  # blocked_thing, downstream_impact, schedule_overlap, deadline_conflict
    message: str
    priority: int  # 0-4, lower = more critical
    thing_id: str | None = None
    thing_title: str | None = None
    blocker_id: str | None = None
    blocker_title: str | None = None
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "conflict_type": self.conflict_type,
            "message": self.message,
            "priority": self.priority,
            "thing_id": self.thing_id,
            "thing_title": self.thing_title,
            "blocker_id": self.blocker_id,
            "blocker_title": self.blocker_title,
            "details": self.details,
        }


def _parse_date(value: object) -> date | None:
    """Extract a date from a JSON value."""
    if isinstance(value, str):
        m = _DATE_RE.search(value)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def _get_deadline(data: dict | None) -> date | None:
    """Extract the most relevant deadline from a Thing's data."""
    if not data:
        return None
    for key in ("deadline", "due_date", "due", "end_date", "ends_at"):
        if key in data:
            d = _parse_date(data[key])
            if d:
                return d
    return None


def _get_date_range(data: dict | None) -> tuple[date | None, date | None]:
    """Extract start and end dates from a Thing's data."""
    if not data:
        return None, None
    start = None
    end = None
    for key in ("starts_at", "start_date", "event_date", "date"):
        if key in data:
            start = _parse_date(data[key])
            if start:
                break
    for key in ("ends_at", "end_date"):
        if key in data:
            end = _parse_date(data[key])
            if end:
                break
    return start, end


def detect_conflicts(
    user_id: str = "",
    proactivity: str = "medium",
) -> list[Conflict]:
    """Detect blockers and conflicts in the Things graph.

    Args:
        user_id: Filter to this user's Things.
        proactivity: Detection level — "low", "medium", or "high".

    Returns:
        List of detected conflicts, sorted by priority (most critical first).
    """
    conflicts: list[Conflict] = []
    uf_sql, uf_params = user_filter(user_id)

    with db() as conn:
        # Load active Things
        rows = conn.execute(
            f"SELECT * FROM things WHERE active = 1{uf_sql}",
            uf_params,
        ).fetchall()
        things_by_id: dict[str, dict] = {}
        for row in rows:
            thing = dict(row)
            if isinstance(thing.get("data"), str):
                try:
                    thing["data"] = json.loads(thing["data"])
                except (json.JSONDecodeError, TypeError):
                    thing["data"] = {}
            things_by_id[thing["id"]] = thing

        # Load relationships
        rels = conn.execute(
            "SELECT * FROM thing_relationships"
        ).fetchall()

    # Build dependency graph: depends_on[A] = [B, C] means A depends on B and C
    depends_on: dict[str, list[str]] = {}
    blocks: dict[str, list[str]] = {}  # blocks[B] = [A, C] means B blocks A and C

    for rel in rels:
        rel_type = rel["relationship_type"].lower().replace(" ", "-")
        from_id = rel["from_thing_id"]
        to_id = rel["to_thing_id"]

        if rel_type == "depends-on":
            depends_on.setdefault(from_id, []).append(to_id)
            blocks.setdefault(to_id, []).append(from_id)
        elif rel_type == "blocks":
            depends_on.setdefault(to_id, []).append(from_id)
            blocks.setdefault(from_id, []).append(to_id)
        elif rel_type == "blocked-by":
            depends_on.setdefault(from_id, []).append(to_id)
            blocks.setdefault(to_id, []).append(from_id)

    # --- Detection 1: Blocked Things ---
    blocked_things: set[str] = set()
    for thing_id, dep_ids in depends_on.items():
        if thing_id not in things_by_id:
            continue
        thing = things_by_id[thing_id]
        if not thing.get("active"):
            continue
        for dep_id in dep_ids:
            if dep_id not in things_by_id:
                continue
            dep = things_by_id[dep_id]
            if dep.get("active"):
                # This thing depends on something that's still active (not done)
                blocked_things.add(thing_id)
                thing_priority = thing.get("priority", 3)
                conflict_priority = max(0, thing_priority - 1)  # Blockers escalate priority

                if proactivity == "low" and conflict_priority > 2:
                    continue

                conflicts.append(Conflict(
                    conflict_type="blocked_thing",
                    message=f'"{thing["title"]}" is blocked by "{dep["title"]}" (still active)',
                    priority=conflict_priority,
                    thing_id=thing_id,
                    thing_title=thing["title"],
                    blocker_id=dep_id,
                    blocker_title=dep["title"],
                ))

    # --- Detection 2: Downstream Impact (high proactivity only) ---
    if proactivity == "high":
        for blocker_id in list(blocked_things):
            # Find things transitively blocked
            visited: set[str] = set()
            queue = list(blocks.get(blocker_id, []))
            while queue:
                current = queue.pop(0)
                if current in visited or current == blocker_id:
                    continue
                visited.add(current)
                downstream = blocks.get(current, [])
                queue.extend(downstream)

            if len(visited) > 1:  # More than just direct dependents
                blocker = things_by_id.get(blocker_id)
                if blocker:
                    affected_titles = [
                        things_by_id[tid]["title"]
                        for tid in visited
                        if tid in things_by_id
                    ][:5]
                    conflicts.append(Conflict(
                        conflict_type="downstream_impact",
                        message=(
                            f'"{blocker["title"]}" blocks {len(visited)} downstream items'
                        ),
                        priority=1,
                        thing_id=blocker_id,
                        thing_title=blocker["title"],
                        details={
                            "affected_count": len(visited),
                            "affected_sample": affected_titles,
                        },
                    ))

    # --- Detection 3: Deadline Conflicts (medium+ proactivity) ---
    if proactivity in ("medium", "high"):
        for thing_id, dep_ids in depends_on.items():
            if thing_id not in things_by_id:
                continue
            thing = things_by_id[thing_id]
            if not thing.get("active"):
                continue
            thing_deadline = _get_deadline(thing.get("data"))
            if not thing_deadline:
                continue

            for dep_id in dep_ids:
                if dep_id not in things_by_id:
                    continue
                dep = things_by_id[dep_id]
                if not dep.get("active"):
                    continue
                dep_deadline = _get_deadline(dep.get("data"))
                if dep_deadline and dep_deadline > thing_deadline:
                    days_diff = (dep_deadline - thing_deadline).days
                    conflicts.append(Conflict(
                        conflict_type="deadline_conflict",
                        message=(
                            f'"{thing["title"]}" is due {thing_deadline} but depends on '
                            f'"{dep["title"]}" due {dep_deadline} ({days_diff}d later)'
                        ),
                        priority=1,
                        thing_id=thing_id,
                        thing_title=thing["title"],
                        blocker_id=dep_id,
                        blocker_title=dep["title"],
                        details={
                            "thing_deadline": str(thing_deadline),
                            "dep_deadline": str(dep_deadline),
                            "days_diff": days_diff,
                        },
                    ))

    # --- Detection 4: Schedule Overlaps (high proactivity only) ---
    if proactivity == "high":
        # Collect things with date ranges
        things_with_ranges: list[tuple[str, str, date, date]] = []
        for tid, thing in things_by_id.items():
            start, end = _get_date_range(thing.get("data"))
            if start:
                if not end:
                    end = start  # single-day event
                things_with_ranges.append((tid, thing["title"], start, end))

        # Check for overlaps (O(n^2) but typically small number of dated items)
        for i, (id_a, title_a, start_a, end_a) in enumerate(things_with_ranges):
            for id_b, title_b, start_b, end_b in things_with_ranges[i + 1:]:
                if start_a <= end_b and start_b <= end_a:
                    # Overlapping date ranges
                    conflicts.append(Conflict(
                        conflict_type="schedule_overlap",
                        message=f'"{title_a}" and "{title_b}" have overlapping dates',
                        priority=2,
                        thing_id=id_a,
                        thing_title=title_a,
                        blocker_id=id_b,
                        blocker_title=title_b,
                        details={
                            "range_a": f"{start_a} - {end_a}",
                            "range_b": f"{start_b} - {end_b}",
                        },
                    ))

    # Sort by priority (most critical first), then by type
    type_order = {
        "deadline_conflict": 0,
        "blocked_thing": 1,
        "downstream_impact": 2,
        "schedule_overlap": 3,
    }
    conflicts.sort(key=lambda c: (c.priority, type_order.get(c.conflict_type, 9)))

    return conflicts


def detect_conflicts_for_context(
    relevant_thing_ids: list[str],
    user_id: str = "",
    proactivity: str = "medium",
) -> list[dict]:
    """Detect conflicts relevant to specific Things (for chat pipeline injection).

    Returns only conflicts involving the given Thing IDs, formatted as dicts
    for injection into the reasoning agent context.
    """
    all_conflicts = detect_conflicts(user_id=user_id, proactivity=proactivity)

    if not relevant_thing_ids:
        return [c.to_dict() for c in all_conflicts]

    id_set = set(relevant_thing_ids)
    relevant = [
        c for c in all_conflicts
        if (c.thing_id and c.thing_id in id_set)
        or (c.blocker_id and c.blocker_id in id_set)
    ]

    return [c.to_dict() for c in relevant]
