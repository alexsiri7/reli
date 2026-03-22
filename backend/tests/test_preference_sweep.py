"""Tests for the preference aggregation sweep phase."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.database import db
from backend.preference_sweep import (
    MIN_INTERACTIONS,
    PreferenceAggregationResult,
    _fetch_existing_preferences,
    _fetch_recent_interactions,
    _format_interactions_for_llm,
    aggregate_preference_patterns,
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
    active: bool = True,
    data: dict | None = None,
    user_id: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO things
           (id, title, type_hint, active, surface, data, created_at, updated_at, user_id)
           VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)""",
        (thing_id, title, type_hint, int(active), json.dumps(data) if data else None, now, now, user_id),
    )


def _insert_chat_message(
    conn,
    role: str,
    content: str,
    *,
    session_id: str = "test-session",
    applied_changes: dict | None = None,
    user_id: str = "",
    timestamp: str | None = None,
) -> None:
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO chat_history
           (session_id, role, content, applied_changes, user_id, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, role, content, json.dumps(applied_changes) if applied_changes else None, user_id or None, ts),
    )


# ---------------------------------------------------------------------------
# _fetch_recent_interactions
# ---------------------------------------------------------------------------


class TestFetchRecentInteractions:
    def test_fetches_messages_within_window(self, patched_db):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(days=5)).isoformat()
        old = (now - timedelta(days=60)).isoformat()

        with db() as conn:
            _insert_chat_message(conn, "user", "Recent message", timestamp=recent)
            _insert_chat_message(conn, "assistant", "Recent reply", timestamp=recent)
            _insert_chat_message(conn, "user", "Old message", timestamp=old)

        with db() as conn:
            results = _fetch_recent_interactions(conn, days=30)

        assert len(results) == 2
        assert results[0]["content"] == "Recent message"

    def test_includes_applied_changes(self, patched_db):
        changes = {"created": [{"title": "New Task"}], "updated": []}
        with db() as conn:
            _insert_chat_message(
                conn,
                "assistant",
                "Done!",
                applied_changes=changes,
            )

        with db() as conn:
            results = _fetch_recent_interactions(conn, days=30)

        assert len(results) == 1
        assert results[0]["applied_changes"]["created"][0]["title"] == "New Task"

    def test_truncates_long_content(self, patched_db):
        long_content = "x" * 1000
        with db() as conn:
            _insert_chat_message(conn, "user", long_content)

        with db() as conn:
            results = _fetch_recent_interactions(conn, days=30)

        assert len(results[0]["content"]) == 500

    def test_empty_db_returns_empty(self, patched_db):
        with db() as conn:
            results = _fetch_recent_interactions(conn, days=30)
        assert results == []


# ---------------------------------------------------------------------------
# _fetch_existing_preferences
# ---------------------------------------------------------------------------


class TestFetchExistingPreferences:
    def test_fetches_preference_things(self, patched_db):
        pref_data = {"confidence": 0.7, "category": "scheduling"}
        with db() as conn:
            _insert_thing(conn, "pref-1", "Prefers mornings", type_hint="preference", data=pref_data)
            _insert_thing(conn, "task-1", "Regular task", type_hint="task")

        with db() as conn:
            results = _fetch_existing_preferences(conn)

        assert len(results) == 1
        assert results[0]["id"] == "pref-1"
        assert results[0]["data"]["confidence"] == 0.7

    def test_excludes_inactive_preferences(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "pref-1", "Old pref", type_hint="preference", active=False)

        with db() as conn:
            results = _fetch_existing_preferences(conn)

        assert len(results) == 0


# ---------------------------------------------------------------------------
# _format_interactions_for_llm
# ---------------------------------------------------------------------------


