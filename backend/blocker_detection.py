"""Real-time blocker and conflict detection for the Reli chat pipeline.

Detects:
  - blocked_thing: Active Thing with an unsatisfied "depends-on" relationship
  - deadline_conflict: Dependency has a later deadline than the thing depending on it
  - schedule_overlap: Things with overlapping date ranges
  - circular_dependency: Circular dependency chains
  - downstream_impact: Transitive blocking chains from a specific thing
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .database import db
from .sweep import _parse_date_value

logger = logging.getLogger(__name__)

# Proactivity levels control which detections run
PROACTIVITY_LEVELS = {
    "off": [],
    "low": ["blocked_thing"],
    "medium": ["blocked_thing", "deadline_conflict", "downstream_impact"],
    "high": ["blocked_thing", "deadline_conflict", "downstream_impact", "schedule_overlap", "circular_dependency"],
}

DEFAULT_PROACTIVITY = "medium"


@dataclass
class BlockerAlert:
    """A detected blocker or conflict."""

    alert_type: str  # blocked_thing, deadline_conflict, schedule_overlap, circular_dependency, downstream_impact
    thing_id: str
    thing_title: str
    message: str
    severity: str = "warning"  # info, warning, critical
    related_thing_ids: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def _get_date_from_thing(thing_row: sqlite3.Row) -> date | None:
    """Extract the most relevant date from a Thing (deadline, due_date, checkin_date)."""
    # Check checkin_date column first
    if thing_row["checkin_date"]:
        parsed = _parse_date_value(thing_row["checkin_date"])
        if parsed:
            return parsed

    # Check data JSON for deadline/due_date
    raw_data = thing_row["data"]
    if raw_data:
        try:
            data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
        except (json.JSONDecodeError, TypeError):
            return None
        if isinstance(data, dict):
            for key in ("deadline", "due_date", "due", "end_date"):
                val = data.get(key)
                if val:
                    parsed = _parse_date_value(val)
                    if parsed:
                        return parsed
    return None


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------


def find_blocked_things(
    conn: sqlite3.Connection,
    thing_ids: list[str] | None = None,
) -> list[BlockerAlert]:
    """Find active Things that depend on other active (incomplete) Things.

    If thing_ids is provided, only check those specific Things.
    """
    if thing_ids:
        ph = ",".join("?" for _ in thing_ids)
        where_clause = f"AND t.id IN ({ph})"
        params: list[Any] = list(thing_ids)
    else:
        where_clause = ""
        params = []

    rows = conn.execute(
        f"""SELECT t.id AS thing_id, t.title AS thing_title,
                   blocker.id AS blocker_id, blocker.title AS blocker_title,
                   blocker.active AS blocker_active
            FROM thing_relationships r
            JOIN things t ON t.id = r.from_thing_id
            JOIN things blocker ON blocker.id = r.to_thing_id
            WHERE r.relationship_type = 'depends-on'
              AND t.active = 1
              AND blocker.active = 1
              {where_clause}
            ORDER BY t.title""",
        params,
    ).fetchall()

    alerts: list[BlockerAlert] = []
    for row in rows:
        alerts.append(
            BlockerAlert(
                alert_type="blocked_thing",
                thing_id=row["thing_id"],
                thing_title=row["thing_title"],
                message=f'"{row["thing_title"]}" is blocked by incomplete "{row["blocker_title"]}"',
                severity="warning",
                related_thing_ids=[row["blocker_id"]],
                extra={"blocker_id": row["blocker_id"], "blocker_title": row["blocker_title"]},
            )
        )
    return alerts


def find_deadline_conflicts(
    conn: sqlite3.Connection,
    thing_ids: list[str] | None = None,
) -> list[BlockerAlert]:
    """Find dependency deadline conflicts: a Thing has a deadline before its blocker's deadline."""
    if thing_ids:
        ph = ",".join("?" for _ in thing_ids)
        where_clause = f"AND t.id IN ({ph})"
        params: list[Any] = list(thing_ids)
    else:
        where_clause = ""
        params = []

    rows = conn.execute(
        f"""SELECT t.id AS thing_id, t.title AS thing_title,
                   t.checkin_date AS thing_checkin, t.data AS thing_data,
                   dep.id AS dep_id, dep.title AS dep_title,
                   dep.checkin_date AS dep_checkin, dep.data AS dep_data
            FROM thing_relationships r
            JOIN things t ON t.id = r.from_thing_id
            JOIN things dep ON dep.id = r.to_thing_id
            WHERE r.relationship_type = 'depends-on'
              AND t.active = 1
              AND dep.active = 1
              {where_clause}""",
        params,
    ).fetchall()

    alerts: list[BlockerAlert] = []
    for row in rows:
        thing_date = _get_date_from_thing(row)
        # Create a pseudo-row for the dependency
        dep_date = None
        if row["dep_checkin"]:
            dep_date = _parse_date_value(row["dep_checkin"])
        if not dep_date and row["dep_data"]:
            try:
                dep_data = json.loads(row["dep_data"]) if isinstance(row["dep_data"], str) else row["dep_data"]
            except (json.JSONDecodeError, TypeError):
                dep_data = {}
            if isinstance(dep_data, dict):
                for key in ("deadline", "due_date", "due", "end_date"):
                    val = dep_data.get(key)
                    if val:
                        dep_date = _parse_date_value(val)
                        if dep_date:
                            break

        if thing_date and dep_date and thing_date < dep_date:
            alerts.append(
                BlockerAlert(
                    alert_type="deadline_conflict",
                    thing_id=row["thing_id"],
                    thing_title=row["thing_title"],
                    message=(
                        f'Deadline conflict: "{row["thing_title"]}" is due {thing_date.isoformat()} '
                        f'but depends on "{row["dep_title"]}" due {dep_date.isoformat()}'
                    ),
                    severity="critical",
                    related_thing_ids=[row["dep_id"]],
                    extra={
                        "thing_deadline": thing_date.isoformat(),
                        "dep_deadline": dep_date.isoformat(),
                        "dep_id": row["dep_id"],
                        "dep_title": row["dep_title"],
                    },
                )
            )
    return alerts


