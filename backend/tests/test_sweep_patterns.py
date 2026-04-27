"""Tests for sweep personality pattern aggregation (Phase 3)."""

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session

import backend.db_engine as _engine_mod
from backend.sweep import (
    _SWEEP_PREF_TITLE,
    BehavioralSignal,
    _detect_finding_dismissal_patterns,
    _detect_finding_engagement_patterns,
    _detect_title_shortening,
    _format_signals_for_llm,
    _merge_patterns,
    _upsert_sweep_preference,
    aggregate_personality_patterns,
    collect_behavioral_signals,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_user(conn, user_id: str = "u1") -> None:
    conn.execute(
        "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
        (user_id, f"{user_id}@test.com", f"g-{user_id}", "Test User"),
    )


def _insert_chat_message(
    conn,
    *,
    session_id: str = "sess-1",
    role: str = "assistant",
    content: str = "Done.",
    applied_changes: dict | None = None,
    user_id: str = "u1",
    timestamp: str | None = None,
) -> None:
    ts = timestamp or date.today().isoformat()
    conn.execute(
        """INSERT INTO chat_history
           (session_id, role, content, applied_changes, timestamp, user_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, role, content, json.dumps(applied_changes) if applied_changes else None, ts, user_id),
    )


def _insert_finding(
    conn,
    finding_id: str,
    finding_type: str,
    *,
    dismissed: bool = False,
    user_id: str = "u1",
    created_at: str | None = None,
) -> None:
    ts = created_at or date.today().isoformat()
    conn.execute(
        """INSERT INTO sweep_findings
           (id, finding_type, message, priority, dismissed, created_at, user_id)
           VALUES (?, ?, ?, 2, ?, ?, ?)""",
        (finding_id, finding_type, f"Test {finding_type}", int(dismissed), ts, user_id),
    )


def _insert_preference(conn, user_id: str, patterns: list[dict], thing_id: str = "t-sweep-existing") -> None:
    conn.execute(
        "INSERT INTO things (id, title, type_hint, active, data, user_id) VALUES (?, ?, 'preference', 1, ?, ?)",
        (thing_id, _SWEEP_PREF_TITLE, json.dumps({"patterns": patterns}), user_id),
    )


# ---------------------------------------------------------------------------
# Title shortening detection
# ---------------------------------------------------------------------------


class TestDetectTitleShortening:
    def test_no_chat_history(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)
        cutoff = (date.today() - timedelta(days=30)).isoformat()
        with Session(_engine_mod.engine) as session:
            signals = _detect_title_shortening(session, "u1", cutoff)
        assert signals == []

    def test_detects_shortened_titles(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)
            # Reli creates a Thing with a long title
            _insert_chat_message(
                conn,
                applied_changes={
                    "created": [{"id": "t1", "title": "Complete the quarterly financial report review"}],
                    "updated": [],
                    "deleted": [],
                    "merged": [],
                    "relationships_created": [],
                },
            )
            # User later renames it shorter
            _insert_chat_message(
                conn,
                applied_changes={
                    "created": [],
                    "updated": [{"id": "t1", "title": "Q4 report"}],
                    "deleted": [],
                    "merged": [],
                    "relationships_created": [],
                },
            )

        cutoff = (date.today() - timedelta(days=30)).isoformat()
        with Session(_engine_mod.engine) as session:
            signals = _detect_title_shortening(session, "u1", cutoff)

        assert len(signals) == 1
        assert signals[0].signal_type == "title_shortening"
        assert signals[0].count >= 1
        assert signals[0].total >= 1

    def test_no_signal_when_title_lengthened(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)
            _insert_chat_message(
                conn,
                applied_changes={
                    "created": [{"id": "t1", "title": "Report"}],
                    "updated": [],
                    "deleted": [],
                    "merged": [],
                    "relationships_created": [],
                },
            )
            _insert_chat_message(
                conn,
                applied_changes={
                    "created": [],
                    "updated": [{"id": "t1", "title": "Quarterly financial report review"}],
                    "deleted": [],
                    "merged": [],
                    "relationships_created": [],
                },
            )

        cutoff = (date.today() - timedelta(days=30)).isoformat()
        with Session(_engine_mod.engine) as session:
            signals = _detect_title_shortening(session, "u1", cutoff)

        # Should still have a signal (title_updates > 0) but shortening count = 0
        if signals:
            assert signals[0].count == 0


# ---------------------------------------------------------------------------
# Finding dismissal patterns
# ---------------------------------------------------------------------------


class TestDetectFindingDismissalPatterns:
    def test_no_findings(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)
        cutoff = (date.today() - timedelta(days=30)).isoformat()
        with Session(_engine_mod.engine) as session:
            signals = _detect_finding_dismissal_patterns(session, "u1", cutoff)
        assert signals == []

    def test_high_dismissal_rate(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)
            # 4 out of 5 stale findings dismissed
            for i in range(5):
                _insert_finding(conn, f"sf-{i}", "stale", dismissed=(i < 4))

        cutoff = (date.today() - timedelta(days=30)).isoformat()
        with Session(_engine_mod.engine) as session:
            signals = _detect_finding_dismissal_patterns(session, "u1", cutoff)

        assert len(signals) == 1
        assert signals[0].signal_type == "finding_dismissal"
        assert signals[0].count == 4
        assert signals[0].total == 5
        assert "stale" in signals[0].examples

    def test_low_dismissal_rate_no_signal(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)
            # 1 out of 5 dismissed — below threshold
            for i in range(5):
                _insert_finding(conn, f"sf-{i}", "stale", dismissed=(i == 0))

        cutoff = (date.today() - timedelta(days=30)).isoformat()
        with Session(_engine_mod.engine) as session:
            signals = _detect_finding_dismissal_patterns(session, "u1", cutoff)

        assert signals == []

    def test_multiple_finding_types(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)
            # Stale: 3/4 dismissed (high)
            for i in range(4):
                _insert_finding(conn, f"sf-stale-{i}", "stale", dismissed=(i < 3))
            # Approaching date: 0/3 dismissed (low)
            for i in range(3):
                _insert_finding(conn, f"sf-date-{i}", "approaching_date", dismissed=False)

        cutoff = (date.today() - timedelta(days=30)).isoformat()
        with Session(_engine_mod.engine) as session:
            signals = _detect_finding_dismissal_patterns(session, "u1", cutoff)

        assert len(signals) == 1
        assert signals[0].examples == ["stale"]


# ---------------------------------------------------------------------------
# Finding engagement patterns
# ---------------------------------------------------------------------------


class TestDetectFindingEngagementPatterns:
    def test_high_engagement(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)
            # 0 out of 4 approaching_date findings dismissed — high engagement
            for i in range(4):
                _insert_finding(conn, f"sf-{i}", "approaching_date", dismissed=False)

        cutoff = (date.today() - timedelta(days=30)).isoformat()
        with Session(_engine_mod.engine) as session:
            signals = _detect_finding_engagement_patterns(session, "u1", cutoff)

        assert len(signals) == 1
        assert signals[0].signal_type == "finding_engagement"
        assert "approaching_date" in signals[0].examples

    def test_low_engagement_no_signal(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)
            # 3 out of 4 dismissed — low engagement
            for i in range(4):
                _insert_finding(conn, f"sf-{i}", "stale", dismissed=(i < 3))

        cutoff = (date.today() - timedelta(days=30)).isoformat()
        with Session(_engine_mod.engine) as session:
            signals = _detect_finding_engagement_patterns(session, "u1", cutoff)

        assert signals == []


# ---------------------------------------------------------------------------
# Signal formatting
# ---------------------------------------------------------------------------


class TestFormatSignalsForLLM:
    def test_empty_signals(self):
        result = _format_signals_for_llm([])
        assert "No behavioral signals" in result

    def test_formats_signals(self):
        signals = [
            BehavioralSignal(
                signal_type="title_shortening",
                description="User shortens titles",
                count=3,
                total=5,
                examples=['"Long title" → "Short"'],
            ),
        ]
        result = _format_signals_for_llm(signals)
        assert "title_shortening" in result
        assert "3/5" in result
        assert "Long title" in result


# ---------------------------------------------------------------------------
# Pattern merging
# ---------------------------------------------------------------------------


class TestMergePatterns:
    def test_new_patterns_added(self):
        existing = [{"pattern": "Be concise", "confidence": "established", "observations": 5}]
        new = [{"pattern": "Use bullet points", "confidence": "emerging", "observations": 2}]
        merged = _merge_patterns(existing, new)
        texts = [p["pattern"] for p in merged]
        assert "Use bullet points" in texts
        assert "Be concise" in texts  # kept with decay

    def test_matching_patterns_updated(self):
        existing = [{"pattern": "Be concise", "confidence": "established", "observations": 5}]
        new = [{"pattern": "Be concise", "confidence": "strong", "observations": 8}]
        merged = _merge_patterns(existing, new)
        assert len(merged) == 1
        assert merged[0]["confidence"] == "strong"
        assert merged[0]["observations"] == 8

    def test_existing_patterns_decay(self):
        existing = [{"pattern": "Old pattern", "confidence": "strong", "observations": 10}]
        new = []  # no new patterns
        merged = _merge_patterns(existing, new)
        assert len(merged) == 1
        assert merged[0]["confidence"] == "established"
        assert merged[0]["observations"] == 9

    def test_fully_decayed_pattern_removed(self):
        existing = [{"pattern": "Weak pattern", "confidence": "emerging", "observations": 1}]
        new = []
        merged = _merge_patterns(existing, new)
        # observations would become 0 (below threshold) → removed
        assert len(merged) == 0

    def test_case_insensitive_matching(self):
        existing = [{"pattern": "Be concise", "confidence": "emerging", "observations": 2}]
        new = [{"pattern": "be concise", "confidence": "established", "observations": 5}]
        merged = _merge_patterns(existing, new)
        assert len(merged) == 1
        assert merged[0]["confidence"] == "established"


# ---------------------------------------------------------------------------
# Upsert sweep preference
# ---------------------------------------------------------------------------


class TestUpsertSweepPreference:
    def test_creates_new_preference(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)

        patterns = [{"pattern": "Be concise", "confidence": "emerging", "observations": 3}]
        _upsert_sweep_preference("u1", patterns)

        with db() as conn:
            row = conn.execute(
                "SELECT data FROM things WHERE title = ? AND type_hint = 'preference'",
                (_SWEEP_PREF_TITLE,),
            ).fetchone()

        assert row is not None
        data = json.loads(row["data"])
        assert len(data["patterns"]) == 1
        assert data["patterns"][0]["pattern"] == "Be concise"

    def test_updates_existing_preference(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)
            _insert_preference(
                conn,
                "u1",
                [
                    {"pattern": "Be concise", "confidence": "emerging", "observations": 2},
                ],
            )

        # Update with stronger signal
        _upsert_sweep_preference(
            "u1",
            [
                {"pattern": "Be concise", "confidence": "established", "observations": 6},
            ],
        )

        with db() as conn:
            row = conn.execute(
                "SELECT data FROM things WHERE title = ? AND type_hint = 'preference'",
                (_SWEEP_PREF_TITLE,),
            ).fetchone()

        data = json.loads(row["data"])
        assert len(data["patterns"]) == 1
        assert data["patterns"][0]["confidence"] == "established"
        assert data["patterns"][0]["observations"] == 6


# ---------------------------------------------------------------------------
# collect_behavioral_signals
# ---------------------------------------------------------------------------


class TestCollectBehavioralSignals:
    def test_empty_user_id(self):
        assert collect_behavioral_signals("") == []

    def test_collects_multiple_signal_types(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)
            # Add dismissal signal data
            for i in range(4):
                _insert_finding(conn, f"sf-{i}", "stale", dismissed=True)
            _insert_finding(conn, "sf-4", "stale", dismissed=False)

        signals = collect_behavioral_signals("u1")
        types = [s.signal_type for s in signals]
        assert "finding_dismissal" in types


# ---------------------------------------------------------------------------
# Full aggregation (mocked LLM)
# ---------------------------------------------------------------------------


class TestAggregatePersonalityPatterns:
    @pytest.mark.asyncio
    async def test_no_signals_returns_empty(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)

        result = await aggregate_personality_patterns("u1")
        assert result.patterns_updated == 0
        assert result.patterns == []

    @pytest.mark.asyncio
    async def test_full_pipeline_with_mocked_llm(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)
            # Set up dismissal signals
            for i in range(5):
                _insert_finding(conn, f"sf-{i}", "stale", dismissed=True)

        llm_response = json.dumps(
            {
                "patterns": [
                    {"pattern": "Reduce staleness alert frequency", "confidence": "established", "observations": 5},
                ]
            }
        )

        with patch("backend.agents._chat", new=AsyncMock(return_value=llm_response)):
            result = await aggregate_personality_patterns("u1")

        assert result.patterns_updated == 1
        assert result.patterns[0]["pattern"] == "Reduce staleness alert frequency"

        # Verify preference Thing was created
        with db() as conn:
            row = conn.execute(
                "SELECT data FROM things WHERE title = ? AND type_hint = 'preference'",
                (_SWEEP_PREF_TITLE,),
            ).fetchone()
        assert row is not None
        data = json.loads(row["data"])
        assert data["patterns"][0]["pattern"] == "Reduce staleness alert frequency"

    @pytest.mark.asyncio
    async def test_invalid_llm_response(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)
            for i in range(5):
                _insert_finding(conn, f"sf-{i}", "stale", dismissed=True)

        with patch("backend.agents._chat", new=AsyncMock(return_value="not json")):
            result = await aggregate_personality_patterns("u1")

        assert result.patterns_updated == 0

    @pytest.mark.asyncio
    async def test_empty_patterns_from_llm(self, patched_db, db):
        with db() as conn:
            _insert_user(conn)
            for i in range(5):
                _insert_finding(conn, f"sf-{i}", "stale", dismissed=True)

        with patch("backend.agents._chat", new=AsyncMock(return_value='{"patterns": []}')):
            result = await aggregate_personality_patterns("u1")

        assert result.patterns_updated == 0