class TestFormatInteractionsForLlm:
    def test_formats_basic_interactions(self, patched_db):
        interactions = [
            {"role": "user", "content": "Hello", "applied_changes": None, "timestamp": "2026-01-01"},
            {"role": "assistant", "content": "Hi!", "applied_changes": None, "timestamp": "2026-01-01"},
        ]
        result = _format_interactions_for_llm(interactions, [])
        assert "2 messages" in result
        assert "[user] Hello" in result
        assert "[assistant] Hi!" in result

    def test_includes_applied_changes_summary(self, patched_db):
        interactions = [
            {
                "role": "assistant",
                "content": "Created a task",
                "applied_changes": {"created": [{"title": "Buy milk"}]},
                "timestamp": "2026-01-01",
            },
        ]
        result = _format_interactions_for_llm(interactions, [])
        assert "created: Buy milk" in result

    def test_includes_existing_preferences(self, patched_db):
        interactions = [{"role": "user", "content": "Test", "applied_changes": None, "timestamp": "2026-01-01"}]
        existing = [{"id": "pref-1", "title": "Likes mornings", "data": {"confidence": 0.8, "category": "scheduling"}}]
        result = _format_interactions_for_llm(interactions, existing)
        assert "Existing preferences" in result
        assert "Likes mornings" in result
        assert "confidence=0.8" in result


# ---------------------------------------------------------------------------
# aggregate_preference_patterns (integration with mocked LLM)
# ---------------------------------------------------------------------------