def find_downstream_impact(
    conn: sqlite3.Connection,
    thing_ids: list[str] | None = None,
) -> list[BlockerAlert]:
    """Find Things that are transitively blocked (chain depth > 1).

    For each active blocked thing, walk the 'blocks' direction to find
    everything downstream that's impacted.
    """
    if thing_ids:
        ph = ",".join("?" for _ in thing_ids)
        where_clause = f"AND blocker.id IN ({ph})"
        params: list[Any] = list(thing_ids)
    else:
        where_clause = ""
        params = []

    # Find Things that block other active Things
    blockers = conn.execute(
        f"""SELECT DISTINCT blocker.id AS blocker_id, blocker.title AS blocker_title
            FROM thing_relationships r
            JOIN things blocker ON blocker.id = r.to_thing_id
            JOIN things blocked ON blocked.id = r.from_thing_id
            WHERE r.relationship_type = 'depends-on'
              AND blocker.active = 1
              AND blocked.active = 1
              {where_clause}""",
        params,
    ).fetchall()

    alerts: list[BlockerAlert] = []
    for blocker_row in blockers:
        # BFS to find downstream impact
        visited: set[str] = set()
        queue = [blocker_row["blocker_id"]]
        downstream: list[str] = []

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            # Find things that depend on current
            dependents = conn.execute(
                """SELECT t.id, t.title FROM thing_relationships r
                   JOIN things t ON t.id = r.from_thing_id
                   WHERE r.to_thing_id = ? AND r.relationship_type = 'depends-on'
                     AND t.active = 1""",
                (current,),
            ).fetchall()

            for dep in dependents:
                if dep["id"] not in visited:
                    downstream.append(dep["id"])
                    queue.append(dep["id"])

        if len(downstream) > 1:  # More than direct dependency = chain impact
            alerts.append(
                BlockerAlert(
                    alert_type="downstream_impact",
                    thing_id=blocker_row["blocker_id"],
                    thing_title=blocker_row["blocker_title"],
                    message=(
                        f'"{blocker_row["blocker_title"]}" blocks {len(downstream)} '
                        f'downstream item{"s" if len(downstream) != 1 else ""}'
                    ),
                    severity="warning",
                    related_thing_ids=downstream,
                    extra={"downstream_count": len(downstream)},
                )
            )
    return alerts


