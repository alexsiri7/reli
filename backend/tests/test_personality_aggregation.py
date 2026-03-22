"""Tests for personality pattern aggregation in sweep (Phase 3)."""

import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.sweep import (
    AggregationResult,
    BehavioralSignal,
    _format_signals_for_llm,
    _merge_patterns,
    collect_behavioral_signals,
    aggregate_personality_patterns,
)


# ---------------------------------------------------------------------------
# BehavioralSignal collection
# ---------------------------------------------------------------------------


class TestCollectBehavioralSignals:
    def _setup_user(self, conn):
        conn.execute(
            "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
            ("u1", "test@test.com", "g1", "Test User"),
        )

    def test_empty_db_returns_no_signals(self, patched_db):
        from backend.database import db

        with db() as conn:
            self._setup_user(conn)
            signals = collect_behavioral_signals(conn, "u1")
        assert signals == []

    def test_title_edits_detected(self, patched_db):
        from backend.database import db

        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            self._setup_user(conn)
            # Insert 4 assistant messages with title updates in applied_changes
            for i in range(4):
                changes = json.dumps({
                    "updated": [{"id": f"t{i}", "title": f"New Title {i}"}],
                })
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, applied_changes, timestamp, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"s{i}", "assistant", f"Updated thing {i}", changes, now, "u1"),
                )

            signals = collect_behavioral_signals(conn, "u1")

        title_signals = [s for s in signals if s.signal_type == "title_editing"]
        assert len(title_signals) == 1
        assert title_signals[0].count == 4

    def test_title_edits_below_threshold_ignored(self, patched_db):
        from backend.database import db

        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            self._setup_user(conn)
            # Only 2 title edits — below threshold of 3
            for i in range(2):
                changes = json.dumps({
                    "updated": [{"id": f"t{i}", "title": f"New Title {i}"}],
                })
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, applied_changes, timestamp, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"s{i}", "assistant", f"Updated {i}", changes, now, "u1"),
                )

            signals = collect_behavioral_signals(conn, "u1")

        title_signals = [s for s in signals if s.signal_type == "title_editing"]
        assert len(title_signals) == 0

    def test_dismissed_findings_detected(self, patched_db):
        from backend.database import db

        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            self._setup_user(conn)
            # Insert 3 dismissed stale findings
            for i in range(3):
                conn.execute(
                    "INSERT INTO sweep_findings (id, finding_type, message, dismissed, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"sf-{i}", "stale", f"Stale thing {i}", 1, now, "u1"),
                )

            signals = collect_behavioral_signals(conn, "u1")

        dismissed_signals = [s for s in signals if s.signal_type == "finding_dismissed"]
        assert len(dismissed_signals) == 1
        assert dismissed_signals[0].extra["finding_type"] == "stale"
        assert dismissed_signals[0].count == 3

    def test_finding_engagement_high(self, patched_db):
        from backend.database import db

        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            self._setup_user(conn)
            # 4 approaching_date findings, only 1 dismissed — high engagement
            for i in range(4):
                conn.execute(
                    "INSERT INTO sweep_findings (id, finding_type, message, dismissed, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"sf-{i}", "approaching_date", f"Date {i}", 1 if i == 0 else 0, now, "u1"),
                )

            signals = collect_behavioral_signals(conn, "u1")

        engaged = [s for s in signals if s.signal_type == "finding_engaged"]
        assert len(engaged) == 1
        assert engaged[0].extra["finding_type"] == "approaching_date"
        assert engaged[0].extra["engagement_rate"] == 0.75

    def test_finding_ignored_pattern(self, patched_db):
        from backend.database import db

        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            self._setup_user(conn)
            # 4 orphan findings, 3 dismissed — mostly ignored
            for i in range(4):
                conn.execute(
                    "INSERT INTO sweep_findings (id, finding_type, message, dismissed, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"sf-{i}", "orphan", f"Orphan {i}", 1 if i < 3 else 0, now, "u1"),
                )

            signals = collect_behavioral_signals(conn, "u1")

        ignored = [s for s in signals if s.signal_type == "finding_ignored"]
        assert len(ignored) == 1
        assert ignored[0].extra["finding_type"] == "orphan"

    def test_brief_messages_detected(self, patched_db):
        from backend.database import db

        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            self._setup_user(conn)
            # 6 short user messages
            for i in range(6):
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, timestamp, user_id) VALUES (?, ?, ?, ?, ?)",
                    (f"s{i}", "user", f"Do task {i}", now, "u1"),
                )

            signals = collect_behavioral_signals(conn, "u1")

        brief = [s for s in signals if s.signal_type == "brief_messages"]
        assert len(brief) == 1

    def test_detailed_messages_detected(self, patched_db):
        from backend.database import db

        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            self._setup_user(conn)
            # 6 long user messages
            for i in range(6):
                content = "x" * 250
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, timestamp, user_id) VALUES (?, ?, ?, ?, ?)",
                    (f"s{i}", "user", content, now, "u1"),
                )

            signals = collect_behavioral_signals(conn, "u1")

        detailed = [s for s in signals if s.signal_type == "detailed_messages"]
        assert len(detailed) == 1

    def test_old_data_excluded_by_lookback(self, patched_db):
        from backend.database import db

        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with db() as conn:
            self._setup_user(conn)
            # Title edits from 30 days ago — outside default 14-day window
            for i in range(5):
                changes = json.dumps({"updated": [{"id": f"t{i}", "title": f"Old {i}"}]})
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, applied_changes, timestamp, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"s{i}", "assistant", f"Old update {i}", changes, old, "u1"),
                )

            signals = collect_behavioral_signals(conn, "u1")

        assert len(signals) == 0


