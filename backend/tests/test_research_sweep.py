"""Tests for the proactive research sweep."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, select

import backend.db_engine as _engine_mod
from backend.database import db
from backend.db_models import SweepFindingRecord, ThingRecord
from backend.research_sweep import (
    _get_open_questions,
    _should_skip,
    run_research_sweep,
)


@pytest.fixture(autouse=True)
def _fresh_db(patched_db):
    """Use the shared patched_db fixture from conftest."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_thing(
    importance: int = 1,
    research_ts: str | None = None,
    updated_at: datetime | None = None,
) -> ThingRecord:
    """Build an in-memory ThingRecord for unit testing pure helpers."""
    now = datetime.now(timezone.utc)
    data: dict = {}
    if research_ts:
        data["research"] = {"timestamp": research_ts}
    return ThingRecord(
        id="t1",
        title="Test Thing",
        importance=importance,
        active=True,
        data=data if data else None,
        updated_at=updated_at or now,
    )


def _insert_thing_with_questions(
    title: str,
    importance: int = 1,
    questions: list[str] | None = None,
    data: dict | None = None,
) -> str:
    """Insert a Thing with open_questions into the test DB."""
    thing_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            """INSERT INTO things
               (id, title, type_hint, importance, active, surface, data, open_questions, created_at, updated_at)
               VALUES (?, ?, 'task', ?, 1, 1, ?, ?, datetime('now'), datetime('now'))""",
            (
                thing_id,
                title,
                importance,
                json.dumps(data) if data else None,
                json.dumps(questions) if questions else None,
            ),
        )
    return thing_id


# ---------------------------------------------------------------------------
# TestShouldSkip — unit tests for the cooldown gate
# ---------------------------------------------------------------------------


class TestShouldSkip:
    def test_skips_low_importance(self):
        """Things with importance > 2 (low/backlog) are skipped."""
        assert _should_skip(_make_thing(importance=3)) is True
        assert _should_skip(_make_thing(importance=4)) is True

    def test_does_not_skip_medium_importance(self):
        """Importance 2 (medium) is within threshold."""
        assert _should_skip(_make_thing(importance=2)) is False

    def test_does_not_skip_high_importance(self):
        """Importance 0 (critical) and 1 (high) are within threshold."""
        assert _should_skip(_make_thing(importance=0)) is False
        assert _should_skip(_make_thing(importance=1)) is False

    def test_skips_recently_researched_unchanged_thing(self):
        """Thing researched 3 days ago, not updated since — skip."""
        now = datetime.now(timezone.utc)
        recent_ts = (now - timedelta(days=3)).isoformat()
        old_update = now - timedelta(days=5)
        thing = _make_thing(research_ts=recent_ts, updated_at=old_update)
        assert _should_skip(thing) is True

    def test_does_not_skip_recently_researched_but_updated(self):
        """Thing researched 3 days ago but updated 1 day ago — do NOT skip."""
        now = datetime.now(timezone.utc)
        research_ts = (now - timedelta(days=3)).isoformat()
        recent_update = now - timedelta(days=1)
        thing = _make_thing(research_ts=research_ts, updated_at=recent_update)
        assert _should_skip(thing) is False

    def test_does_not_skip_when_cooldown_expired(self):
        """Thing researched 10 days ago — cooldown expired, do not skip."""
        now = datetime.now(timezone.utc)
        old_ts = (now - timedelta(days=10)).isoformat()
        thing = _make_thing(research_ts=old_ts, updated_at=now - timedelta(days=12))
        assert _should_skip(thing) is False

    def test_handles_naive_updated_at(self):
        """updated_at without tzinfo should not raise — treated as UTC."""
        now = datetime.now(timezone.utc)
        research_ts = (now - timedelta(days=3)).isoformat()
        naive_update = datetime.utcnow() - timedelta(days=5)  # no tzinfo
        thing = _make_thing(research_ts=research_ts, updated_at=naive_update)
        # Should not raise, and should be skipped (unchanged since research)
        assert _should_skip(thing) is True

    def test_handles_malformed_timestamp(self):
        """Malformed research timestamp — treat as not researched, do not skip."""
        thing = _make_thing(research_ts="not-a-date")
        assert _should_skip(thing) is False

    def test_no_data_does_not_skip(self):
        """Thing with no prior research data is not skipped."""
        thing = _make_thing(importance=1, research_ts=None)
        assert _should_skip(thing) is False


# ---------------------------------------------------------------------------
# TestGetOpenQuestions — unit tests for format handling
# ---------------------------------------------------------------------------