class TestAggregatePreferencePatterns:
    @pytest.mark.asyncio
    async def test_skips_when_too_few_interactions(self, patched_db):
        """Should return empty result when fewer than MIN_INTERACTIONS messages."""
        with db() as conn:
            for i in range(MIN_INTERACTIONS - 1):
                _insert_chat_message(conn, "user", f"Message {i}")

        result = await aggregate_preference_patterns()
        assert result.preferences_created == 0
        assert result.preferences_updated == 0

    @pytest.mark.asyncio
    async def test_creates_new_preference_thing(self, patched_db):
        """Should create a new preference Thing when LLM detects a pattern."""
        with db() as conn:
            for i in range(MIN_INTERACTIONS + 2):
                _insert_chat_message(conn, "user", f"Schedule meeting for afternoon {i}")
                _insert_chat_message(conn, "assistant", f"Done, moved to afternoon {i}")

        llm_response = json.dumps({
            "preferences": [
                {
                    "title": "Prefers afternoon meetings",
                    "category": "scheduling",
                    "confidence": 0.65,
                    "evidence": [
                        "Rescheduled 5 meetings to afternoon",
                        "Never requests morning slots",
                    ],
                    "existing_id": None,
                }
            ]
        })

        with patch("backend.preference_sweep._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await aggregate_preference_patterns()

        assert result.preferences_created == 1
        assert result.preferences_updated == 0
        assert result.preferences[0]["title"] == "Prefers afternoon meetings"
        assert result.preferences[0]["action"] == "created"

        # Verify the Thing was created in the database
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM things WHERE type_hint = 'preference'"
            ).fetchone()
        assert row is not None
        assert row["title"] == "Prefers afternoon meetings"
        assert row["surface"] == 0  # preferences are hidden from default views
        data = json.loads(row["data"])
        assert data["confidence"] == 0.65
        assert data["category"] == "scheduling"
        assert len(data["evidence"]) == 2

    @pytest.mark.asyncio
    async def test_updates_existing_preference(self, patched_db):
        """Should update confidence and evidence when LLM confirms existing pattern."""
        pref_data = {
            "confidence": 0.5,
            "category": "scheduling",
            "evidence": ["Old evidence 1"],
            "sweep_count": 2,
        }
        with db() as conn:
            _insert_thing(conn, "pref-exist", "Prefers afternoons", type_hint="preference", data=pref_data)
            for i in range(MIN_INTERACTIONS + 2):
                _insert_chat_message(conn, "user", f"Move meeting to pm {i}")
                _insert_chat_message(conn, "assistant", f"Moved {i}")

        llm_response = json.dumps({
            "preferences": [
                {
                    "title": "Prefers afternoons",
                    "category": "scheduling",
                    "confidence": 0.55,
                    "evidence": ["New evidence: rescheduled again"],
                    "existing_id": "pref-exist",
                }
            ]
        })

        with patch("backend.preference_sweep._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await aggregate_preference_patterns()

        assert result.preferences_created == 0
        assert result.preferences_updated == 1
        assert result.preferences[0]["action"] == "updated"
        assert result.preferences[0]["old_confidence"] == 0.5
        assert result.preferences[0]["new_confidence"] == 0.55

        # Verify the Thing was updated
        with db() as conn:
            row = conn.execute("SELECT data FROM things WHERE id = 'pref-exist'").fetchone()
        data = json.loads(row["data"])
        assert data["confidence"] == 0.55
        assert data["sweep_count"] == 3
        assert "New evidence: rescheduled again" in data["evidence"]
        assert "Old evidence 1" in data["evidence"]

    @pytest.mark.asyncio
    async def test_handles_invalid_llm_response(self, patched_db):
        """Should gracefully handle invalid JSON from the LLM."""
        with db() as conn:
            for i in range(MIN_INTERACTIONS + 2):
                _insert_chat_message(conn, "user", f"Message {i}")

        with patch("backend.preference_sweep._chat", new_callable=AsyncMock, return_value="not json"):
            result = await aggregate_preference_patterns()

        assert result.preferences_created == 0
        assert result.preferences_updated == 0

    @pytest.mark.asyncio
    async def test_handles_empty_preferences_list(self, patched_db):
        """Should handle LLM returning empty preferences list."""
        with db() as conn:
            for i in range(MIN_INTERACTIONS + 2):
                _insert_chat_message(conn, "user", f"Message {i}")

        llm_response = json.dumps({"preferences": []})

        with patch("backend.preference_sweep._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await aggregate_preference_patterns()

        assert result.preferences_created == 0
        assert result.preferences_updated == 0

    @pytest.mark.asyncio
    async def test_clamps_confidence_to_valid_range(self, patched_db):
        """Confidence should be clamped to 0.0-1.0."""
        with db() as conn:
            for i in range(MIN_INTERACTIONS + 2):
                _insert_chat_message(conn, "user", f"Message {i}")

        llm_response = json.dumps({
            "preferences": [
                {
                    "title": "Over-confident pref",
                    "category": "other",
                    "confidence": 1.5,
                    "evidence": ["ev1", "ev2"],
                }
            ]
        })

        with patch("backend.preference_sweep._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await aggregate_preference_patterns()

        assert result.preferences_created == 1
        with db() as conn:
            row = conn.execute("SELECT data FROM things WHERE type_hint = 'preference'").fetchone()
        data = json.loads(row["data"])
        assert data["confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_ignores_unknown_existing_id(self, patched_db):
        """If existing_id doesn't match any preference, create a new one instead."""
        with db() as conn:
            for i in range(MIN_INTERACTIONS + 2):
                _insert_chat_message(conn, "user", f"Message {i}")

        llm_response = json.dumps({
            "preferences": [
                {
                    "title": "New pref",
                    "category": "social",
                    "confidence": 0.4,
                    "evidence": ["ev1", "ev2"],
                    "existing_id": "nonexistent-id",
                }
            ]
        })

        with patch("backend.preference_sweep._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await aggregate_preference_patterns()

        assert result.preferences_created == 1
        assert result.preferences_updated == 0

    @pytest.mark.asyncio
    async def test_evidence_capped_at_ten(self, patched_db):
        """Merged evidence should be capped at 10 entries."""
        old_evidence = [f"old-{i}" for i in range(9)]
        pref_data = {
            "confidence": 0.5,
            "category": "productivity",
            "evidence": old_evidence,
            "sweep_count": 1,
        }
        with db() as conn:
            _insert_thing(conn, "pref-cap", "Test cap", type_hint="preference", data=pref_data)
            for i in range(MIN_INTERACTIONS + 2):
                _insert_chat_message(conn, "user", f"Msg {i}")

        llm_response = json.dumps({
            "preferences": [
                {
                    "title": "Test cap",
                    "category": "productivity",
                    "confidence": 0.6,
                    "evidence": ["new-1", "new-2", "new-3"],
                    "existing_id": "pref-cap",
                }
            ]
        })

        with patch("backend.preference_sweep._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await aggregate_preference_patterns()

        with db() as conn:
            row = conn.execute("SELECT data FROM things WHERE id = 'pref-cap'").fetchone()
        data = json.loads(row["data"])
        assert len(data["evidence"]) == 10  # capped
