"""Tests for personality signal detection in the reasoning agent.

Tests the record_personality_signal tool that detects and records
personality/behavior signals from conversation feedback.
"""

import json

import pytest

from backend.reasoning_agent import _make_reasoning_tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_signal_tool(user_id: str = "u1", session_id: str = "s1"):
    """Create reasoning tools and return the record_personality_signal tool."""
    tools, applied, _ = _make_reasoning_tools(user_id, session_id=session_id)
    # record_personality_signal is the last tool in the list
    signal_tool = tools[-1]
    return signal_tool, applied


def _insert_user(conn, user_id="u1"):
    conn.execute(
        "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
        (user_id, "test@test.com", "g1", "Test User"),
    )


def _insert_preference_thing(conn, thing_id, patterns, user_id="u1"):
    pref_data = json.dumps({"patterns": patterns})
    conn.execute(
        "INSERT INTO things (id, title, type_hint, active, data, user_id, surface)"
        " VALUES (?, ?, ?, 1, ?, ?, 0)",
        (thing_id, "Personality Preferences", "preference", pref_data, user_id),
    )


# ---------------------------------------------------------------------------
# Tool creation
# ---------------------------------------------------------------------------


class TestToolCreation:
    def test_signal_tool_in_tools_list(self):
        tools, _, _ = _make_reasoning_tools("u1")
        # Should have 8 tools (7 original + record_personality_signal)
        assert len(tools) == 8
        # Last tool should be record_personality_signal (wrapped by _traced_tool)
        assert "record_personality_signal" in tools[-1].__name__


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestSignalValidation:
    def test_empty_pattern_rejected(self, patched_db):
        tool, _ = _get_signal_tool()
        result = tool(signal_type="positive", pattern="")
        assert "error" in result

    def test_whitespace_pattern_rejected(self, patched_db):
        tool, _ = _get_signal_tool()
        result = tool(signal_type="positive", pattern="   ")
        assert "error" in result

    def test_invalid_signal_type_rejected(self, patched_db):
        tool, _ = _get_signal_tool()
        result = tool(signal_type="invalid", pattern="Be concise")
        assert "error" in result

    def test_valid_signal_types_accepted(self, patched_db):
        from backend.database import db

        with db() as conn:
            _insert_user(conn)

        for signal_type in ["positive", "negative", "explicit_correction", "implicit_correction"]:
            tool, _ = _get_signal_tool()
            result = tool(signal_type=signal_type, pattern=f"Pattern for {signal_type}")
            assert "error" not in result, f"Failed for signal_type={signal_type}"


# ---------------------------------------------------------------------------
# Creating new preference Things
# ---------------------------------------------------------------------------


class TestCreatePreferenceThing:
    def test_creates_preference_thing_when_none_exists(self, patched_db):
        from backend.database import db

        with db() as conn:
            _insert_user(conn)

        tool, applied = _get_signal_tool()
        result = tool(
            signal_type="explicit_correction",
            pattern="No emoji",
            reasoning="User said 'no emoji please'",
        )

        assert result["action"] == "created"
        assert result["pattern"] == "No emoji"
        assert result["signal_type"] == "explicit_correction"
        assert result["confidence"] == "established"  # explicit corrections start higher
        assert result["observations"] == 3  # explicit correction gets 3
        assert len(applied["created"]) == 1

        # Verify in DB
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM things WHERE type_hint = 'preference' AND active = 1"
            ).fetchone()
            assert row is not None
            data = json.loads(row["data"])
            assert len(data["patterns"]) == 1
            assert data["patterns"][0]["pattern"] == "No emoji"

    def test_creates_with_correct_fields(self, patched_db):
        from backend.database import db

        with db() as conn:
            _insert_user(conn)

        tool, _ = _get_signal_tool()
        tool(signal_type="positive", pattern="Likes proactive suggestions")

        with db() as conn:
            row = conn.execute("SELECT * FROM things WHERE type_hint = 'preference'").fetchone()
            assert row["title"] == "Personality Preferences"
            assert row["surface"] == 0  # not shown in sidebar
            assert row["active"] == 1
            assert row["user_id"] == "u1"