def find_schedule_overlaps(
    conn: sqlite3.Connection,
    thing_ids: list[str] | None = None,
) -> list[BlockerAlert]:
    """Find Things with the same checkin_date or deadline that might conflict."""
    if thing_ids:
        ph = ",".join("?" for _ in thing_ids)
        where_clause = f"AND t.id IN ({ph})"
        params: list[Any] = list(thing_ids)
    else:
        where_clause = ""
        params = []

    rows = conn.execute(
        f"""SELECT t.id, t.title, t.checkin_date, t.data, t.priority
            FROM things t
            WHERE t.active = 1
              AND (t.checkin_date IS NOT NULL OR (t.data IS NOT NULL AND t.data != '{{}}'))
              AND t.type_hint IN ('task', 'project', 'goal', 'event')
              {where_clause}""",
        params,
    ).fetchall()

    # Group things by date
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        d = _get_date_from_thing(row)
        if d:
            key = d.isoformat()
            by_date.setdefault(key, []).append({"id": row["id"], "title": row["title"], "priority": row["priority"]})

    alerts: list[BlockerAlert] = []
    for date_str, things in by_date.items():
        if len(things) >= 2:
            # Only flag if there are high-priority items competing
            high_pri = [t for t in things if t["priority"] <= 2]
            if len(high_pri) >= 2:
                titles = [t["title"] for t in high_pri[:3]]
                alerts.append(
                    BlockerAlert(
                        alert_type="schedule_overlap",
                        thing_id=high_pri[0]["id"],
                        thing_title=high_pri[0]["title"],
                        message=f'Schedule conflict on {date_str}: {", ".join(titles)}',
                        severity="info",
                        related_thing_ids=[t["id"] for t in high_pri[1:]],
                        extra={"date": date_str, "count": len(high_pri)},
                    )
                )
    return alerts


