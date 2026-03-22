"""Tests for personality pattern aggregation in the sweep system."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.sweep import (
    _fetch_recent_interactions,
    _format_interactions_for_llm,
    _merge_patterns,
    aggregate_personality_patterns,
)

# ---------------------------------------------------------------------------
# _merge_patterns
# ---------------------------------------------------------------------------


class TestMergePatterns:
    def test_empty_existing_adds_all_new(self):
        new = [
            {"pattern": "Be concise", "confidence": "emerging", "observations": 2},
            {"pattern": "Use bullets", "confidence": "emerging", "observations": 1},
        ]
        merged, updated, created = _merge_patterns([], new)
        assert len(merged) == 2
        assert updated == 0
        assert created == 2

    def test_matching_pattern_updates_observations(self):
        existing = [{"pattern": "Be concise", "confidence": "emerging", "observations": 2}]
        new = [{"pattern": "be concise", "confidence": "emerging", "observations": 3}]
        merged, updated, created = _merge_patterns(existing, new)
        assert len(merged) == 1
        assert merged[0]["observations"] == 5
        assert merged[0]["confidence"] == "established"  # 5 >= 4
        assert merged[0]["pattern"] == "Be concise"  # keeps original casing
        assert updated == 1
        assert created == 0

    def test_confidence_never_downgrades(self):
        existing = [{"pattern": "Be direct", "confidence": "strong", "observations": 10}]
        new = [{"pattern": "be direct", "confidence": "emerging", "observations": 1}]
        merged, updated, created = _merge_patterns(existing, new)
        assert merged[0]["confidence"] == "strong"
        assert merged[0]["observations"] == 11

    def test_confidence_upgrades_to_strong(self):
        existing = [{"pattern": "Use lists", "confidence": "established", "observations": 6}]
        new = [{"pattern": "use lists", "confidence": "emerging", "observations": 3}]
        merged, updated, created = _merge_patterns(existing, new)
        assert merged[0]["confidence"] == "strong"  # 9 >= 8
        assert merged[0]["observations"] == 9

    def test_mixed_update_and_create(self):
        existing = [{"pattern": "Be concise", "confidence": "emerging", "observations": 1}]
        new = [
            {"pattern": "be concise", "confidence": "emerging", "observations": 2},
            {"pattern": "No emoji", "confidence": "emerging", "observations": 1},
        ]
        merged, updated, created = _merge_patterns(existing, new)
        assert len(merged) == 2
        assert updated == 1
        assert created == 1

    def test_empty_pattern_text_skipped(self):
        merged, updated, created = _merge_patterns([], [{"pattern": "", "confidence": "emerging"}])
        assert len(merged) == 0
        assert created == 0

    def test_no_new_patterns(self):
        existing = [{"pattern": "Be concise", "confidence": "strong", "observations": 10}]
        merged, updated, created = _merge_patterns(existing, [])
        assert merged == existing
        assert updated == 0
        assert created == 0


# ---------------------------------------------------------------------------
# _fetch_recent_interactions
# ---------------------------------------------------------------------------


class TestFetchRecentInteractions:
    def test_fetches_recent_messages(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "t@t.com", "g1", "Test"),
            )
            now = datetime.now(timezone.utc)
            for i in range(3):
                ts = (now - timedelta(days=i)).isoformat()
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, timestamp, user_id) VALUES (?, ?, ?, ?, ?)",
                    ("s1", "user" if i % 2 == 0 else "assistant", f"Message {i}", ts, "u1"),
                )

        with db() as conn:
            result = _fetch_recent_interactions(conn, "u1", days=7)
        assert len(result) == 3

    def test_excludes_old_messages(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "t@t.com", "g1", "Test"),
            )
            old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            conn.execute(
                "INSERT INTO chat_history (session_id, role, content, timestamp, user_id) VALUES (?, ?, ?, ?, ?)",
                ("s1", "user", "Old message", old_ts, "u1"),
            )

        with db() as conn:
            result = _fetch_recent_interactions(conn, "u1", days=7)
        assert len(result) == 0

    def test_truncates_long_content(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "t@t.com", "g1", "Test"),
            )
            ts = datetime.now(timezone.utc).isoformat()
            long_content = "x" * 1000
            conn.execute(
                "INSERT INTO chat_history (session_id, role, content, timestamp, user_id) VALUES (?, ?, ?, ?, ?)",
                ("s1", "user", long_content, ts, "u1"),
            )

        with db() as conn:
            result = _fetch_recent_interactions(conn, "u1", days=7)
        assert len(result[0]["content"]) == 500

    def test_parses_applied_changes(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "t@t.com", "g1", "Test"),
            )
            ts = datetime.now(timezone.utc).isoformat()
            changes = json.dumps({"created": [{"id": "t1"}], "updated": [{"id": "t2"}, {"id": "t3"}]})
            conn.execute(
                "INSERT INTO chat_history (session_id, role, content, applied_changes, timestamp, user_id)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("s1", "assistant", "Done", changes, ts, "u1"),
            )

        with db() as conn:
            result = _fetch_recent_interactions(conn, "u1", days=7)
        assert "changes" in result[0]
        assert "created: 1" in result[0]["changes"]
        assert "updated: 2" in result[0]["changes"]


# ---------------------------------------------------------------------------
# _format_interactions_for_llm
# ---------------------------------------------------------------------------


class TestFormatInteractionsForLlm:
    def test_empty_interactions(self):
        result = _format_interactions_for_llm([], [])
        assert "No recent interactions" in result

    def test_formats_interactions(self):
        interactions = [
            {"role": "user", "content": "Add a task"},
            {"role": "assistant", "content": "Created task", "changes": "created: 1"},
        ]
        result = _format_interactions_for_llm(interactions, [])
        assert "[user] Add a task" in result
        assert "[assistant] Created task [applied: created: 1]" in result

    def test_includes_dismissed_findings(self):
        interactions = [{"role": "user", "content": "Hello"}]
        dismissed = [{"finding_type": "stale", "message": "Old item", "priority": 3}]
        result = _format_interactions_for_llm(interactions, dismissed)
        assert "Dismissed findings" in result
        assert "[stale] Old item" in result


# ---------------------------------------------------------------------------
# aggregate_personality_patterns (integration, mocked LLM)
# ---------------------------------------------------------------------------


class TestAggregatePersonalityPatterns:
    @pytest.mark.asyncio
    async def test_skips_empty_user_id(self):
        result = await aggregate_personality_patterns("")
        assert result.patterns_found == 0

    @pytest.mark.asyncio
    async def test_skips_too_few_interactions(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "t@t.com", "g1", "Test"),
            )
            ts = datetime.now(timezone.utc).isoformat()
            # Only 2 interactions — below threshold of 4
            for role in ("user", "assistant"):
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, timestamp, user_id) VALUES (?, ?, ?, ?, ?)",
                    ("s1", role, "Hello", ts, "u1"),
                )

        result = await aggregate_personality_patterns("u1")
        assert result.patterns_found == 0

    @pytest.mark.asyncio
    async def test_creates_preference_thing_when_none_exists(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "t@t.com", "g1", "Test"),
            )
            ts = datetime.now(timezone.utc).isoformat()
            for i in range(5):
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, timestamp, user_id) VALUES (?, ?, ?, ?, ?)",
                    ("s1", "user" if i % 2 == 0 else "assistant", f"Msg {i}", ts, "u1"),
                )

        llm_response = json.dumps(
            {"patterns": [{"pattern": "Prefers concise responses", "confidence": "emerging", "observations": 3}]}
        )

        with patch("backend.sweep._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await aggregate_personality_patterns("u1")

        assert result.patterns_found == 1
        assert result.patterns_created == 1

        # Verify the preference Thing was created
        with db() as conn:
            row = conn.execute(
                "SELECT data FROM things WHERE type_hint = 'preference' AND user_id = ?",
                ("u1",),
            ).fetchone()
        assert row is not None
        data = json.loads(row["data"])
        assert len(data["patterns"]) == 1
        assert data["patterns"][0]["pattern"] == "Prefers concise responses"

    @pytest.mark.asyncio
    async def test_updates_existing_preference_thing(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "t@t.com", "g1", "Test"),
            )
            # Create existing preference Thing
            existing_data = json.dumps(
                {"patterns": [{"pattern": "Be concise", "confidence": "emerging", "observations": 2}]}
            )
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                ("existing-pref", "Personality Preferences", "preference", 1, existing_data, "u1"),
            )
            ts = datetime.now(timezone.utc).isoformat()
            for i in range(5):
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, timestamp, user_id) VALUES (?, ?, ?, ?, ?)",
                    ("s1", "user" if i % 2 == 0 else "assistant", f"Msg {i}", ts, "u1"),
                )

        llm_response = json.dumps(
            {
                "patterns": [
                    {"pattern": "be concise", "confidence": "emerging", "observations": 2},
                    {"pattern": "No emoji", "confidence": "emerging", "observations": 1},
                ]
            }
        )

        with patch("backend.sweep._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await aggregate_personality_patterns("u1")

        assert result.patterns_found == 2
        assert result.patterns_updated == 1
        assert result.patterns_created == 1

        # Verify the existing Thing was updated (not a new one created)
        with db() as conn:
            rows = conn.execute(
                "SELECT id, data FROM things WHERE type_hint = 'preference' AND user_id = ?",
                ("u1",),
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["id"] == "existing-pref"
        data = json.loads(rows[0]["data"])
        assert len(data["patterns"]) == 2

    @pytest.mark.asyncio
    async def test_handles_invalid_llm_json(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "t@t.com", "g1", "Test"),
            )
            ts = datetime.now(timezone.utc).isoformat()
            for i in range(5):
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, timestamp, user_id) VALUES (?, ?, ?, ?, ?)",
                    ("s1", "user", f"Msg {i}", ts, "u1"),
                )

        with patch("backend.sweep._chat", new_callable=AsyncMock, return_value="not-json{"):
            result = await aggregate_personality_patterns("u1")

        assert result.patterns_found == 0

    @pytest.mark.asyncio
    async def test_handles_empty_patterns_response(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "t@t.com", "g1", "Test"),
            )
            ts = datetime.now(timezone.utc).isoformat()
            for i in range(5):
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, timestamp, user_id) VALUES (?, ?, ?, ?, ?)",
                    ("s1", "user", f"Msg {i}", ts, "u1"),
                )

        with patch("backend.sweep._chat", new_callable=AsyncMock, return_value='{"patterns": []}'):
            result = await aggregate_personality_patterns("u1")

        assert result.patterns_found == 0
        assert result.patterns_created == 0
