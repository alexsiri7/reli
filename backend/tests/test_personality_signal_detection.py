"""Tests for personality signal detection in the reasoning agent.

Tests the update_personality_preference tool that detects and records
personality/behavior signals from conversations.
"""

import json

import pytest

from backend.reasoning_agent import _make_reasoning_tools


@pytest.fixture()
def reasoning_tools(patched_db):
    """Create reasoning tools bound to a test user with a DB."""
    from backend.database import db

    with db() as conn:
        conn.execute(
            "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
            ("u1", "test@test.com", "g1", "Test User"),
        )

    tools, applied, fetched = _make_reasoning_tools("u1", session_id="test-session")
    # Find the update_personality_preference tool
    pref_tool = None
    for t in tools:
        if t.__wrapped__.__name__ == "update_personality_preference":
            pref_tool = t
            break
    assert pref_tool is not None, "update_personality_preference tool not found"
    return pref_tool, applied


class TestUpdatePersonalityPreferenceValidation:
    """Test input validation for the tool."""

    def test_empty_pattern_rejected(self, reasoning_tools):
        tool, _ = reasoning_tools
        result = tool(signal_type="positive", pattern="")
        assert "error" in result

    def test_invalid_signal_type_rejected(self, reasoning_tools):
        tool, _ = reasoning_tools
        result = tool(signal_type="invalid", pattern="Be concise")
        assert "error" in result

    def test_valid_signal_types_accepted(self, reasoning_tools):
        tool, _ = reasoning_tools
        for signal_type in ["positive", "negative", "explicit_correction", "implicit_correction"]:
            result = tool(signal_type=signal_type, pattern=f"Pattern for {signal_type}")
            assert "error" not in result, f"Signal type '{signal_type}' was rejected"


class TestCreatePreferenceThing:
    """Test creating a new preference Thing when none exists."""

    def test_creates_preference_thing(self, reasoning_tools):
        tool, applied = reasoning_tools
        result = tool(signal_type="positive", pattern="Likes bullet points")
        assert result["status"] == "created"
        assert result["pattern"] == "Likes bullet points"
        assert result["signal_type"] == "positive"
        assert len(applied["created"]) == 1
        thing = applied["created"][0]
        assert thing["type_hint"] == "preference"
        assert thing["title"] == "Communication Preferences"

    def test_created_thing_has_pattern_data(self, reasoning_tools):
        tool, applied = reasoning_tools
        tool(signal_type="explicit_correction", pattern="No emoji")
        thing = applied["created"][0]
        data = json.loads(thing["data"]) if isinstance(thing["data"], str) else thing["data"]
        assert len(data["patterns"]) == 1
        p = data["patterns"][0]
        assert p["pattern"] == "No emoji"
        assert p["confidence"] == "strong"  # explicit_correction → strong
        assert p["observations"] == 1
        assert p["last_signal_type"] == "explicit_correction"

    def test_positive_signal_creates_emerging(self, reasoning_tools):
        tool, applied = reasoning_tools
        tool(signal_type="positive", pattern="Likes examples")
        thing = applied["created"][0]
        data = json.loads(thing["data"]) if isinstance(thing["data"], str) else thing["data"]
        assert data["patterns"][0]["confidence"] == "emerging"

    def test_implicit_correction_creates_established(self, reasoning_tools):
        tool, applied = reasoning_tools
        tool(signal_type="implicit_correction", pattern="User shortens task titles")
        thing = applied["created"][0]
        data = json.loads(thing["data"]) if isinstance(thing["data"], str) else thing["data"]
        assert data["patterns"][0]["confidence"] == "established"

    def test_reasoning_stored(self, reasoning_tools):
        tool, applied = reasoning_tools
        tool(
            signal_type="positive",
            pattern="Likes concise responses",
            reasoning="User said 'perfect, short and sweet'",
        )
        thing = applied["created"][0]
        data = json.loads(thing["data"]) if isinstance(thing["data"], str) else thing["data"]
        assert data["patterns"][0]["last_signal"] == "User said 'perfect, short and sweet'"


