"""Tests for connection_sweep LLM response parsing safety."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.connection_sweep import ConnectionCandidate, validate_candidates
from backend.tools import create_thing


def _make_candidates(patched_db) -> list[ConnectionCandidate]:
    """Create two Things and return a candidate pair."""
    a = create_thing(title="Build API")
    b = create_thing(title="Deploy Service")
    return [
        ConnectionCandidate(
            from_thing_id=a["id"],
            from_thing_title="Build API",
            from_type_hint="task",
            to_thing_id=b["id"],
            to_thing_title="Deploy Service",
            to_type_hint="task",
            distance=0.2,
        )
    ]


class TestValidateCandidatesParsing:
    @pytest.mark.asyncio
    async def test_malformed_json_returns_empty_suggestions(self, patched_db):
        """When LLM returns invalid JSON, validate_candidates returns [] with no exception."""
        candidates = _make_candidates(patched_db)

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value="not valid json {{"):
            result = await validate_candidates(candidates)

        assert result.suggestions_created == 0
        assert result.suggestions == []
        assert result.candidates_found == len(candidates)

    @pytest.mark.asyncio
    async def test_low_confidence_finding_filtered_out(self, patched_db):
        """A finding at confidence 0.59 is filtered by the 0.6 threshold gate."""
        candidates = _make_candidates(patched_db)
        llm_response = json.dumps(
            {
                "connections": [
                    {
                        "from_id": candidates[0].from_thing_id,
                        "to_id": candidates[0].to_thing_id,
                        "relationship_type": "depends-on",
                        "reason": "API needed before deploy",
                        "confidence": 0.59,
                    }
                ]
            }
        )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await validate_candidates(candidates)

        assert result.suggestions_created == 0

    @pytest.mark.asyncio
    async def test_high_confidence_finding_accepted(self, patched_db):
        """A finding at confidence 0.8 passes the threshold gate."""
        candidates = _make_candidates(patched_db)
        llm_response = json.dumps(
            {
                "connections": [
                    {
                        "from_id": candidates[0].from_thing_id,
                        "to_id": candidates[0].to_thing_id,
                        "relationship_type": "depends-on",
                        "reason": "API must be built before deploying",
                        "confidence": 0.8,
                    }
                ]
            }
        )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await validate_candidates(candidates)

        assert result.suggestions_created == 1
        assert result.suggestions[0]["confidence"] == 0.8

    @pytest.mark.asyncio
    async def test_empty_connections_key_returns_zero(self, patched_db):
        """When LLM returns valid JSON but empty connections list, result is 0 suggestions."""
        candidates = _make_candidates(patched_db)
        llm_response = json.dumps({"connections": []})

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await validate_candidates(candidates)

        assert result.suggestions_created == 0
