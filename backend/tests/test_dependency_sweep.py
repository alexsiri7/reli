"""Tests for the dependency detection sweep."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, select

import backend.db_engine as _engine_mod
from backend.database import db
from backend.db_models import ConnectionSuggestionRecord, SweepFindingRecord
from backend.dependency_sweep import find_dependency_clusters, run_dependency_sweep


@pytest.fixture(autouse=True)
def _fresh_db(patched_db):
    """Use the shared patched_db fixture from conftest."""


def _insert_thing(
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


def _insert_relationship(from_id: str, to_id: str, rel_type: str) -> str:
    rel_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type) VALUES (?, ?, ?, ?)",
            (rel_id, from_id, to_id, rel_type),
        )
    return rel_id


class TestFindDependencyClusters:
    def test_groups_children_of_same_project(self):
        """Tasks sharing a project become a cluster."""
        proj = _insert_thing("Spain Trip", type_hint="project")
        task_a = _insert_thing("Book flights")
        task_b = _insert_thing("Approve holidays")
        _insert_relationship(proj, task_a, "parent-of")
        _insert_relationship(proj, task_b, "parent-of")

        clusters = find_dependency_clusters()

        assert len(clusters) == 1
        thing_ids = {t["id"] for t in clusters[0].things}
        assert task_a in thing_ids
        assert task_b in thing_ids
        assert clusters[0].label == "Spain Trip"

    def test_solo_project_child_excluded(self):
        """A project with only one child should not create a cluster."""
        proj = _insert_thing("Solo Project", type_hint="project")
        task_a = _insert_thing("Only task")
        _insert_relationship(proj, task_a, "parent-of")

        clusters = find_dependency_clusters()
        assert len(clusters) == 0

    def test_inactive_things_excluded(self):
        """Inactive Things should not appear in clusters."""
        proj = _insert_thing("Trip", type_hint="project")
        task_a = _insert_thing("Active task")
        task_b = _insert_thing("Done task", active=False)
        _insert_relationship(proj, task_a, "parent-of")
        _insert_relationship(proj, task_b, "parent-of")

        clusters = find_dependency_clusters()
        assert len(clusters) == 0  # Only 1 active child → no cluster

    def test_empty_db_returns_empty(self):
        assert find_dependency_clusters() == []


class TestDetectClusterDependencies:
    @pytest.mark.asyncio
    async def test_creates_suggestion_for_high_confidence_dependency(self):
        """LLM response with confidence >= 0.6 should create a ConnectionSuggestion."""
        proj = _insert_thing("Spain Trip", type_hint="project")
        task_a_id = _insert_thing("Book flights")
        task_b_id = _insert_thing("Approve holidays")
        _insert_relationship(proj, task_a_id, "parent-of")
        _insert_relationship(proj, task_b_id, "parent-of")

        mock_response = json.dumps({
            "dependencies": [{
                "from_id": task_a_id,
                "to_id": task_b_id,
                "relationship_type": "depends-on",
                "reason": "Flights must wait for holiday approval",
                "confidence": 0.85,
            }],
            "conflicts": [],
        })

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_response):
            result = await run_dependency_sweep()

        assert result.suggestions_created == 1
        with Session(_engine_mod.engine) as session:
            suggs = session.exec(select(ConnectionSuggestionRecord)).all()
        assert len(suggs) == 1
        assert suggs[0].suggested_relationship_type == "depends-on"

    @pytest.mark.asyncio
    async def test_skips_low_confidence_dependency(self):
        """Confidence < 0.6 should not create a suggestion."""
        proj = _insert_thing("Trip", type_hint="project")
        task_a_id = _insert_thing("Task A")
        task_b_id = _insert_thing("Task B")
        _insert_relationship(proj, task_a_id, "parent-of")
        _insert_relationship(proj, task_b_id, "parent-of")

        mock_response = json.dumps({
            "dependencies": [{
                "from_id": task_a_id,
                "to_id": task_b_id,
                "relationship_type": "depends-on",
                "reason": "Maybe related",
                "confidence": 0.3,
            }],
            "conflicts": [],
        })

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_response):
            result = await run_dependency_sweep()

        assert result.suggestions_created == 0

    @pytest.mark.asyncio
    async def test_creates_sweep_finding_for_conflict(self):
        """LLM-detected conflict should create a SweepFindingRecord."""
        proj = _insert_thing("Trip", type_hint="project")
        task_a_id = _insert_thing("Book flights", checkin_date="2026-05-01")
        task_b_id = _insert_thing("Approve holidays", checkin_date="2026-04-25")
        _insert_relationship(proj, task_a_id, "parent-of")
        _insert_relationship(proj, task_b_id, "parent-of")

        mock_response = json.dumps({
            "dependencies": [],
            "conflicts": [{
                "thing_id": task_a_id,
                "related_thing_ids": [task_b_id],
                "message": "Can't book flights before holidays are approved!",
                "severity": "warning",
                "priority": 1,
            }],
        })

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
    async def test_invalid_json_from_llm_returns_empty(self):
        """Invalid LLM JSON should not crash — return empty result."""
        proj = _insert_thing("Trip", type_hint="project")
        _insert_relationship(proj, _insert_thing("A"), "parent-of")
        _insert_relationship(proj, _insert_thing("B"), "parent-of")

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value="not json"):
            result = await run_dependency_sweep()

        assert result.suggestions_created == 0
        assert result.findings_created == 0

    @pytest.mark.asyncio
    async def test_does_not_duplicate_existing_suggestion(self):
        """If a suggestion already exists for a pair, skip creating another."""
        proj = _insert_thing("Trip", type_hint="project")
        task_a_id = _insert_thing("Task A")
        task_b_id = _insert_thing("Task B")
        _insert_relationship(proj, task_a_id, "parent-of")
        _insert_relationship(proj, task_b_id, "parent-of")

        # Pre-insert existing suggestion
        with Session(_engine_mod.engine) as session:
            session.add(ConnectionSuggestionRecord(
                id="cs-existing",
                from_thing_id=task_a_id,
                to_thing_id=task_b_id,
                suggested_relationship_type="depends-on",
                reason="existing",
                confidence=0.8,
                status="pending",
                created_at=datetime.now(timezone.utc),
            ))
            session.commit()

        mock_response = json.dumps({
            "dependencies": [{
                "from_id": task_a_id,
                "to_id": task_b_id,
                "relationship_type": "depends-on",
                "reason": "again",
                "confidence": 0.9,
            }],
            "conflicts": [],
        })

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_response):
            result = await run_dependency_sweep()

        assert result.suggestions_created == 0  # Already existed