# ---------------------------------------------------------------------------
# Pattern merging
# ---------------------------------------------------------------------------


class TestMergePatterns:
    def test_new_patterns_appended(self):
        existing = [{"pattern": "Be concise", "confidence": "strong", "observations": 10}]
        new = [{"pattern": "Use bullet points", "confidence": "emerging", "observations": 2}]
        result = _merge_patterns(existing, new)
        assert len(result) == 2
        assert result[1]["pattern"] == "Use bullet points"

    def test_matching_patterns_merged(self):
        existing = [{"pattern": "Be concise", "confidence": "emerging", "observations": 3}]
        new = [{"pattern": "Be concise", "confidence": "emerging", "observations": 2}]
        result = _merge_patterns(existing, new)
        assert len(result) == 1
        assert result[0]["observations"] == 5
        assert result[0]["confidence"] == "established"

    def test_case_insensitive_matching(self):
        existing = [{"pattern": "Be Concise", "confidence": "emerging", "observations": 3}]
        new = [{"pattern": "be concise", "confidence": "emerging", "observations": 2}]
        result = _merge_patterns(existing, new)
        assert len(result) == 1
        assert result[0]["observations"] == 5

    def test_confidence_upgrade_to_strong(self):
        existing = [{"pattern": "No emoji", "confidence": "established", "observations": 8}]
        new = [{"pattern": "No emoji", "confidence": "emerging", "observations": 3}]
        result = _merge_patterns(existing, new)
        assert result[0]["confidence"] == "strong"
        assert result[0]["observations"] == 11

    def test_empty_existing(self):
        result = _merge_patterns([], [{"pattern": "New", "confidence": "emerging", "observations": 1}])
        assert len(result) == 1

    def test_empty_new(self):
        existing = [{"pattern": "Old", "confidence": "strong", "observations": 10}]
        result = _merge_patterns(existing, [])
        assert len(result) == 1
        assert result[0] == existing[0]

    def test_does_not_mutate_input(self):
        existing = [{"pattern": "A", "confidence": "emerging", "observations": 3}]
        new = [{"pattern": "A", "confidence": "emerging", "observations": 2}]
        _merge_patterns(existing, new)
        assert existing[0]["observations"] == 3  # unchanged


# ---------------------------------------------------------------------------
# LLM prompt formatting
# ---------------------------------------------------------------------------


class TestFormatSignalsForLlm:
    def test_no_signals(self):
        result = _format_signals_for_llm([], [])
        assert "No behavioral signals" in result

    def test_signals_formatted(self):
        signals = [
            BehavioralSignal("title_editing", "Edited 5 titles", 5, {"total_updates": 10}),
            BehavioralSignal("brief_messages", "Short messages", 8, {"avg_length": 30.5}),
        ]
        result = _format_signals_for_llm(signals, [])
        assert "2 behavioral signals" in result
        assert "title_editing" in result
        assert "brief_messages" in result
        assert "total_updates=10" in result

    def test_existing_patterns_included(self):
        signals = [BehavioralSignal("test", "Test signal", 1)]
        existing = [{"pattern": "Be concise", "confidence": "strong", "observations": 10}]
        result = _format_signals_for_llm(signals, existing)
        assert "Existing personality patterns" in result
        assert "[strong] Be concise" in result