class TestGetOpenQuestions:
    def test_returns_empty_for_none(self):
        """None open_questions returns empty list."""
        thing = ThingRecord(id="t1", title="x", open_questions=None)
        assert _get_open_questions(thing) == []

    def test_returns_list_unchanged(self):
        """List type returned as-is."""
        thing = ThingRecord(id="t1", title="x", open_questions=["q1", "q2"])
        assert _get_open_questions(thing) == ["q1", "q2"]

    def test_parses_json_string(self):
        """JSON-encoded string is parsed and returned."""
        thing = ThingRecord(id="t1", title="x", open_questions='["q1", "q2"]')
        assert _get_open_questions(thing) == ["q1", "q2"]

    def test_returns_empty_for_json_object(self):
        """JSON dict (not list) returns empty — no crash."""
        thing = ThingRecord(id="t1", title="x", open_questions='{"key": "val"}')
        assert _get_open_questions(thing) == []

    def test_returns_empty_for_invalid_json_string(self):
        """Invalid JSON string returns empty list."""
        thing = ThingRecord(id="t1", title="x", open_questions="not json")
        assert _get_open_questions(thing) == []

    def test_returns_empty_for_non_string_non_list(self):
        """Unexpected type returns empty list."""
        thing = ThingRecord(id="t1", title="x", open_questions=42)  # type: ignore[arg-type]
        assert _get_open_questions(thing) == []


# ---------------------------------------------------------------------------
# TestRunResearchSweep — integration tests for the main orchestrator
# ---------------------------------------------------------------------------


