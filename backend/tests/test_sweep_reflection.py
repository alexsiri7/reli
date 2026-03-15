"""Tests for the nightly sweep Phase 2: LLM reflection."""

import json
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from backend.database import db
from backend.sweep import (
    SweepCandidate,
    _format_candidates_for_llm,
    reflect_on_candidates,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_thing(conn, thing_id: str, title: str, **kwargs) -> None:
    now = kwargs.pop("updated_at", date.today().isoformat())
    conn.execute(
        """INSERT INTO things
           (id, title, type_hint, parent_id, checkin_date, active, surface,
            data, open_questions, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
        (
            thing_id,
            title,
            kwargs.get("type_hint"),
            kwargs.get("parent_id"),
            kwargs.get("checkin_date"),
            int(kwargs.get("active", True)),
            json.dumps(kwargs.get("data")) if kwargs.get("data") else None,
            json.dumps(kwargs.get("open_questions")) if kwargs.get("open_questions") else None,
            now,
            now,
        ),
    )


def _make_candidate(
    thing_id: str = "t1",
    title: str = "Test Thing",
    finding_type: str = "stale",
    message: str = "Untouched for 20d: Test Thing",
    priority: int = 3,
    extra: dict | None = None,
) -> SweepCandidate:
    return SweepCandidate(
        thing_id=thing_id,
        thing_title=title,
        finding_type=finding_type,
        message=message,
        priority=priority,
        extra=extra or {},
    )


# ---------------------------------------------------------------------------
# _format_candidates_for_llm
# ---------------------------------------------------------------------------


class TestFormatCandidates:
    def test_empty_candidates(self):
        result = _format_candidates_for_llm([])
        assert "No candidates" in result

    def test_formats_single_candidate(self):
        candidates = [_make_candidate()]
        result = _format_candidates_for_llm(candidates)
        assert "1 candidates:" in result
        assert "[stale]" in result
        assert "Untouched for 20d" in result
        assert "id=t1" in result

    def test_includes_extra_fields(self):
        candidates = [_make_candidate(extra={"days_stale": 20, "type_hint": "task"})]
        result = _format_candidates_for_llm(candidates)
        assert "days_stale=20" in result
        assert "type_hint=task" in result

    def test_multiple_candidates_numbered(self):
        candidates = [
            _make_candidate(thing_id="a", title="Alpha"),
            _make_candidate(thing_id="b", title="Beta"),
        ]
        result = _format_candidates_for_llm(candidates)
        assert "1." in result
        assert "2." in result
        assert "2 candidates:" in result


# ---------------------------------------------------------------------------
# reflect_on_candidates
# ---------------------------------------------------------------------------


class TestReflectOnCandidates:
    @pytest.mark.asyncio
    async def test_creates_findings_from_llm_response(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "Budget Report")

        candidates = [_make_candidate(thing_id="t1", title="Budget Report")]
        llm_response = json.dumps(
            {
                "findings": [
                    {
                        "thing_id": "t1",
                        "finding_type": "llm_insight",
                        "message": "Budget report has been neglected — review before month end.",
                        "priority": 1,
                        "expires_in_days": 7,
                    },
                    {
                        "thing_id": None,
                        "finding_type": "llm_insight",
                        "message": "You have several stale items — consider a weekly review habit.",
                        "priority": 3,
                        "expires_in_days": 14,
                    },
                ]
            }
        )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await reflect_on_candidates(candidates)

        assert result.findings_created == 2
        assert len(result.findings) == 2
        assert result.findings[0]["thing_id"] == "t1"
        assert result.findings[0]["priority"] == 1
        assert result.findings[0]["finding_type"] == "llm_insight"
        assert result.findings[1]["thing_id"] is None
        assert result.findings[1]["expires_at"] is not None

        # Verify persisted to database
        with db() as conn:
            rows = conn.execute("SELECT * FROM sweep_findings ORDER BY priority").fetchall()
        assert len(rows) == 2
        assert rows[0]["finding_type"] == "llm_insight"
        assert rows[0]["thing_id"] == "t1"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty(self, patched_db):
        candidates = [_make_candidate()]
        with patch("backend.agents._chat", new_callable=AsyncMock, return_value="not json at all"):
            result = await reflect_on_candidates(candidates)

        assert result.findings_created == 0
        assert result.findings == []

    @pytest.mark.asyncio
    async def test_empty_candidates_still_calls_llm(self, patched_db):
        llm_response = json.dumps({"findings": []})
        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response) as mock_chat:
            result = await reflect_on_candidates([])

        mock_chat.assert_called_once()
        assert result.findings_created == 0

    @pytest.mark.asyncio
    async def test_invalid_thing_id_set_to_null(self, patched_db):
        candidates = [_make_candidate(thing_id="t1")]
        llm_response = json.dumps(
            {
                "findings": [
                    {
                        "thing_id": "nonexistent-uuid",
                        "finding_type": "llm_insight",
                        "message": "Something about a thing that doesn't exist",
                        "priority": 2,
                        "expires_in_days": 7,
                    }
                ]
            }
        )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await reflect_on_candidates(candidates)

        assert result.findings_created == 1
        assert result.findings[0]["thing_id"] is None  # invalid ID was nulled

    @pytest.mark.asyncio
    async def test_priority_clamped(self, patched_db):
        candidates = [_make_candidate()]
        llm_response = json.dumps(
            {
                "findings": [
                    {
                        "thing_id": None,
                        "finding_type": "llm_insight",
                        "message": "Bad priority test",
                        "priority": 99,
                        "expires_in_days": 7,
                    }
                ]
            }
        )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await reflect_on_candidates(candidates)

        assert result.findings[0]["priority"] == 2  # clamped to default

    @pytest.mark.asyncio
    async def test_expires_in_days_out_of_range_ignored(self, patched_db):
        candidates = [_make_candidate()]
        llm_response = json.dumps(
            {
                "findings": [
                    {
                        "thing_id": None,
                        "finding_type": "llm_insight",
                        "message": "No expiry test",
                        "priority": 2,
                        "expires_in_days": 999,
                    }
                ]
            }
        )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await reflect_on_candidates(candidates)

        assert result.findings[0]["expires_at"] is None  # out of range, no expiry

    @pytest.mark.asyncio
    async def test_empty_message_skipped(self, patched_db):
        candidates = [_make_candidate()]
        llm_response = json.dumps(
            {
                "findings": [
                    {
                        "thing_id": None,
                        "finding_type": "llm_insight",
                        "message": "",
                        "priority": 2,
                    },
                    {
                        "thing_id": None,
                        "finding_type": "llm_insight",
                        "message": "Valid finding",
                        "priority": 2,
                    },
                ]
            }
        )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await reflect_on_candidates(candidates)

        assert result.findings_created == 1
        assert result.findings[0]["message"] == "Valid finding"

    @pytest.mark.asyncio
    async def test_collects_candidates_when_none_passed(self, patched_db):
        """When candidates=None, reflect_on_candidates calls collect_candidates()."""
        llm_response = json.dumps({"findings": []})
        with (
            patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response),
            patch("backend.sweep.collect_candidates", return_value=[]) as mock_collect,
        ):
            await reflect_on_candidates(None)

        mock_collect.assert_called_once()

    @pytest.mark.asyncio
    async def test_usage_stats_returned(self, patched_db):
        candidates = [_make_candidate()]
        llm_response = json.dumps({"findings": []})
        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await reflect_on_candidates(candidates)

        assert "api_calls" in result.usage


# ---------------------------------------------------------------------------
# Sweep router endpoint
# ---------------------------------------------------------------------------


class TestSweepRouter:
    @pytest.mark.asyncio
    async def test_run_sweep_endpoint(self, async_client, patched_db):
        llm_response = json.dumps(
            {
                "findings": [
                    {
                        "thing_id": None,
                        "finding_type": "llm_insight",
                        "message": "All clear today!",
                        "priority": 3,
                        "expires_in_days": 1,
                    }
                ]
            }
        )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            resp = await async_client.post("/api/sweep/run")

        assert resp.status_code == 200
        data = resp.json()
        assert "candidates_found" in data
        assert "findings_created" in data
        assert data["findings_created"] == 1
        assert "usage" in data