# ---------------------------------------------------------------------------
# Full aggregation (with mocked LLM)
# ---------------------------------------------------------------------------


class TestAggregatePersonalityPatterns:
    @pytest.mark.asyncio
    async def test_no_signals_skips_llm(self, patched_db):
        """When there are no behavioral signals, LLM is not called."""
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )

        result = await aggregate_personality_patterns("u1")
        assert result.signals_collected == 0
        assert result.patterns_updated == 0

    @pytest.mark.asyncio
    async def test_creates_preference_thing(self, patched_db):
        """LLM returns patterns → a new preference Thing is created."""
        from backend.database import db

        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )
            # Create enough signals to trigger collection
            for i in range(5):
                changes = json.dumps({"updated": [{"id": f"t{i}", "title": f"Edited {i}"}]})
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, applied_changes, timestamp, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"s{i}", "assistant", f"Done {i}", changes, now, "u1"),
                )

        llm_response = json.dumps({
            "patterns": [
                {"pattern": "Use shorter task titles", "confidence": "emerging", "observations": 5},
            ]
        })

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await aggregate_personality_patterns("u1")

        assert result.signals_collected >= 1
        assert result.patterns_updated == 1

        # Verify the preference Thing was created
        with db() as conn:
            row = conn.execute(
                "SELECT data FROM things WHERE type_hint = 'preference' AND title = 'Learned Personality Preferences' AND user_id = ?",
                ("u1",),
            ).fetchone()
            assert row is not None
            data = json.loads(row["data"])
            assert len(data["patterns"]) == 1
            assert data["patterns"][0]["pattern"] == "Use shorter task titles"

    @pytest.mark.asyncio
    async def test_updates_existing_preference_thing(self, patched_db):
        """When a preference Thing already exists, it gets updated (merged)."""
        from backend.database import db

        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )
            # Create existing preference Thing
            existing_data = json.dumps({
                "patterns": [
                    {"pattern": "Be concise", "confidence": "established", "observations": 7},
                ]
            })
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, created_at, updated_at, user_id) VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
                ("pref-existing", "Learned Personality Preferences", "preference", existing_data, now, now, "u1"),
            )
            # Add behavioral signals
            for i in range(5):
                changes = json.dumps({"updated": [{"id": f"t{i}", "title": f"Edited {i}"}]})
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, applied_changes, timestamp, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"s{i}", "assistant", f"Done {i}", changes, now, "u1"),
                )

        llm_response = json.dumps({
            "patterns": [
                {"pattern": "Use shorter task titles", "confidence": "emerging", "observations": 3},
            ]
        })

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await aggregate_personality_patterns("u1")

        assert result.patterns_updated == 1

        # Verify existing Thing was updated with merged patterns
        with db() as conn:
            row = conn.execute(
                "SELECT data FROM things WHERE id = 'pref-existing'",
            ).fetchone()
            data = json.loads(row["data"])
            assert len(data["patterns"]) == 2  # original + new
            patterns = {p["pattern"] for p in data["patterns"]}
            assert "Be concise" in patterns
            assert "Use shorter task titles" in patterns

    @pytest.mark.asyncio
    async def test_invalid_llm_response_handled(self, patched_db):
        """Invalid JSON from LLM doesn't crash."""
        from backend.database import db

        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )
            for i in range(5):
                changes = json.dumps({"updated": [{"id": f"t{i}", "title": f"X {i}"}]})
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, applied_changes, timestamp, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"s{i}", "assistant", f"Done {i}", changes, now, "u1"),
                )

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value="not valid json {"):
            result = await aggregate_personality_patterns("u1")

        assert result.signals_collected >= 1
        assert result.patterns_updated == 0

    @pytest.mark.asyncio
    async def test_empty_patterns_from_llm(self, patched_db):
        """LLM returns empty patterns list → no Thing created."""
        from backend.database import db

        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )
            for i in range(5):
                changes = json.dumps({"updated": [{"id": f"t{i}", "title": f"X {i}"}]})
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, applied_changes, timestamp, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"s{i}", "assistant", f"Done {i}", changes, now, "u1"),
                )

        llm_response = json.dumps({"patterns": []})

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await aggregate_personality_patterns("u1")

        assert result.patterns_updated == 0

        # No preference Thing should exist
        with db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM things WHERE type_hint = 'preference' AND user_id = ?",
                ("u1",),
            ).fetchone()
            assert row["cnt"] == 0
