"""Tests for the dependency detection sweep."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, select

import backend.db_engine as _engine_mod
from backend.db_models import ConnectionSuggestionRecord, SweepFindingRecord
from backend.dependency_sweep import (
    DependencyCluster,
    _format_cluster_for_llm,
    find_dependency_clusters,
    run_dependency_sweep,
)


@pytest.fixture(autouse=True)
def _fresh_db(patched_db):
    """Use the shared patched_db fixture from conftest."""


def _insert_thing(
    db,
    title: str,
    type_hint: str = "task",
    data: dict | None = None,
    checkin_date: str | None = None,
    active: bool = True,
) -> str:
    thing_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            """INSERT INTO things
               (id, title, type_hint, importance, active, surface, data, checkin_date, created_at, updated_at)
               VALUES (?, ?, ?, 2, ?, 1, ?, ?, datetime('now'), datetime('now'))""",
            (thing_id, title, type_hint, int(active), json.dumps(data) if data else None, checkin_date),
        )
    return thing_id


def _insert_relationship(db, from_id: str, to_id: str, rel_type: str) -> str:
    rel_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type) VALUES (?, ?, ?, ?)",
            (rel_id, from_id, to_id, rel_type),
        )
    return rel_id


class TestFindDependencyClusters:
    def test_groups_children_of_same_project(self, db):
        """Tasks sharing a project become a cluster."""
        proj = _insert_thing(db, "Spain Trip", type_hint="project")
        task_a = _insert_thing(db, "Book flights")
        task_b = _insert_thing(db, "Approve holidays")
        _insert_relationship(db, proj, task_a, "parent-of")
        _insert_relationship(db, proj, task_b, "parent-of")

        clusters = find_dependency_clusters()

        assert len(clusters) == 1
        thing_ids = {t["id"] for t in clusters[0].things}
        assert task_a in thing_ids
        assert task_b in thing_ids
        assert clusters[0].label == "Spain Trip"

    def test_solo_project_child_excluded(self, db):
        """A project with only one child should not create a cluster."""
        proj = _insert_thing(db, "Solo Project", type_hint="project")
        task_a = _insert_thing(db, "Only task")
        _insert_relationship(db, proj, task_a, "parent-of")

        clusters = find_dependency_clusters()
        assert len(clusters) == 0

    def test_inactive_things_excluded(self, db):
        """Inactive Things should not appear in clusters."""
        proj = _insert_thing(db, "Trip", type_hint="project")
        task_a = _insert_thing(db, "Active task")
        task_b = _insert_thing(db, "Done task", active=False)
        _insert_relationship(db, proj, task_a, "parent-of")
        _insert_relationship(db, proj, task_b, "parent-of")

        clusters = find_dependency_clusters()
        assert len(clusters) == 0  # Only 1 active child → no cluster

    def test_empty_db_returns_empty(self):
        assert find_dependency_clusters() == []

    def test_partially_covered_cluster_still_included(self, db):
        """A cluster with at least one uncovered pair is included even if others are covered."""
        proj = _insert_thing(db, "Project", type_hint="project")
        a = _insert_thing(db, "Task A")
        b = _insert_thing(db, "Task B")
        c = _insert_thing(db, "Task C")
        _insert_relationship(db, proj, a, "parent-of")
        _insert_relationship(db, proj, b, "parent-of")
        _insert_relationship(db, proj, c, "parent-of")
        # Cover A→B but leave A→C and B→C uncovered
        _insert_relationship(db, a, b, "depends-on")

        clusters = find_dependency_clusters()
        assert len(clusters) == 1

    def test_fully_covered_cluster_skipped(self, db):
        """A cluster where ALL pairs have existing deps/blocks is skipped."""
        proj = _insert_thing(db, "Project", type_hint="project")
        a = _insert_thing(db, "Task A")
        b = _insert_thing(db, "Task B")
        _insert_relationship(db, proj, a, "parent-of")
        _insert_relationship(db, proj, b, "parent-of")
        # Cover the only pair
        _insert_relationship(db, a, b, "depends-on")

        clusters = find_dependency_clusters()
        assert len(clusters) == 0


class TestFormatClusterForLlm:
    def test_format_cluster_includes_deadline(self):
        """Cluster formatting includes deadline from data JSON."""
        cluster = DependencyCluster(
            cluster_id="project-x",
            label="Spain Trip",
            things=[
                {
                    "id": "a1",
                    "title": "Book flights",
                    "type_hint": "task",
                    "checkin_date": "2026-05-01",
                    "data": json.dumps({"due_date": "2026-04-30"}),
                    "user_id": "",
                },
            ],
        )
        result = _format_cluster_for_llm(cluster)
        assert "deadline: 2026-04-30" in result
        assert "checkin: 2026-05-01" in result

    def test_format_cluster_handles_malformed_data(self):
        """Cluster formatting should not raise on malformed data JSON."""
        cluster = DependencyCluster(
            cluster_id="project-x",
            label="Trip",
            things=[
                {
                    "id": "a1",
                    "title": "Task",
                    "type_hint": "task",
                    "checkin_date": None,
                    "data": "not valid json",
                    "user_id": "",
                },
            ],
        )
        # Should not raise
        result = _format_cluster_for_llm(cluster)
        assert '"Task"' in result


class TestDetectClusterDependencies:
    @pytest.mark.asyncio
    async def test_creates_suggestion_for_high_confidence_dependency(self, db):
        """LLM response with confidence >= 0.6 should create a ConnectionSuggestion."""
        proj = _insert_thing(db, "Spain Trip", type_hint="project")
        task_a_id = _insert_thing(db, "Book flights")
        task_b_id = _insert_thing(db, "Approve holidays")
        _insert_relationship(db, proj, task_a_id, "parent-of")
        _insert_relationship(db, proj, task_b_id, "parent-of")

        mock_response = json.dumps(
            {
                "dependencies": [
                    {
                        "from_id": task_a_id,
                        "to_id": task_b_id,
                        "relationship_type": "depends-on",
                        "reason": "Flights must wait for holiday approval",
                        "confidence": 0.85,
                    }
                ],
                "conflicts": [],
            }
        )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_response):
            result = await run_dependency_sweep()

        assert result.suggestions_created == 1
        with Session(_engine_mod.engine) as session:
            suggs = session.exec(select(ConnectionSuggestionRecord)).all()
        assert len(suggs) == 1
        assert suggs[0].suggested_relationship_type == "depends-on"

    @pytest.mark.asyncio
    async def test_skips_low_confidence_dependency(self, db):
        """Confidence < 0.6 should not create a suggestion."""
        proj = _insert_thing(db, "Trip", type_hint="project")
        task_a_id = _insert_thing(db, "Task A")
        task_b_id = _insert_thing(db, "Task B")
        _insert_relationship(db, proj, task_a_id, "parent-of")
        _insert_relationship(db, proj, task_b_id, "parent-of")

        mock_response = json.dumps(
            {
                "dependencies": [
                    {
                        "from_id": task_a_id,
                        "to_id": task_b_id,
                        "relationship_type": "depends-on",
                        "reason": "Maybe related",
                        "confidence": 0.3,
                    }
                ],
                "conflicts": [],
            }
        )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_response):
            result = await run_dependency_sweep()

        assert result.suggestions_created == 0

    @pytest.mark.asyncio
    async def test_creates_sweep_finding_for_conflict(self, db):
        """LLM-detected conflict should create a SweepFindingRecord."""
        proj = _insert_thing(db, "Trip", type_hint="project")
        task_a_id = _insert_thing(db, "Book flights", checkin_date="2026-05-01")
        task_b_id = _insert_thing(db, "Approve holidays", checkin_date="2026-04-25")
        _insert_relationship(db, proj, task_a_id, "parent-of")
        _insert_relationship(db, proj, task_b_id, "parent-of")

        mock_response = json.dumps(
            {
                "dependencies": [],
                "conflicts": [
                    {
                        "thing_id": task_a_id,
                        "related_thing_ids": [task_b_id],
                        "message": "Can't book flights before holidays are approved!",
                        "severity": "warning",
                        "priority": 1,
                    }
                ],
            }
        )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_response):
            result = await run_dependency_sweep()

        assert result.findings_created == 1
        with Session(_engine_mod.engine) as session:
            findings = session.exec(
                select(SweepFindingRecord).where(SweepFindingRecord.finding_type == "llm_conflict")
            ).all()
        assert len(findings) == 1
        assert "flights" in findings[0].message

    @pytest.mark.asyncio
    async def test_invalid_json_from_llm_returns_empty(self, db):
        """Invalid LLM JSON should not crash — return empty result."""
        proj = _insert_thing(db, "Trip", type_hint="project")
        _insert_relationship(db, proj, _insert_thing(db, "A"), "parent-of")
        _insert_relationship(db, proj, _insert_thing(db, "B"), "parent-of")

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value="not json"):
            result = await run_dependency_sweep()

        assert result.suggestions_created == 0
        assert result.findings_created == 0

    @pytest.mark.asyncio
    async def test_does_not_duplicate_existing_suggestion(self, db):
        """If a suggestion already exists for a pair, skip creating another."""
        proj = _insert_thing(db, "Trip", type_hint="project")
        task_a_id = _insert_thing(db, "Task A")
        task_b_id = _insert_thing(db, "Task B")
        _insert_relationship(db, proj, task_a_id, "parent-of")
        _insert_relationship(db, proj, task_b_id, "parent-of")

        # Pre-insert existing suggestion
        with Session(_engine_mod.engine) as session:
            session.add(
                ConnectionSuggestionRecord(
                    id="cs-existing",
                    from_thing_id=task_a_id,
                    to_thing_id=task_b_id,
                    suggested_relationship_type="depends-on",
                    reason="existing",
                    confidence=0.8,
                    status="pending",
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.commit()

        mock_response = json.dumps(
            {
                "dependencies": [
                    {
                        "from_id": task_a_id,
                        "to_id": task_b_id,
                        "relationship_type": "depends-on",
                        "reason": "again",
                        "confidence": 0.9,
                    }
                ],
                "conflicts": [],
            }
        )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_response):
            result = await run_dependency_sweep()

        assert result.suggestions_created == 0  # Already existed

    @pytest.mark.asyncio
    async def test_does_not_duplicate_reverse_direction_suggestion(self, db):
        """If a suggestion exists in reverse direction (B→A), skip creating A→B."""
        proj = _insert_thing(db, "Trip", type_hint="project")
        task_a_id = _insert_thing(db, "Task A")
        task_b_id = _insert_thing(db, "Task B")
        _insert_relationship(db, proj, task_a_id, "parent-of")
        _insert_relationship(db, proj, task_b_id, "parent-of")

        # Pre-insert suggestion in REVERSE direction (B→A)
        with Session(_engine_mod.engine) as session:
            session.add(
                ConnectionSuggestionRecord(
                    id="cs-rev",
                    from_thing_id=task_b_id,
                    to_thing_id=task_a_id,
                    suggested_relationship_type="depends-on",
                    reason="existing reverse",
                    confidence=0.8,
                    status="pending",
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.commit()

        # LLM suggests A→B
        mock_response = json.dumps(
            {
                "dependencies": [
                    {
                        "from_id": task_a_id,
                        "to_id": task_b_id,
                        "relationship_type": "depends-on",
                        "reason": "should be skipped",
                        "confidence": 0.9,
                    }
                ],
                "conflicts": [],
            }
        )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_response):
            result = await run_dependency_sweep()

        assert result.suggestions_created == 0

    @pytest.mark.asyncio
    async def test_skips_when_relationship_already_exists(self, db):
        """If a ThingRelationshipRecord already exists for a pair, skip suggestion."""
        proj = _insert_thing(db, "Trip", type_hint="project")
        task_a_id = _insert_thing(db, "Task A")
        task_b_id = _insert_thing(db, "Task B")
        _insert_relationship(db, proj, task_a_id, "parent-of")
        _insert_relationship(db, proj, task_b_id, "parent-of")
        _insert_relationship(db, task_a_id, task_b_id, "depends-on")  # actual relationship

        mock_response = json.dumps(
            {
                "dependencies": [
                    {
                        "from_id": task_a_id,
                        "to_id": task_b_id,
                        "relationship_type": "depends-on",
                        "reason": "already related",
                        "confidence": 0.9,
                    }
                ],
                "conflicts": [],
            }
        )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_response):
            result = await run_dependency_sweep()

        assert result.suggestions_created == 0

    @pytest.mark.asyncio
    async def test_rejects_ids_not_in_cluster(self, db):
        """LLM response referencing IDs outside the cluster should be silently dropped."""
        proj = _insert_thing(db, "Trip", type_hint="project")
        task_a_id = _insert_thing(db, "Task A")
        task_b_id = _insert_thing(db, "Task B")
        _insert_relationship(db, proj, task_a_id, "parent-of")
        _insert_relationship(db, proj, task_b_id, "parent-of")

        mock_response = json.dumps(
            {
                "dependencies": [
                    {
                        "from_id": "00000000-0000-0000-0000-000000000000",  # Not in cluster
                        "to_id": task_b_id,
                        "relationship_type": "depends-on",
                        "reason": "Hallucinated ID",
                        "confidence": 0.9,
                    }
                ],
                "conflicts": [],
            }
        )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_response):
            result = await run_dependency_sweep()

        assert result.suggestions_created == 0
