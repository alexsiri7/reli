"""Tests for personality pattern aggregation sweep."""

import json
from datetime import date, timedelta

import pytest

from backend.database import db
from backend.personality_sweep import (
    PersonalitySweepResult,
    detect_finding_dismissals,
    detect_finding_engagement,
    detect_interaction_cadence,
    detect_message_brevity,
    detect_title_editing,
    run_personality_sweep,
    store_personality_patterns,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_chat_message(
    conn,
    session_id: str,
    role: str,
    content: str,
    applied_changes: dict | None = None,
    timestamp: str | None = None,
    user_id: str | None = None,
) -> None:
    ts = timestamp or date.today().isoformat()
    conn.execute(
        """INSERT INTO chat_history
           (session_id, role, content, applied_changes, timestamp, user_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            role,
            content,
            json.dumps(applied_changes) if applied_changes else None,
            ts,
            user_id,
        ),
    )


def _insert_sweep_finding(
    conn,
    finding_id: str,
    finding_type: str,
    message: str,
    dismissed: bool = False,
    created_at: str | None = None,
    user_id: str | None = None,
) -> None:
    ts = created_at or date.today().isoformat()
    conn.execute(
        """INSERT INTO sweep_findings
           (id, finding_type, message, priority, dismissed, created_at, user_id)
           VALUES (?, ?, ?, 2, ?, ?, ?)""",
        (finding_id, finding_type, message, int(dismissed), ts, user_id),
    )


# ---------------------------------------------------------------------------
# Title editing detection
# ---------------------------------------------------------------------------


class TestDetectTitleEditing:
    def test_detects_frequent_title_edits(self, patched_db):
        with db() as conn:
            # Create 5 creations and 3 title updates (60% ratio)
            for i in range(5):
                _insert_chat_message(
                    conn,
                    "s1",
                    "assistant",
                    f"Created thing {i}",
                    applied_changes={"created": [{"id": f"t{i}", "title": f"Thing {i}"}], "updated": [], "deleted": []},
                )
            for i in range(3):
                _insert_chat_message(
                    conn,
                    "s1",
                    "assistant",
                    f"Updated thing {i}",
                    applied_changes={
                        "created": [],
                        "updated": [{"id": f"t{i}", "title": f"Renamed {i}"}],
                        "deleted": [],
                    },
                )

        with db() as conn:
            signal = detect_title_editing(conn)
        assert signal is not None
        assert signal.category == "title_editing"
        assert signal.observations == 3

    def test_no_signal_below_threshold(self, patched_db):
        with db() as conn:
            # Only 2 title edits, below _MIN_OBSERVATIONS=3
            for i in range(5):
                _insert_chat_message(
                    conn,
                    "s1",
                    "assistant",
                    f"Created thing {i}",
                    applied_changes={"created": [{"id": f"t{i}", "title": f"Thing {i}"}], "updated": [], "deleted": []},
                )
            for i in range(2):
                _insert_chat_message(
                    conn,
                    "s1",
                    "assistant",
                    f"Updated thing {i}",
                    applied_changes={
                        "created": [],
                        "updated": [{"id": f"t{i}", "title": f"Renamed {i}"}],
                        "deleted": [],
                    },
                )

        with db() as conn:
            signal = detect_title_editing(conn)
        assert signal is None

    def test_no_signal_when_low_ratio(self, patched_db):
        with db() as conn:
            # 20 creations and 3 title updates (15% ratio, below 20% threshold)
            for i in range(20):
                _insert_chat_message(
                    conn,
                    "s1",
                    "assistant",
                    f"Created thing {i}",
                    applied_changes={"created": [{"id": f"t{i}", "title": f"Thing {i}"}], "updated": [], "deleted": []},
                )
            for i in range(3):
                _insert_chat_message(
                    conn,
                    "s1",
                    "assistant",
                    f"Updated thing {i}",
                    applied_changes={
                        "created": [],
                        "updated": [{"id": f"t{i}", "title": f"Renamed {i}"}],
                        "deleted": [],
                    },
                )

        with db() as conn:
            signal = detect_title_editing(conn)
        assert signal is None


# ---------------------------------------------------------------------------
# Finding dismissal detection
# ---------------------------------------------------------------------------


class TestDetectFindingDismissals:
    def test_detects_high_dismissal_rate(self, patched_db):
        with db() as conn:
            # 5 stale findings, 4 dismissed (80%)
            for i in range(5):
                _insert_sweep_finding(conn, f"sf-{i}", "stale", f"Stale thing {i}", dismissed=(i < 4))

        with db() as conn:
            signals = detect_finding_dismissals(conn)
        assert len(signals) == 1
        assert signals[0].category == "finding_dismissals"
        assert "stale" in signals[0].pattern

    def test_no_signal_for_low_dismissal_rate(self, patched_db):
        with db() as conn:
            # 5 stale findings, 1 dismissed (20%)
            for i in range(5):
                _insert_sweep_finding(conn, f"sf-{i}", "stale", f"Stale thing {i}", dismissed=(i < 1))

        with db() as conn:
            signals = detect_finding_dismissals(conn)
        assert len(signals) == 0


# ---------------------------------------------------------------------------
# Finding engagement detection
# ---------------------------------------------------------------------------


class TestDetectFindingEngagement:
    def test_detects_high_engagement(self, patched_db):
        with db() as conn:
            # 5 approaching_date findings, 0 dismissed (100% engagement)
            for i in range(5):
                _insert_sweep_finding(conn, f"sf-{i}", "approaching_date", f"Date item {i}", dismissed=False)

        with db() as conn:
            signals = detect_finding_engagement(conn)
        assert len(signals) == 1
        assert signals[0].category == "finding_engagement"
        assert "approaching date" in signals[0].pattern

    def test_no_signal_for_low_engagement(self, patched_db):
        with db() as conn:
            # 5 findings, 3 dismissed (60% engaged, below 80% threshold)
            for i in range(5):
                _insert_sweep_finding(conn, f"sf-{i}", "stale", f"Stale {i}", dismissed=(i < 3))

        with db() as conn:
            signals = detect_finding_engagement(conn)
        assert len(signals) == 0


# ---------------------------------------------------------------------------
# Message brevity detection
# ---------------------------------------------------------------------------


class TestDetectMessageBrevity:
    def test_detects_concise_user(self, patched_db):
        with db() as conn:
            # Short messages
            for i in range(10):
                _insert_chat_message(conn, "s1", "user", f"Do task {i}")

        with db() as conn:
            signal = detect_message_brevity(conn)
        assert signal is not None
        assert signal.category == "message_brevity"
        assert "concise" in signal.pattern

    def test_detects_verbose_user(self, patched_db):
        with db() as conn:
            # Long messages
            for i in range(10):
                long_msg = (
                    f"Please create a detailed task with comprehensive description "
                    f"covering all aspects of the project including timeline, "
                    f"dependencies, resources needed, and expected outcomes for "
                    f"item number {i} in our ongoing initiative"
                )
                _insert_chat_message(conn, "s1", "user", long_msg)

        with db() as conn:
            signal = detect_message_brevity(conn)
        assert signal is not None
        assert "detailed" in signal.pattern

    def test_no_signal_for_moderate_length(self, patched_db):
        with db() as conn:
            # Medium-length messages (80-200 chars)
            for i in range(10):
                msg = f"Create a task for the upcoming project meeting about quarterly review number {i}"
                _insert_chat_message(conn, "s1", "user", msg)

        with db() as conn:
            signal = detect_message_brevity(conn)
        assert signal is None


# ---------------------------------------------------------------------------
# Interaction cadence detection
# ---------------------------------------------------------------------------


class TestDetectInteractionCadence:
    def test_detects_daily_user(self, patched_db):
        with db() as conn:
            # Active on 25 of the last 30 days
            for i in range(25):
                day = (date.today() - timedelta(days=i)).isoformat()
                _insert_chat_message(conn, "s1", "user", f"Message on day {i}", timestamp=day)

        with db() as conn:
            signal = detect_interaction_cadence(conn)
        assert signal is not None
        assert "daily" in signal.pattern

    def test_detects_infrequent_user(self, patched_db):
        with db() as conn:
            # Active on only 4 of the last 30 days
            for i in [0, 7, 14, 21]:
                day = (date.today() - timedelta(days=i)).isoformat()
                _insert_chat_message(conn, "s1", "user", f"Message on day {i}", timestamp=day)

        with db() as conn:
            signal = detect_interaction_cadence(conn)
        assert signal is not None
        assert "infrequently" in signal.pattern


# ---------------------------------------------------------------------------
# Pattern storage
# ---------------------------------------------------------------------------


class TestStorePersonalityPatterns:
    def test_creates_preference_thing(self, patched_db):
        from backend.personality_sweep import PatternSignal

        signals = [
            PatternSignal(
                pattern="User prefers concise messages",
                confidence="moderate",
                observations=8,
                category="message_brevity",
                detail="avg 45 chars",
            )
        ]

        thing_id = store_personality_patterns(signals)
        assert thing_id is not None

        with db() as conn:
            row = conn.execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
        assert row is not None
        assert row["type_hint"] == "preference"
        assert row["surface"] == 0  # Not shown in default views

        data = json.loads(row["data"])
        assert len(data["patterns"]) == 1
        assert data["patterns"][0]["pattern"] == "User prefers concise messages"

    def test_updates_existing_preference_thing(self, patched_db):
        from backend.personality_sweep import PatternSignal

        # Create initial
        signals1 = [
            PatternSignal(
                pattern="User prefers concise messages",
                confidence="moderate",
                observations=8,
                category="message_brevity",
            )
        ]
        thing_id1 = store_personality_patterns(signals1)

        # Update with new pattern (different category)
        signals2 = [
            PatternSignal(
                pattern="User ignores stale alerts",
                confidence="strong",
                observations=12,
                category="finding_dismissals",
            )
        ]
        thing_id2 = store_personality_patterns(signals2)

        assert thing_id1 == thing_id2  # Same Thing updated

        with db() as conn:
            row = conn.execute("SELECT data FROM things WHERE id = ?", (thing_id1,)).fetchone()
        data = json.loads(row["data"])
        # Should have both patterns (old message_brevity was not in new sweep so kept,
        # plus new finding_dismissals)
        categories = {p["category"] for p in data["patterns"]}
        assert "message_brevity" in categories
        assert "finding_dismissals" in categories

    def test_supersedes_same_category(self, patched_db):
        from backend.personality_sweep import PatternSignal

        # Create initial brevity signal
        signals1 = [
            PatternSignal(
                pattern="User prefers concise messages",
                confidence="moderate",
                observations=8,
                category="message_brevity",
            )
        ]
        thing_id1 = store_personality_patterns(signals1)

        # Update with new brevity signal (same category, should replace)
        signals2 = [
            PatternSignal(
                pattern="User writes detailed messages",
                confidence="strong",
                observations=15,
                category="message_brevity",
            )
        ]
        thing_id2 = store_personality_patterns(signals2)

        assert thing_id1 == thing_id2

        with db() as conn:
            row = conn.execute("SELECT data FROM things WHERE id = ?", (thing_id1,)).fetchone()
        data = json.loads(row["data"])
        brevity_patterns = [p for p in data["patterns"] if p["category"] == "message_brevity"]
        assert len(brevity_patterns) == 1
        assert brevity_patterns[0]["pattern"] == "User writes detailed messages"

    def test_returns_none_for_empty_signals(self, patched_db):
        thing_id = store_personality_patterns([])
        assert thing_id is None


# ---------------------------------------------------------------------------
# Full sweep integration
# ---------------------------------------------------------------------------


class TestRunPersonalitySweep:
    @pytest.mark.asyncio
    async def test_full_sweep_with_data(self, patched_db):
        with db() as conn:
            # Create data that triggers brevity detection
            for i in range(10):
                _insert_chat_message(conn, "s1", "user", f"Do task {i}")

        result = await run_personality_sweep()
        assert isinstance(result, PersonalitySweepResult)
        assert result.signals_detected >= 1

    @pytest.mark.asyncio
    async def test_full_sweep_empty_db(self, patched_db):
        result = await run_personality_sweep()
        assert isinstance(result, PersonalitySweepResult)
        assert result.signals_detected == 0
        assert result.thing_id is None