# ---------------------------------------------------------------------------
# Adding to existing preference Things
# ---------------------------------------------------------------------------


class TestAddPatternToExisting:
    def test_adds_pattern_to_existing_thing(self, patched_db):
        from backend.database import db

        with db() as conn:
            _insert_user(conn)
            _insert_preference_thing(conn, "t1", [
                {"pattern": "Be concise", "confidence": "strong", "observations": 5},
            ])

        tool, applied = _get_signal_tool()
        result = tool(signal_type="positive", pattern="Use bullet points")

        assert result["action"] == "added_pattern"
        assert result["thing_id"] == "t1"
        assert result["pattern"] == "Use bullet points"
        assert len(applied["updated"]) == 1

        # Verify both patterns are in the DB
        with db() as conn:
            row = conn.execute("SELECT data FROM things WHERE id = 't1'").fetchone()
            data = json.loads(row["data"])
            assert len(data["patterns"]) == 2
            patterns = [p["pattern"] for p in data["patterns"]]
            assert "Be concise" in patterns
            assert "Use bullet points" in patterns


# ---------------------------------------------------------------------------
# Updating existing patterns
# ---------------------------------------------------------------------------


class TestUpdateExistingPattern:
    def test_increments_observations_on_positive(self, patched_db):
        from backend.database import db

        with db() as conn:
            _insert_user(conn)
            _insert_preference_thing(conn, "t1", [
                {"pattern": "Be concise", "confidence": "emerging", "observations": 2},
            ])

        tool, _ = _get_signal_tool()
        result = tool(signal_type="positive", pattern="Be concise")

        assert result["action"] == "updated"
        assert result["observations"] == 3
        assert result["confidence"] == "established"  # crossed threshold at 3

    def test_explicit_correction_increments_by_3(self, patched_db):
        from backend.database import db

        with db() as conn:
            _insert_user(conn)
            _insert_preference_thing(conn, "t1", [
                {"pattern": "No emoji", "confidence": "emerging", "observations": 1},
            ])

        tool, _ = _get_signal_tool()
        result = tool(signal_type="explicit_correction", pattern="No emoji")

        assert result["observations"] == 4
        assert result["confidence"] == "established"

    def test_negative_decrements_observations(self, patched_db):
        from backend.database import db

        with db() as conn:
            _insert_user(conn)
            _insert_preference_thing(conn, "t1", [
                {"pattern": "Be verbose", "confidence": "established", "observations": 5},
            ])

        tool, _ = _get_signal_tool()
        result = tool(signal_type="negative", pattern="Be verbose")

        assert result["observations"] == 4
        assert result["confidence"] == "established"  # still above threshold

    def test_negative_floors_at_1(self, patched_db):
        from backend.database import db

        with db() as conn:
            _insert_user(conn)
            _insert_preference_thing(conn, "t1", [
                {"pattern": "Be verbose", "confidence": "emerging", "observations": 1},
            ])

        tool, _ = _get_signal_tool()
        result = tool(signal_type="negative", pattern="Be verbose")

        assert result["observations"] == 1  # can't go below 1

    def test_case_insensitive_matching(self, patched_db):
        from backend.database import db

        with db() as conn:
            _insert_user(conn)
            _insert_preference_thing(conn, "t1", [
                {"pattern": "Be Concise", "confidence": "emerging", "observations": 2},
            ])

        tool, _ = _get_signal_tool()
        result = tool(signal_type="positive", pattern="be concise")

        assert result["action"] == "updated"
        assert result["observations"] == 3


# ---------------------------------------------------------------------------
# Confidence progression
# ---------------------------------------------------------------------------


