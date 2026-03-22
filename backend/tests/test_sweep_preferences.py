"""Tests for sweep preference aggregation (Phase 3)."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.database import db
from backend.sweep import (
    _confidence_for_observations,
    _find_matching_preference,
    _load_existing_preferences,
    _load_recent_interactions,
    aggregate_preferences,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_thing(
    conn,
    thing_id: str,
    title: str,
    *,
    type_hint: str | None = None,
    data: dict | None = None,
    user_id: str = "u1",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO things
           (id, title, type_hint, active, surface, priority, data,
            created_at, updated_at, user_id)
           VALUES (?, ?, ?, 1, 0, 3, ?, ?, ?, ?)""",
        (
            thing_id,
            title,
            type_hint,
            json.dumps(data) if data else None,
            now,
            now,
            user_id,
        ),
    )


def _insert_chat_message(
    conn,
    role: str,
    content: str,
    *,
    session_id: str = "sess-1",
    user_id: str = "u1",
    timestamp: str | None = None,
) -> None:
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO chat_history
           (session_id, role, content, timestamp, user_id)
           VALUES (?, ?, ?, ?, ?)""",
        (session_id, role, content, ts, user_id),
    )


# ---------------------------------------------------------------------------
# Unit tests: confidence mapping
# ---------------------------------------------------------------------------


class TestConfidenceMapping:
    def test_emerging(self):
        assert _confidence_for_observations(1) == "emerging"
        assert _confidence_for_observations(2) == "emerging"

    def test_established(self):
        assert _confidence_for_observations(3) == "established"
        assert _confidence_for_observations(4) == "established"

    def test_strong(self):
        assert _confidence_for_observations(5) == "strong"
        assert _confidence_for_observations(10) == "strong"


# ---------------------------------------------------------------------------
# Unit tests: pattern matching
# ---------------------------------------------------------------------------


class TestFindMatchingPreference:
    def test_no_match(self):
        existing = [{"pattern": "Likes pizza", "thing_id": "t1", "confidence": "emerging", "observations": 2}]
        assert _find_matching_preference("Prefers morning workouts", existing) is None

    def test_match_by_word_overlap(self):
        existing = [
            {"pattern": "Avoids morning meetings", "thing_id": "t1", "confidence": "emerging", "observations": 2}
        ]
        result = _find_matching_preference("Prefers avoiding morning meetings", existing)
        assert result is not None
        assert result["thing_id"] == "t1"

    def test_empty_existing(self):
        assert _find_matching_preference("Some pattern", []) is None

    def test_empty_pattern(self):
        existing = [{"pattern": "Test", "thing_id": "t1", "confidence": "emerging", "observations": 1}]
        assert _find_matching_preference("", existing) is None


# ---------------------------------------------------------------------------
# Integration tests: load recent interactions
# ---------------------------------------------------------------------------


class TestLoadRecentInteractions:
    def test_loads_messages_within_window(self, patched_db):
        recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        with db() as conn:
            _insert_chat_message(conn, "user", "Hello recent", timestamp=recent)
            _insert_chat_message(conn, "assistant", "Hi there", timestamp=recent)
            _insert_chat_message(conn, "user", "Very old message", timestamp=old)

        with db() as conn:
            result = _load_recent_interactions(conn, "u1", days=7)
        assert len(result) == 2
        assert result[0]["content"] == "Hello recent"

    def test_empty_when_no_messages(self, patched_db):
        with db() as conn:
            result = _load_recent_interactions(conn, "u1", days=7)
        assert result == []


# ---------------------------------------------------------------------------
# Integration tests: load existing preferences
# ---------------------------------------------------------------------------


class TestLoadExistingPreferences:
    def test_loads_preference_things(self, patched_db):
        with db() as conn:
            _insert_thing(
                conn,
                "pref-1",
                "Avoids mornings",
                type_hint="preference",
                data={"patterns": [{"pattern": "Avoids mornings", "confidence": "emerging", "observations": 2}]},
            )
        with db() as conn:
            result = _load_existing_preferences(conn, "u1")
        assert len(result) == 1
        assert result[0]["pattern"] == "Avoids mornings"
        assert result[0]["thing_id"] == "pref-1"

    def test_ignores_non_preference_things(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "task-1", "Some task", type_hint="task")
        with db() as conn:
            result = _load_existing_preferences(conn, "u1")
        assert result == []


# ---------------------------------------------------------------------------
# Integration tests: aggregate_preferences
# ---------------------------------------------------------------------------


class TestAggregatePreferences:
    @pytest.mark.asyncio
    async def test_skips_without_user_id(self, patched_db):
        result = await aggregate_preferences(user_id="")
        assert result.patterns_created == 0
        assert result.patterns_updated == 0

    @pytest.mark.asyncio
    async def test_skips_with_few_messages(self, patched_db):
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with db() as conn:
            _insert_chat_message(conn, "user", "Hello", timestamp=recent)
        result = await aggregate_preferences(user_id="u1")
        assert result.patterns_created == 0

    @pytest.mark.asyncio
    async def test_creates_new_preference(self, patched_db):
        """When LLM detects a new pattern, a preference Thing is created."""
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with db() as conn:
            for i in range(5):
                _insert_chat_message(conn, "user", f"Message {i}", timestamp=recent)

        llm_response = json.dumps(
            {
                "patterns": [
                    {
                        "pattern": "Prefers afternoon meetings",
                        "evidence": "Rescheduled morning meetings twice",
                        "observations": 3,
                    }
                ]
            }
        )

        with patch("backend.sweep._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await aggregate_preferences(user_id="u1")

        assert result.patterns_created == 1
        assert result.patterns_updated == 0
        assert result.patterns[0]["pattern"] == "Prefers afternoon meetings"
        assert result.patterns[0]["action"] == "created"

        # Verify Thing was created in DB
        with db() as conn:
            row = conn.execute(
                "SELECT data, type_hint FROM things WHERE id = ?",
                (result.patterns[0]["thing_id"],),
            ).fetchone()
        assert row is not None
        assert row["type_hint"] == "preference"
        data = json.loads(row["data"])
        assert data["patterns"][0]["confidence"] == "established"

    @pytest.mark.asyncio
    async def test_updates_existing_preference(self, patched_db):
        """When LLM detects a pattern matching an existing one, observations are bumped."""
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with db() as conn:
            _insert_thing(
                conn,
                "pref-exist",
                "Avoids mornings",
                type_hint="preference",
                data={
                    "patterns": [{"pattern": "Avoids morning meetings", "confidence": "emerging", "observations": 2}]
                },
            )
            for i in range(5):
                _insert_chat_message(conn, "user", f"Msg {i}", timestamp=recent)

        llm_response = json.dumps(
            {
                "patterns": [
                    {
                        "pattern": "Avoids morning meetings and appointments",
                        "evidence": "Rescheduled morning events again",
                        "observations": 2,
                    }
                ]
            }
        )

        with patch("backend.sweep._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await aggregate_preferences(user_id="u1")

        assert result.patterns_created == 0
        assert result.patterns_updated == 1
        assert result.patterns[0]["action"] == "updated"
        assert result.patterns[0]["observations"] == 4  # 2 existing + 2 new

        # Verify DB was updated
        with db() as conn:
            row = conn.execute("SELECT data FROM things WHERE id = 'pref-exist'").fetchone()
        data = json.loads(row["data"])
        assert data["patterns"][0]["observations"] == 4
        assert data["patterns"][0]["confidence"] == "established"

    @pytest.mark.asyncio
    async def test_handles_invalid_llm_response(self, patched_db):
        """Gracefully handles invalid JSON from LLM."""
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with db() as conn:
            for i in range(5):
                _insert_chat_message(conn, "user", f"Msg {i}", timestamp=recent)

        with patch("backend.sweep._chat", new_callable=AsyncMock, return_value="not json"):
            result = await aggregate_preferences(user_id="u1")

        assert result.patterns_created == 0
        assert result.patterns_updated == 0

    @pytest.mark.asyncio
    async def test_handles_empty_patterns(self, patched_db):
        """LLM returns empty patterns list when no patterns detected."""
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with db() as conn:
            for i in range(5):
                _insert_chat_message(conn, "user", f"Msg {i}", timestamp=recent)

        llm_response = json.dumps({"patterns": []})

        with patch("backend.sweep._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await aggregate_preferences(user_id="u1")

        assert result.patterns_created == 0
        assert result.patterns_updated == 0
