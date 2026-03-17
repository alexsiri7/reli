"""Cross-project pattern detection for the nightly sweep.

Analyzes Things across multiple projects to detect:
  - shared_blocker: A Thing that blocks tasks in multiple projects
  - resource_conflict: A person/resource linked to active tasks across projects
  - thematic_connection: Tasks in different projects with similar themes
  - duplicated_effort: Tasks in different projects doing the same work

Findings are stored as Things with type_hint='sweep-finding' and tagged
#sweep-finding in data.tags.  Each finding is linked to the relevant Things
via relationships.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .database import db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Finding data structure
# ---------------------------------------------------------------------------

FINDING_TYPE_HINT = "sweep-finding"
SWEEP_FINDING_TAG = "#sweep-finding"


@dataclass
class CrossProjectFinding:
    """A cross-project pattern detected by the sweep."""

    finding_type: str  # shared_blocker | resource_conflict | thematic_connection | duplicated_effort
    title: str
    message: str
    related_thing_ids: list[str] = field(default_factory=list)
    related_project_ids: list[str] = field(default_factory=list)
    priority: int = 3  # 1-5 (reli priority scale)
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Detection queries
# ---------------------------------------------------------------------------


def _get_active_projects(conn: sqlite3.Connection) -> list[dict]:
    """Return active projects that have at least one active child."""
    rows = conn.execute(
        """SELECT p.id, p.title
           FROM things p
           WHERE p.active = 1
             AND p.type_hint = 'project'
             AND EXISTS (
                 SELECT 1 FROM things c
                 WHERE c.parent_id = p.id AND c.active = 1
             )
           ORDER BY p.title"""
    ).fetchall()
    return [{"id": row["id"], "title": row["title"]} for row in rows]


def find_shared_blockers(conn: sqlite3.Connection) -> list[CrossProjectFinding]:
    """Find Things that block tasks across multiple projects.

    A "shared blocker" is a Thing connected via 'blocks' or 'blocked_by'
    relationships to active tasks in 2+ distinct projects.
    """
    # Find Things that are the target of 'blocks' relationships (or source of
    # 'blocked_by') pointing to tasks in different projects.
    rows = conn.execute(
        """SELECT blocker.id AS blocker_id,
                  blocker.title AS blocker_title,
                  GROUP_CONCAT(DISTINCT task_project.id) AS project_ids,
                  GROUP_CONCAT(DISTINCT task_project.title) AS project_titles,
                  GROUP_CONCAT(DISTINCT blocked_task.id) AS task_ids,
                  COUNT(DISTINCT task_project.id) AS project_count
           FROM thing_relationships r
           JOIN things blocker ON blocker.id = r.from_thing_id
           JOIN things blocked_task ON blocked_task.id = r.to_thing_id
           JOIN things task_project ON blocked_task.parent_id = task_project.id
           WHERE r.relationship_type IN ('blocks', 'blocking')
             AND blocked_task.active = 1
             AND task_project.type_hint = 'project'
             AND task_project.active = 1
           GROUP BY blocker.id
           HAVING project_count >= 2"""
    ).fetchall()

    findings: list[CrossProjectFinding] = []
    for row in rows:
        proj_titles = row["project_titles"].split(",")
        findings.append(
            CrossProjectFinding(
                finding_type="shared_blocker",
                title=f"Shared blocker: {row['blocker_title']}",
                message=(
                    f'"{row["blocker_title"]}" is blocking tasks across '
                    f'{row["project_count"]} projects: {", ".join(proj_titles)}'
                ),
                related_thing_ids=row["task_ids"].split(",") + [row["blocker_id"]],
                related_project_ids=row["project_ids"].split(","),
                priority=2,
                extra={
                    "blocker_id": row["blocker_id"],
                    "blocker_title": row["blocker_title"],
                    "project_count": row["project_count"],
                },
            )
        )
    return findings


def find_resource_conflicts(conn: sqlite3.Connection) -> list[CrossProjectFinding]:
    """Find people/resources assigned to active tasks in multiple projects.

    A "resource conflict" is a Thing (typically type_hint='person') that has
    relationships to active tasks spanning 2+ distinct projects.
    """
    # Look for Things connected to tasks in multiple projects via any
    # assignment-like relationship.
    assignment_types = (
        "assigned_to",
        "assignee",
        "responsible",
        "works_on",
        "owner",
        "owned_by",
    )
    placeholders = ",".join("?" * len(assignment_types))

    rows = conn.execute(
        f"""SELECT resource.id AS resource_id,
                   resource.title AS resource_title,
                   resource.type_hint AS resource_type,
                   GROUP_CONCAT(DISTINCT task_project.id) AS project_ids,
                   GROUP_CONCAT(DISTINCT task_project.title) AS project_titles,
                   GROUP_CONCAT(DISTINCT task.id) AS task_ids,
                   COUNT(DISTINCT task_project.id) AS project_count
            FROM thing_relationships r
            JOIN things resource ON (
                (resource.id = r.from_thing_id AND r.to_thing_id IN (
                    SELECT id FROM things WHERE parent_id IS NOT NULL AND active = 1
                ))
                OR
                (resource.id = r.to_thing_id AND r.from_thing_id IN (
                    SELECT id FROM things WHERE parent_id IS NOT NULL AND active = 1
                ))
            )
            JOIN things task ON (
                (task.id = r.to_thing_id AND resource.id = r.from_thing_id)
                OR
                (task.id = r.from_thing_id AND resource.id = r.to_thing_id)
            )
            JOIN things task_project ON task.parent_id = task_project.id
            WHERE r.relationship_type IN ({placeholders})
              AND task.active = 1
              AND task_project.type_hint = 'project'
              AND task_project.active = 1
              AND task.id != resource.id
            GROUP BY resource.id
            HAVING project_count >= 2""",
        assignment_types,
    ).fetchall()

    findings: list[CrossProjectFinding] = []
    for row in rows:
        proj_titles = row["project_titles"].split(",")
        resource_type = row["resource_type"] or "resource"
        findings.append(
            CrossProjectFinding(
                finding_type="resource_conflict",
                title=f"Resource conflict: {row['resource_title']}",
                message=(
                    f'{resource_type.title()} "{row["resource_title"]}" is assigned to '
                    f"active tasks across {row['project_count']} projects: "
                    f'{", ".join(proj_titles)}'
                ),
                related_thing_ids=row["task_ids"].split(",") + [row["resource_id"]],
                related_project_ids=row["project_ids"].split(","),
                priority=2,
                extra={
                    "resource_id": row["resource_id"],
                    "resource_type": resource_type,
                    "project_count": row["project_count"],
                },
            )
        )
    return findings


def find_thematic_connections(
    conn: sqlite3.Connection,
    min_word_overlap: int = 3,
) -> list[CrossProjectFinding]:
    """Find tasks in different projects with similar themes.

    Uses word-level overlap between task titles to detect thematic connections.
    A pair qualifies when they share at least *min_word_overlap* significant
    words and belong to different projects.
    """
    # Stopwords to exclude from comparison
    stopwords = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "it", "as", "be", "was", "are",
        "this", "that", "not", "do", "has", "have", "had", "will", "can",
        "should", "would", "could", "may", "up", "out", "if", "no", "so",
    }

    # Get all active tasks that belong to a project
    rows = conn.execute(
        """SELECT t.id, t.title, t.parent_id, p.title AS project_title
           FROM things t
           JOIN things p ON t.parent_id = p.id
           WHERE t.active = 1
             AND p.type_hint = 'project'
             AND p.active = 1
           ORDER BY t.title"""
    ).fetchall()

    if len(rows) < 2:
        return []

    # Build word sets for each task
    task_words: list[tuple[dict, set[str]]] = []
    for row in rows:
        words = {
            w.lower()
            for w in row["title"].split()
            if len(w) > 2 and w.lower() not in stopwords
        }
        if words:
            task_words.append(
                (
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "project_id": row["parent_id"],
                        "project_title": row["project_title"],
                    },
                    words,
                )
            )

    # Compare pairs across different projects
    seen_pairs: set[tuple[str, str]] = set()
    findings: list[CrossProjectFinding] = []

    for i, (task_a, words_a) in enumerate(task_words):
        for task_b, words_b in task_words[i + 1 :]:
            if task_a["project_id"] == task_b["project_id"]:
                continue  # same project, skip

            pair_key = tuple(sorted([task_a["id"], task_b["id"]]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            overlap = words_a & words_b
            if len(overlap) >= min_word_overlap:
                findings.append(
                    CrossProjectFinding(
                        finding_type="thematic_connection",
                        title=f"Thematic link: {task_a['title'][:40]} ↔ {task_b['title'][:40]}",
                        message=(
                            f'Tasks share common themes across projects: '
                            f'"{task_a["title"]}" ({task_a["project_title"]}) and '
                            f'"{task_b["title"]}" ({task_b["project_title"]}). '
                            f'Shared keywords: {", ".join(sorted(overlap))}'
                        ),
                        related_thing_ids=[task_a["id"], task_b["id"]],
                        related_project_ids=[task_a["project_id"], task_b["project_id"]],
                        priority=3,
                        extra={
                            "overlap_words": sorted(overlap),
                            "overlap_count": len(overlap),
                        },
                    )
                )

    return findings


def find_duplicated_effort(conn: sqlite3.Connection) -> list[CrossProjectFinding]:
    """Find tasks in different projects that appear to duplicate work.

    Uses tighter matching than thematic_connections — looks for tasks with
    highly similar titles (>60% word overlap) across projects.
    """
    stopwords = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "it", "as", "be", "was", "are",
        "this", "that", "not", "do", "has", "have", "had", "will", "can",
        "should", "would", "could", "may", "up", "out", "if", "no", "so",
    }

    rows = conn.execute(
        """SELECT t.id, t.title, t.parent_id, p.title AS project_title
           FROM things t
           JOIN things p ON t.parent_id = p.id
           WHERE t.active = 1
             AND p.type_hint = 'project'
             AND p.active = 1
           ORDER BY t.title"""
    ).fetchall()

    if len(rows) < 2:
        return []

    task_words: list[tuple[dict, set[str]]] = []
    for row in rows:
        words = {
            w.lower()
            for w in row["title"].split()
            if len(w) > 2 and w.lower() not in stopwords
        }
        if words:
            task_words.append(
                (
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "project_id": row["parent_id"],
                        "project_title": row["project_title"],
                    },
                    words,
                )
            )

    seen_pairs: set[tuple[str, str]] = set()
    findings: list[CrossProjectFinding] = []

    for i, (task_a, words_a) in enumerate(task_words):
        for task_b, words_b in task_words[i + 1 :]:
            if task_a["project_id"] == task_b["project_id"]:
                continue

            pair_key = tuple(sorted([task_a["id"], task_b["id"]]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            overlap = words_a & words_b
            union = words_a | words_b
            if not union:
                continue

            similarity = len(overlap) / len(union)
            if similarity >= 0.6:
                pct = int(similarity * 100)
                findings.append(
                    CrossProjectFinding(
                        finding_type="duplicated_effort",
                        title=f"Possible duplicate: {task_a['title'][:40]} ↔ {task_b['title'][:40]}",
                        message=(
                            f"Potential duplicated effort ({pct}% similar): "
                            f'"{task_a["title"]}" ({task_a["project_title"]}) and '
                            f'"{task_b["title"]}" ({task_b["project_title"]})'
                        ),
                        related_thing_ids=[task_a["id"], task_b["id"]],
                        related_project_ids=[task_a["project_id"], task_b["project_id"]],
                        priority=2,
                        extra={
                            "similarity": round(similarity, 2),
                            "overlap_words": sorted(overlap),
                        },
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# Collect all cross-project findings
# ---------------------------------------------------------------------------


def collect_cross_project_findings() -> list[CrossProjectFinding]:
    """Run all cross-project detection queries and return findings.

    Only runs when there are 2+ active projects with active children.
    """
    with db() as conn:
        projects = _get_active_projects(conn)
        if len(projects) < 2:
            logger.info(
                "Cross-project sweep skipped: %d active project(s) (need 2+)",
                len(projects),
            )
            return []

        findings = (
            find_shared_blockers(conn)
            + find_resource_conflicts(conn)
            + find_thematic_connections(conn)
            + find_duplicated_effort(conn)
        )

    # Deduplicate by (finding_type, sorted related_thing_ids)
    seen: dict[tuple[str, str], CrossProjectFinding] = {}
    for f in findings:
        key = (f.finding_type, ",".join(sorted(f.related_thing_ids)))
        if key not in seen or f.priority < seen[key].priority:
            seen[key] = f

    result = list(seen.values())
    result.sort(key=lambda f: (f.priority, f.title))
    return result


# ---------------------------------------------------------------------------
# Persist findings as Things tagged #sweep-finding
# ---------------------------------------------------------------------------


def persist_findings(
    findings: list[CrossProjectFinding],
    user_id: str | None = None,
) -> list[dict]:
    """Store cross-project findings as Things tagged #sweep-finding.

    Each finding becomes a Thing with:
      - type_hint = 'sweep-finding'
      - data.tags = ['#sweep-finding']
      - data.finding_type = the detection category
      - data.related_project_ids = projects involved
      - Relationships to the relevant Things

    Existing sweep-finding Things from the same detection run are deactivated
    first to avoid accumulation.

    Returns the list of created Thing dicts.
    """
    now = datetime.now(timezone.utc).isoformat()
    created: list[dict] = []

    with db() as conn:
        # Deactivate previous cross-project findings to avoid stale accumulation.
        # We only deactivate findings that were auto-generated (have the tag).
        conn.execute(
            """UPDATE things
               SET active = 0, updated_at = ?
               WHERE type_hint = ?
                 AND active = 1
                 AND data LIKE ?""",
            (now, FINDING_TYPE_HINT, f'%"{SWEEP_FINDING_TAG}"%'),
        )

        for finding in findings:
            thing_id = f"cpf-{uuid.uuid4().hex[:12]}"
            data = {
                "tags": [SWEEP_FINDING_TAG],
                "finding_type": finding.finding_type,
                "message": finding.message,
                "related_project_ids": finding.related_project_ids,
                **finding.extra,
            }

            conn.execute(
                """INSERT INTO things
                   (id, title, type_hint, priority, active, surface, data,
                    created_at, updated_at, user_id)
                   VALUES (?, ?, ?, ?, 1, 1, ?, ?, ?, ?)""",
                (
                    thing_id,
                    finding.title,
                    FINDING_TYPE_HINT,
                    finding.priority,
                    json.dumps(data),
                    now,
                    now,
                    user_id,
                ),
            )

            # Create relationships to related Things
            for related_id in finding.related_thing_ids:
                rel_id = f"cpfr-{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """INSERT OR IGNORE INTO thing_relationships
                       (id, from_thing_id, to_thing_id, relationship_type, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (rel_id, thing_id, related_id, "sweep_finding_about", now),
                )

            created.append(
                {
                    "id": thing_id,
                    "title": finding.title,
                    "finding_type": finding.finding_type,
                    "message": finding.message,
                    "priority": finding.priority,
                    "related_thing_ids": finding.related_thing_ids,
                    "related_project_ids": finding.related_project_ids,
                }
            )

    return created


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_cross_project_sweep(user_id: str | None = None) -> dict:
    """Run the full cross-project pattern detection sweep.

    1. Collect findings via SQL queries
    2. Persist findings as Things tagged #sweep-finding

    Returns summary dict with counts and created findings.
    """
    findings = collect_cross_project_findings()

    if not findings:
        logger.info("Cross-project sweep: no patterns detected")
        return {"findings_detected": 0, "findings_created": []}

    created = persist_findings(findings, user_id=user_id)
    logger.info("Cross-project sweep: %d patterns detected, %d findings created", len(findings), len(created))

    return {
        "findings_detected": len(findings),
        "findings_created": created,
    }