class TestUpdateExistingPreference:
    """Test updating an existing preference Thing."""

    def _seed_preference(self, patterns):
        """Insert a preference Thing with given patterns."""
        from backend.database import db

        pref_data = json.dumps({"patterns": patterns})
        with db() as conn:
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, user_id, surface) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("pref-1", "Communication Preferences", "preference", 1, pref_data, "u1", 0),
            )

    def test_updates_existing_preference(self, reasoning_tools):
        self._seed_preference(
            [
                {"pattern": "Be concise", "confidence": "emerging", "observations": 1},
            ]
        )
        tool, applied = reasoning_tools
        result = tool(signal_type="positive", pattern="Be concise")
        assert result["status"] == "updated"
        assert result["thing_id"] == "pref-1"

    def test_increments_observations(self, reasoning_tools):
        self._seed_preference(
            [
                {"pattern": "Be concise", "confidence": "emerging", "observations": 2},
            ]
        )
        tool, applied = reasoning_tools
        tool(signal_type="positive", pattern="Be concise")
        thing = applied["updated"][0]
        data = json.loads(thing["data"]) if isinstance(thing["data"], str) else thing["data"]
        assert data["patterns"][0]["observations"] == 3

    def test_auto_promotes_to_established(self, reasoning_tools):
        self._seed_preference(
            [
                {"pattern": "Use lists", "confidence": "emerging", "observations": 2},
            ]
        )
        tool, _ = reasoning_tools
        # Observation 2 → 3 should promote to "established"
        result = tool(signal_type="positive", pattern="Use lists")
        from backend.database import db

        with db() as conn:
            row = conn.execute("SELECT data FROM things WHERE id = 'pref-1'").fetchone()
        data = json.loads(row["data"])
        assert data["patterns"][0]["confidence"] == "established"
        assert data["patterns"][0]["observations"] == 3

    def test_auto_promotes_to_strong(self, reasoning_tools):
        self._seed_preference(
            [
                {"pattern": "Be direct", "confidence": "established", "observations": 4},
            ]
        )
        tool, _ = reasoning_tools
        # Observation 4 → 5 should promote to "strong"
        result = tool(signal_type="positive", pattern="Be direct")
        from backend.database import db

        with db() as conn:
            row = conn.execute("SELECT data FROM things WHERE id = 'pref-1'").fetchone()
        data = json.loads(row["data"])
        assert data["patterns"][0]["confidence"] == "strong"
        assert data["patterns"][0]["observations"] == 5

    def test_explicit_correction_overrides_confidence(self, reasoning_tools):
        self._seed_preference(
            [
                {"pattern": "No emoji", "confidence": "emerging", "observations": 1},
            ]
        )
        tool, _ = reasoning_tools
        tool(signal_type="explicit_correction", pattern="No emoji")
        from backend.database import db

        with db() as conn:
            row = conn.execute("SELECT data FROM things WHERE id = 'pref-1'").fetchone()
        data = json.loads(row["data"])
        assert data["patterns"][0]["confidence"] == "strong"
        assert data["patterns"][0]["observations"] == 2

    def test_adds_new_pattern_to_existing_thing(self, reasoning_tools):
        self._seed_preference(
            [
                {"pattern": "Be concise", "confidence": "strong", "observations": 5},
            ]
        )
        tool, applied = reasoning_tools
        tool(signal_type="positive", pattern="Use examples")
        thing = applied["updated"][0]
        data = json.loads(thing["data"]) if isinstance(thing["data"], str) else thing["data"]
        assert len(data["patterns"]) == 2
        patterns = {p["pattern"] for p in data["patterns"]}
        assert "Be concise" in patterns
        assert "Use examples" in patterns

    def test_case_insensitive_pattern_match(self, reasoning_tools):
        self._seed_preference(
            [
                {"pattern": "Be Concise", "confidence": "emerging", "observations": 1},
            ]
        )
        tool, _ = reasoning_tools
        tool(signal_type="positive", pattern="be concise")
        from backend.database import db

        with db() as conn:
            row = conn.execute("SELECT data FROM things WHERE id = 'pref-1'").fetchone()
        data = json.loads(row["data"])
        # Should match existing pattern, not create a new one
        assert len(data["patterns"]) == 1
        assert data["patterns"][0]["observations"] == 2


class TestSignalDetectionSystemPrompt:
    """Test that signal detection instructions are in the system prompt."""

    def test_tool_preamble_mentions_tool(self):
        from backend.reasoning_agent import REASONING_AGENT_TOOL_SYSTEM

        assert "update_personality_preference" in REASONING_AGENT_TOOL_SYSTEM

    def test_tool_rules_have_signal_types(self):
        from backend.reasoning_agent import REASONING_AGENT_TOOL_SYSTEM

        assert "POSITIVE signals" in REASONING_AGENT_TOOL_SYSTEM
        assert "NEGATIVE signals" in REASONING_AGENT_TOOL_SYSTEM
        assert "EXPLICIT CORRECTION" in REASONING_AGENT_TOOL_SYSTEM
        assert "IMPLICIT CORRECTION" in REASONING_AGENT_TOOL_SYSTEM

    def test_planning_prompt_includes_tool(self):
        from backend.reasoning_agent import PLANNING_AGENT_TOOL_SYSTEM

        assert "update_personality_preference" in PLANNING_AGENT_TOOL_SYSTEM

    def test_signal_rules_in_prompt(self):
        from backend.reasoning_agent import REASONING_AGENT_TOOL_SYSTEM

        assert "Personality Signal Detection" in REASONING_AGENT_TOOL_SYSTEM
        assert "false positives" in REASONING_AGENT_TOOL_SYSTEM


class TestToolRegistration:
    """Test that the tool is properly registered."""

    def test_tool_in_tools_list(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )
        tools, _, _ = _make_reasoning_tools("u1")
        tool_names = [t.__wrapped__.__name__ for t in tools]
        assert "update_personality_preference" in tool_names

    def test_tool_count(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )
        tools, _, _ = _make_reasoning_tools("u1")
        # 7 original tools + 1 new = 8
        assert len(tools) == 8