def find_circular_dependencies(
    conn: sqlite3.Connection,
    thing_ids: list[str] | None = None,
) -> list[BlockerAlert]:
    """Detect circular dependency chains among active Things."""
    if thing_ids:
        ph = ",".join("?" for _ in thing_ids)
        where_clause = f"AND (r.from_thing_id IN ({ph}) OR r.to_thing_id IN ({ph}))"
        params: list[Any] = list(thing_ids) + list(thing_ids)
    else:
        where_clause = ""
        params = []

    edges = conn.execute(
        f"""SELECT r.from_thing_id, r.to_thing_id
            FROM thing_relationships r
            JOIN things t1 ON t1.id = r.from_thing_id
            JOIN things t2 ON t2.id = r.to_thing_id
            WHERE r.relationship_type = 'depends-on'
              AND t1.active = 1 AND t2.active = 1
              {where_clause}""",
        params,
    ).fetchall()

    # Build adjacency list
    graph: dict[str, list[str]] = {}
    for edge in edges:
        graph.setdefault(edge["from_thing_id"], []).append(edge["to_thing_id"])

    # DFS cycle detection
    visited: set[str] = set()
    in_stack: set[str] = set()
    cycles_found: set[frozenset[str]] = set()

    def dfs(node: str, path: list[str]) -> None:
        if node in in_stack:
            # Found cycle — extract it
            cycle_start = path.index(node)
            cycle = frozenset(path[cycle_start:])
            cycles_found.add(cycle)
            return
        if node in visited:
            return
        visited.add(node)
        in_stack.add(node)
        path.append(node)
        for neighbor in graph.get(node, []):
            dfs(neighbor, path)
        path.pop()
        in_stack.discard(node)

    for node in graph:
        if node not in visited:
            dfs(node, [])

    alerts: list[BlockerAlert] = []
    for cycle in cycles_found:
        cycle_list = list(cycle)
        # Fetch titles
        ph = ",".join("?" for _ in cycle_list)
        title_rows = conn.execute(
            f"SELECT id, title FROM things WHERE id IN ({ph})", cycle_list
        ).fetchall()
        titles = {r["id"]: r["title"] for r in title_rows}
        title_list = [titles.get(cid, cid[:8]) for cid in cycle_list[:3]]
        label = " → ".join(title_list)
        if len(cycle_list) > 3:
            label += f" (+ {len(cycle_list) - 3} more)"

        alerts.append(
            BlockerAlert(
                alert_type="circular_dependency",
                thing_id=cycle_list[0],
                thing_title=titles.get(cycle_list[0], ""),
                message=f"Circular dependency: {label}",
                severity="critical",
                related_thing_ids=cycle_list[1:],
                extra={"cycle_size": len(cycle_list)},
            )
        )
    return alerts


# ---------------------------------------------------------------------------
# Main detection entry point
# ---------------------------------------------------------------------------


def detect_blockers(
    proactivity_level: str = DEFAULT_PROACTIVITY,
    thing_ids: list[str] | None = None,
) -> list[BlockerAlert]:
    """Run blocker/conflict detection at the specified proactivity level.

    Args:
        proactivity_level: "off", "low", "medium", or "high"
        thing_ids: If provided, only check these specific Things (for real-time pipeline use)

    Returns:
        List of BlockerAlert objects sorted by severity (critical first)
    """
    enabled = PROACTIVITY_LEVELS.get(proactivity_level, PROACTIVITY_LEVELS[DEFAULT_PROACTIVITY])
    if not enabled:
        return []

    detectors = {
        "blocked_thing": find_blocked_things,
        "deadline_conflict": find_deadline_conflicts,
        "downstream_impact": find_downstream_impact,
        "schedule_overlap": find_schedule_overlaps,
        "circular_dependency": find_circular_dependencies,
    }

    alerts: list[BlockerAlert] = []
    with db() as conn:
        for detection_type in enabled:
            detector = detectors.get(detection_type)
            if detector:
                try:
                    alerts.extend(detector(conn, thing_ids))
                except Exception:
                    logger.exception("Blocker detection failed for %s", detection_type)

    # Deduplicate by (alert_type, thing_id)
    seen: dict[tuple[str, str], BlockerAlert] = {}
    for alert in alerts:
        key = (alert.alert_type, alert.thing_id)
        if key not in seen:
            seen[key] = alert

    result = list(seen.values())
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    result.sort(key=lambda a: (severity_order.get(a.severity, 9), a.thing_title))
    return result


def detect_blockers_for_context(
    thing_ids: list[str],
    proactivity_level: str = DEFAULT_PROACTIVITY,
) -> list[dict[str, Any]]:
    """Detect blockers for Things in the current conversation context.

    Returns a list of dicts suitable for injection into the reasoning agent prompt.
    """
    if not thing_ids or proactivity_level == "off":
        return []

    alerts = detect_blockers(proactivity_level=proactivity_level, thing_ids=thing_ids)
    return [
        {
            "alert_type": a.alert_type,
            "thing_id": a.thing_id,
            "thing_title": a.thing_title,
            "message": a.message,
            "severity": a.severity,
            "related_thing_ids": a.related_thing_ids,
        }
        for a in alerts
    ]
