"""Dependency detection sweep — find implicit dependencies between Things.

Phase 1 (SQL): Group active Things into clusters by project membership.
Phase 2 (LLM): Send each cluster to the LLM asking for implicit dependencies
               and scheduling conflicts.

Results are stored as ConnectionSuggestionRecord (user-reviewed dependencies)
and SweepFindingRecord (conflicts surfaced in daily briefing).
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_
from sqlmodel import Session, select

import backend.db_engine as _engine_mod
from .db_engine import user_filter_clause
from .db_models import (
    ConnectionSuggestionRecord,
    SweepFindingRecord,
    ThingRecord,
    ThingRelationshipRecord,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CLUSTER_SIZE = 20  # Max Things per LLM cluster
MAX_CLUSTERS_PER_SWEEP = 10  # Max clusters per sweep run

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DependencyCluster:
    """A group of Things to check for implicit dependencies."""

    cluster_id: str  # e.g., "project-<project_id>"
    label: str  # Human-readable label for prompt
    things: list[dict] = field(default_factory=list)  # {id, title, type_hint, checkin_date, data, user_id}
    user_id: str = ""


@dataclass
class DependencyDetectionResult:
    """Result of the dependency detection sweep."""

    clusters_found: int = 0
    suggestions_created: int = 0
    findings_created: int = 0
    suggestions: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Phase 1: SQL clustering
# ---------------------------------------------------------------------------


def find_dependency_clusters(user_id: str = "") -> list[DependencyCluster]:
    """Group active Things into clusters by project membership.

    A cluster is created for each project that has 2+ active children,
    excluding clusters where all pairs already have depends-on/blocks
    relationships.
    """
    with Session(_engine_mod.engine) as session:
        # Get all active Things
        thing_stmt = select(ThingRecord).where(ThingRecord.active == True)  # noqa: E712 — SQLAlchemy requires == for column comparisons; `is True` evaluates in Python, not SQL
        if user_id:
            thing_stmt = thing_stmt.where(
                user_filter_clause(ThingRecord.user_id, user_id)
            )
        things = session.exec(thing_stmt).all()
        thing_map = {
            t.id: {
                "id": t.id,
                "title": t.title,
                "type_hint": t.type_hint,
                "checkin_date": t.checkin_date.isoformat() if isinstance(t.checkin_date, (date, datetime)) else t.checkin_date,
                "data": t.data,
                "user_id": t.user_id,
            }
            for t in things
        }

        # Get project parent-of relationships (scoped to user's things)
        user_thing_ids = list(thing_map.keys())
        parent_stmt = (
            select(ThingRelationshipRecord)
            .where(ThingRelationshipRecord.relationship_type == "parent-of")
            .where(ThingRelationshipRecord.from_thing_id.in_(user_thing_ids))  # type: ignore[union-attr]
        )
        parent_rels = session.exec(parent_stmt).all()

        # Get existing depends-on/blocks relationships for dedup (scoped to user's things)
        dep_stmt = select(ThingRelationshipRecord).where(
            ThingRelationshipRecord.relationship_type.in_(["depends-on", "blocks"]),  # type: ignore[union-attr]
            ThingRelationshipRecord.from_thing_id.in_(user_thing_ids),               # type: ignore[union-attr]
        )
        dep_rels = session.exec(dep_stmt).all()
        existing_deps: set[tuple[str, str]] = set()
        for r in dep_rels:
            existing_deps.add((r.from_thing_id, r.to_thing_id))
            existing_deps.add((r.to_thing_id, r.from_thing_id))

    # Group children by project
    project_children: dict[str, list[dict]] = {}
    project_titles: dict[str, str] = {}
    active_ids = set(thing_map.keys())

    for rel in parent_rels:
        project = thing_map.get(rel.from_thing_id)
        child = thing_map.get(rel.to_thing_id)
        if not project or not child:
            continue
        if project.get("type_hint") != "project":
            continue
        if rel.to_thing_id not in active_ids:
            continue

        pid = rel.from_thing_id
        if pid not in project_children:
            project_children[pid] = []
            project_titles[pid] = project["title"]
        project_children[pid].append(child)

    clusters: list[DependencyCluster] = []

    for pid, children in project_children.items():
        if len(children) < 2:
            continue

        # Skip if ALL pairs already have depends-on/blocks
        child_ids = [c["id"] for c in children]
        if all((a, b) in existing_deps for i, a in enumerate(child_ids) for b in child_ids[i + 1:]):
            continue

        # Cap cluster size
        capped = children[:MAX_CLUSTER_SIZE]

        cluster_user_id = capped[0].get("user_id", "") or ""

        clusters.append(DependencyCluster(
            cluster_id=f"project-{pid}",
            label=project_titles[pid],
            things=capped,
            user_id=cluster_user_id,
        ))

    # Cap total clusters
    return clusters[:MAX_CLUSTERS_PER_SWEEP]


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

DEPENDENCY_DETECTION_SYSTEM = """\
You are the Dependency Analyst for Reli, an AI personal information manager.
You are given a cluster of active Things that belong to the same project or
date window. Your job is to identify:

1. IMPLICIT DEPENDENCIES: pairs of Things where one must logically happen before
   the other, but no explicit relationship exists yet.
2. CONFLICTS: situations where the implicit dependency creates a scheduling
   problem (e.g., a blocker's timeline is too tight given the blocked thing's deadline).

Respond with ONLY valid JSON (no markdown, no explanation):
{
  "dependencies": [
    {
      "from_id": "...",
      "to_id": "...",
      "relationship_type": "depends-on",
      "reason": "Flights must be booked after work holidays are approved to avoid rescheduling costs",
      "confidence": 0.85
    }
  ],
  "conflicts": [
    {
      "thing_id": "...",
      "related_thing_ids": ["..."],
      "message": "Can't book flights before holidays are approved — the approval window may be too tight",
      "severity": "warning",
      "priority": 1
    }
  ]
}

Rules:
- relationship_type: use "depends-on" (from needs to done first) or "blocks" (from prevents to)
- confidence: 0.0-1.0. Only include dependencies with confidence >= 0.6
- severity: "critical" (deadline already at risk), "warning" (potential problem), "info" (FYI)
- priority: 0=critical, 1=high, 2=medium, 3=low
- message: written for the USER, warm and direct, explain the real-world risk
- Do NOT invent dependencies. Only report ones with genuine semantic justification.
- If no dependencies or conflicts exist, return {"dependencies": [], "conflicts": []}
- Keep to the most important findings (max 5 dependencies, max 3 conflicts per cluster).
"""


def _format_cluster_for_llm(cluster: DependencyCluster) -> str:
    """Format a cluster into a prompt string for the LLM."""
    lines = [
        f"Cluster: {cluster.label}",
        f"Today: {date.today().isoformat()}",
        f"{len(cluster.things)} Things:",
        "",
    ]
    for t in cluster.things:
        checkin = f", checkin: {t['checkin_date']}" if t.get("checkin_date") else ""
        type_str = f" [{t['type_hint']}]" if t.get("type_hint") else ""
        # Extract any deadline from data JSON
        deadline = ""
        raw_data = t.get("data")
        if raw_data:
            try:
                data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                for key in ("deadline", "due_date", "due"):
                    if key in data:
                        deadline = f", deadline: {data[key]}"
                        break
            except (json.JSONDecodeError, TypeError):
                pass
        lines.append(f'- "{t["title"]}"{type_str} (id={t["id"]}{checkin}{deadline})')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 2: LLM detection + DB writes
# ---------------------------------------------------------------------------


async def detect_cluster_dependencies(
    clusters: list[DependencyCluster],
    user_id: str = "",
) -> DependencyDetectionResult:
    """Send clusters to LLM and create suggestions/findings from results."""
    from .agents import UsageStats, _chat

    usage_stats = UsageStats()
    all_suggestions: list[dict] = []
    all_findings: list[dict] = []

    for cluster in clusters:
        try:
            prompt = _format_cluster_for_llm(cluster)
            cluster_thing_ids = {t["id"] for t in cluster.things}

            raw = await _chat(
                messages=[
                    {"role": "system", "content": DEPENDENCY_DETECTION_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                model=None,
                response_format={"type": "json_object"},
                usage_stats=usage_stats,
            )
        except Exception as exc:
            logger.warning(
                "Dependency sweep: LLM call failed for cluster %s (%s): %s",
                cluster.cluster_id,
                cluster.label,
                exc,
            )
            continue

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Dependency detection returned invalid JSON: %s", raw[:200])
            continue

        raw_deps = parsed.get("dependencies", [])
        if not isinstance(raw_deps, list):
            raw_deps = []

        raw_conflicts = parsed.get("conflicts", [])
        if not isinstance(raw_conflicts, list):
            raw_conflicts = []

        now = datetime.now(timezone.utc)

        try:
            with Session(_engine_mod.engine) as session:
                # Process dependencies → ConnectionSuggestionRecord
                for dep in raw_deps:
                    if not isinstance(dep, dict):
                        continue

                    from_id = dep.get("from_id", "")
                    to_id = dep.get("to_id", "")
                    if not from_id or not to_id:
                        continue

                    # Validate IDs are in this cluster
                    if from_id not in cluster_thing_ids or to_id not in cluster_thing_ids:
                        continue

                    confidence = dep.get("confidence", 0.0)
                    if not isinstance(confidence, (int, float)):
                        confidence = 0.0
                    confidence = max(0.0, min(1.0, float(confidence)))
                    if confidence < 0.6:
                        continue

                    rel_type = str(dep.get("relationship_type", "depends-on")).strip()
                    if not rel_type:
                        rel_type = "depends-on"

                    reason = str(dep.get("reason", "")).strip()
                    if not reason:
                        continue

                    # Check for existing suggestion in either direction (pending/deferred)
                    existing_sugg = session.exec(
                        select(ConnectionSuggestionRecord).where(
                            ConnectionSuggestionRecord.status.in_(["pending", "deferred"]),  # type: ignore[union-attr]
                            or_(
                                (ConnectionSuggestionRecord.from_thing_id == from_id) & (ConnectionSuggestionRecord.to_thing_id == to_id),
                                (ConnectionSuggestionRecord.from_thing_id == to_id) & (ConnectionSuggestionRecord.to_thing_id == from_id),
                            ),
                        )
                    ).first()
                    if existing_sugg:
                        continue

                    # Check for existing relationship in this direction
                    # (Phase 1 clustering already pre-filters fully-covered pairs, so false
                    #  negatives here are rare and harmless — the suggestion will be deduped
                    #  by the reverse-direction suggestion check above if it exists.)
                    existing_rel = session.exec(
                        select(ThingRelationshipRecord).where(
                            ThingRelationshipRecord.from_thing_id == from_id,
                            ThingRelationshipRecord.to_thing_id == to_id,
                        )
                    ).first()
                    if existing_rel:
                        continue

                    sugg_id = f"cs-{uuid.uuid4().hex[:8]}"
                    from_thing = session.get(ThingRecord, from_id)
                    sugg_user_id = from_thing.user_id if from_thing else None

                    suggestion = ConnectionSuggestionRecord(
                        id=sugg_id,
                        from_thing_id=from_id,
                        to_thing_id=to_id,
                        suggested_relationship_type=rel_type,
                        reason=reason,
                        confidence=confidence,
                        status="pending",
                        created_at=now,
                        user_id=sugg_user_id,
                    )
                    session.add(suggestion)
                    all_suggestions.append({
                        "id": sugg_id,
                        "from_thing_id": from_id,
                        "to_thing_id": to_id,
                        "suggested_relationship_type": rel_type,
                        "reason": reason,
                        "confidence": confidence,
                    })

                # Process conflicts → SweepFindingRecord
                for conflict in raw_conflicts:
                    if not isinstance(conflict, dict):
                        continue

                    thing_id = conflict.get("thing_id", "")
                    if not thing_id or thing_id not in cluster_thing_ids:
                        continue

                    message = str(conflict.get("message", "")).strip()
                    if not message:
                        continue

                    priority = conflict.get("priority", 2)
                    if not isinstance(priority, int) or priority < 0 or priority > 3:
                        priority = 2

                    expires_at = now + timedelta(days=7)

                    # Resolve user_id from thing
                    thing_rec = session.get(ThingRecord, thing_id)
                    finding_user_id = thing_rec.user_id if thing_rec else (user_id or None)

                    finding_id = f"sf-{uuid.uuid4().hex[:8]}"
                    session.add(SweepFindingRecord(
                        id=finding_id,
                        thing_id=thing_id,
                        finding_type="llm_conflict",
                        message=message,
                        priority=priority,
                        dismissed=False,
                        created_at=now,
                        expires_at=expires_at,
                        user_id=finding_user_id,
                    ))
                    all_findings.append({
                        "id": finding_id,
                        "thing_id": thing_id,
                        "finding_type": "llm_conflict",
                        "message": message,
                        "priority": priority,
                    })

                session.commit()
        except Exception as exc:
            logger.warning(
                "Dependency sweep: DB write failed for cluster %s: %s",
                cluster.cluster_id,
                exc,
            )
            continue

    return DependencyDetectionResult(
        clusters_found=len(clusters),
        suggestions_created=len(all_suggestions),
        findings_created=len(all_findings),
        suggestions=all_suggestions,
        findings=all_findings,
        usage=usage_stats.to_dict(),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run_dependency_sweep(user_id: str = "") -> DependencyDetectionResult:
    """Run the full dependency detection sweep."""
    clusters = find_dependency_clusters(user_id=user_id)
    logger.info("Dependency sweep: %d clusters found", len(clusters))
    if not clusters:
        return DependencyDetectionResult()
    result = await detect_cluster_dependencies(clusters, user_id=user_id)
    logger.info(
        "Dependency sweep complete: %d suggestions, %d findings",
        result.suggestions_created,
        result.findings_created,
    )
    return result