class TestConfidenceProgression:
    def test_emerging_to_established(self, patched_db):
        from backend.database import db

        with db() as conn:
            _insert_user(conn)
            _insert_preference_thing(conn, "t1", [
                {"pattern": "Use lists", "confidence": "emerging", "observations": 2},
            ])

        tool, _ = _get_signal_tool()
        result = tool(signal_type="positive", pattern="Use lists")
        assert result["confidence"] == "established"  # 3 observations

    def test_established_to_strong(self, patched_db):
        from backend.database import db

        with db() as conn:
            _insert_user(conn)
            _insert_preference_thing(conn, "t1", [
                {"pattern": "Use lists", "confidence": "established", "observations": 5},
            ])

        tool, _ = _get_signal_tool()
        result = tool(signal_type="positive", pattern="Use lists")
        assert result["confidence"] == "strong"  # 6 observations

    def test_explicit_correction_starts_established(self, patched_db):
        from backend.database import db

        with db() as conn:
            _insert_user(conn)

        tool, _ = _get_signal_tool()
        result = tool(signal_type="explicit_correction", pattern="No jargon")
        assert result["confidence"] == "established"
        assert result["observations"] == 3

    def test_positive_starts_emerging(self, patched_db):
        from backend.database import db

        with db() as conn:
            _insert_user(conn)

        tool, _ = _get_signal_tool()
        result = tool(signal_type="positive", pattern="Likes humor")
        assert result["confidence"] == "emerging"
        assert result["observations"] == 1


# ---------------------------------------------------------------------------
# Multi-pattern scenarios
# ---------------------------------------------------------------------------


class TestMultiPattern:
    def test_updates_correct_pattern_among_many(self, patched_db):
        from backend.database import db

        with db() as conn:
            _insert_user(conn)
            _insert_preference_thing(conn, "t1", [
                {"pattern": "Be concise", "confidence": "strong", "observations": 10},
                {"pattern": "Use lists", "confidence": "emerging", "observations": 2},
                {"pattern": "No emoji", "confidence": "established", "observations": 4},
            ])

        tool, _ = _get_signal_tool()
        result = tool(signal_type="positive", pattern="Use lists")

        assert result["pattern"] == "Use lists"
        assert result["observations"] == 3

        # Verify other patterns unchanged
        with db() as conn:
            row = conn.execute("SELECT data FROM things WHERE id = 't1'").fetchone()
            data = json.loads(row["data"])
            by_name = {p["pattern"]: p for p in data["patterns"]}
            assert by_name["Be concise"]["observations"] == 10
            assert by_name["No emoji"]["observations"] == 4

    def test_pattern_across_multiple_things(self, patched_db):
        from backend.database import db

        with db() as conn:
            _insert_user(conn)
            _insert_preference_thing(conn, "t1", [
                {"pattern": "Be concise", "confidence": "emerging", "observations": 1},
            ])
            _insert_preference_thing(conn, "t2", [
                {"pattern": "Use lists", "confidence": "emerging", "observations": 1},
            ])

        tool, _ = _get_signal_tool()
        result = tool(signal_type="positive", pattern="Use lists")

        assert result["action"] == "updated"
        assert result["thing_id"] == "t2"


# ---------------------------------------------------------------------------
# System prompt integration
# ---------------------------------------------------------------------------


class TestSystemPromptIntegration:
    def test_signal_detection_in_tool_preamble(self):
        from backend.reasoning_agent import REASONING_AGENT_TOOL_SYSTEM

        assert "record_personality_signal" in REASONING_AGENT_TOOL_SYSTEM

    def test_signal_detection_in_planning_prompt(self):
        from backend.reasoning_agent import PLANNING_AGENT_TOOL_SYSTEM

        assert "record_personality_signal" in PLANNING_AGENT_TOOL_SYSTEM

    def test_signal_detection_instructions_present(self):
        from backend.reasoning_agent import REASONING_AGENT_TOOL_SYSTEM

        assert "Personality Signal Detection" in REASONING_AGENT_TOOL_SYSTEM
        assert "explicit_correction" in REASONING_AGENT_TOOL_SYSTEM
        assert "implicit_correction" in REASONING_AGENT_TOOL_SYSTEM

    def test_mode_prompt_includes_signal_tool(self):
        from backend.reasoning_agent import get_system_prompt_for_mode

        for mode in ["normal", "planning"]:
            for style in ["auto", "coach", "consultant"]:
                prompt = get_system_prompt_for_mode(mode, style)
                assert "record_personality_signal" in prompt, (
                    f"Missing record_personality_signal in mode={mode}, style={style}"
                )