class TestRunResearchSweep:
    @pytest.mark.asyncio
    async def test_creates_finding_and_stores_research_data(self):
        """Successful web search creates SweepFinding and updates Thing.data."""
        tid = _insert_thing_with_questions(
            "Spain Trip",
            questions=["What is the visa requirement for Spain?"],
        )

        mock_llm = json.dumps({
            "action": "web_search",
            "query": "Spain visa requirements 2026",
            "reason": "Factual lookup for visa info",
        })
        mock_result_obj = type("R", (), {
            "to_dict": lambda self: {
                "title": "Spain Visa Guide",
                "url": "http://example.com",
                "snippet": "No visa needed for EU citizens.",
            }
        })()

        with (
            patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_llm),
            patch(
                "backend.research_sweep.google_search",
                new_callable=AsyncMock,
                return_value=[mock_result_obj],
            ),
        ):
            result = await run_research_sweep()

        assert result.things_researched == 1
        assert result.findings_created == 1
        assert result.lookups_executed == 1

        with Session(_engine_mod.engine) as session:
            thing = session.get(ThingRecord, tid)
            assert thing is not None
            assert isinstance(thing.data, dict)
            assert "research" in thing.data
            assert thing.data["research"]["source"] == "web_search"
            assert thing.data["research"]["query"] == "Spain visa requirements 2026"

            findings = session.exec(
                select(SweepFindingRecord).where(
                    SweepFindingRecord.finding_type == "research"
                )
            ).all()
            assert len(findings) == 1
            assert "Spain Trip" in findings[0].message

    @pytest.mark.asyncio
    async def test_preserves_existing_thing_data_on_merge(self):
        """research_sweep must not overwrite other keys in Thing.data."""
        existing_data = {"custom_key": "important_value", "notes": [1, 2, 3]}
        tid = _insert_thing_with_questions(
            "Trip",
            questions=["Best hotel?"],
            data=existing_data,
        )

        mock_llm = json.dumps({"action": "web_search", "query": "best hotels", "reason": "x"})
        mock_result_obj = type("R", (), {
            "to_dict": lambda self: {"title": "Hotels", "url": "u", "snippet": "s"}
        })()

        with (
            patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_llm),
            patch(
                "backend.research_sweep.google_search",
                new_callable=AsyncMock,
                return_value=[mock_result_obj],
            ),
        ):
            await run_research_sweep()

        with Session(_engine_mod.engine) as session:
            thing = session.get(ThingRecord, tid)
            assert thing is not None
            assert thing.data["custom_key"] == "important_value"
            assert thing.data["notes"] == [1, 2, 3]
            assert "research" in thing.data

    @pytest.mark.asyncio
    async def test_does_not_mutate_updated_at(self):
        """research_sweep must NOT update Thing.updated_at (would break cooldown)."""
        tid = _insert_thing_with_questions(
            "Test Thing",
            questions=["A question?"],
        )

        # Record the original updated_at
        with Session(_engine_mod.engine) as session:
            thing_before = session.get(ThingRecord, tid)
            original_updated_at = thing_before.updated_at  # type: ignore[union-attr]

        mock_llm = json.dumps({"action": "web_search", "query": "query", "reason": "r"})
        mock_result_obj = type("R", (), {
            "to_dict": lambda self: {"title": "T", "url": "u", "snippet": "s"}
        })()

        with (
            patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_llm),
            patch(
                "backend.research_sweep.google_search",
                new_callable=AsyncMock,
                return_value=[mock_result_obj],
            ),
        ):
            await run_research_sweep()

        with Session(_engine_mod.engine) as session:
            thing_after = session.get(ThingRecord, tid)
            assert thing_after is not None
            # updated_at must NOT have changed
            assert thing_after.updated_at == original_updated_at

    @pytest.mark.asyncio
    async def test_action_none_does_not_execute_lookup(self):
        """LLM deciding action=none should not increment lookups_executed."""
        _insert_thing_with_questions("Vague idea", questions=["What should I do?"])

        mock_llm = json.dumps({"action": "none", "query": None, "reason": "needs user decision"})

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_llm):
            result = await run_research_sweep()

        assert result.lookups_executed == 0
        assert result.findings_created == 0

    @pytest.mark.asyncio
    async def test_respects_max_lookups_cap(self):
        """Only MAX_LOOKUPS_PER_RUN (10) Things are processed even if more are eligible."""
        for i in range(15):
            _insert_thing_with_questions(f"Thing {i}", questions=["question?"])

        mock_llm = json.dumps({"action": "web_search", "query": "query", "reason": "r"})
        mock_result_obj = type("R", (), {
            "to_dict": lambda self: {"title": "T", "url": "u", "snippet": "s"}
        })()

        with (
            patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_llm),
            patch(
                "backend.research_sweep.google_search",
                new_callable=AsyncMock,
                return_value=[mock_result_obj],
            ),
        ):
            result = await run_research_sweep()

        assert result.lookups_executed <= 10

    @pytest.mark.asyncio
    async def test_skips_low_importance_things(self):
        """Things with importance > 2 (low/backlog) should not be researched."""
        _insert_thing_with_questions("Low priority", importance=3, questions=["question?"])

        with patch("backend.agents._chat", new_callable=AsyncMock) as mock_llm:
            result = await run_research_sweep()

        mock_llm.assert_not_called()
        assert result.things_researched == 0

    @pytest.mark.asyncio
    async def test_invalid_llm_json_continues_to_next_thing(self):
        """Invalid LLM JSON for one Thing should not crash sweep."""
        _insert_thing_with_questions("Trip", questions=["question?"])

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value="not json"):
            result = await run_research_sweep()

        # Should not raise, and no findings created (action falls back to "none")
        assert result.findings_created == 0

    @pytest.mark.asyncio
    async def test_empty_lookup_results_creates_no_finding(self):
        """If lookup returns no results, no finding is created."""
        _insert_thing_with_questions("Trip", questions=["question?"])

        mock_llm = json.dumps({"action": "web_search", "query": "query", "reason": "r"})

        with (
            patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_llm),
            patch(
                "backend.research_sweep.google_search",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await run_research_sweep()

        assert result.findings_created == 0
        assert result.lookups_executed == 1  # lookup was attempted


# ---------------------------------------------------------------------------
# TestResearchEndpointResponseShape — API contract test
# ---------------------------------------------------------------------------


class TestResearchEndpointResponseShape:
    @pytest.mark.asyncio
    async def test_research_endpoint_response_shape(self, async_client):
        """POST /sweep/research returns expected keys with correct types."""
        with patch(
            "backend.agents._chat",
            new_callable=AsyncMock,
            return_value='{"action": "none", "query": null, "reason": "no data needed"}',
        ):
            response = await async_client.post("/api/sweep/research")

        assert response.status_code == 200
        data = response.json()
        assert "things_researched" in data
        assert isinstance(data["things_researched"], int)
        assert "findings_created" in data
        assert isinstance(data["findings_created"], int)
        assert "lookups_executed" in data
        assert isinstance(data["lookups_executed"], int)
        assert "findings" in data
        assert isinstance(data["findings"], list)
        assert "usage" in data
        assert isinstance(data["usage"], dict)

    @pytest.mark.asyncio
    async def test_sweep_run_includes_research_fields(self, async_client):
        """/sweep/run response includes research_lookups and research_findings keys."""
        mock_llm_response = json.dumps({
            "action": "none",
            "query": None,
            "reason": "no data needed",
        })

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=mock_llm_response):
            response = await async_client.post("/api/sweep/run")

        assert response.status_code == 200
        data = response.json()
        assert "research_lookups" in data
        assert isinstance(data["research_lookups"], int)
        assert "research_findings" in data
        assert isinstance(data["research_findings"], int)
