"""Tests for personality preference schema, DB loading, and prompt building."""

import json

import pytest

from backend.agents import (
    _build_personality_overlay,
    get_response_system_prompt,
    load_personality_preferences,
)
from backend.models import PersonalityPattern, PersonalityPreferenceData


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestPersonalityModels:
    def test_pattern_defaults(self):
        p = PersonalityPattern(pattern="Be concise")
        assert p.confidence == "emerging"
        assert p.observations == 1

    def test_pattern_with_all_fields(self):
        p = PersonalityPattern(pattern="Use bullet points", confidence="strong", observations=5)
        assert p.pattern == "Use bullet points"
        assert p.confidence == "strong"
        assert p.observations == 5

    def test_preference_data_empty(self):
        data = PersonalityPreferenceData()
        assert data.patterns == []

    def test_preference_data_with_patterns(self):
        data = PersonalityPreferenceData(
            patterns=[
                PersonalityPattern(pattern="Be direct"),
                PersonalityPattern(pattern="Ask fewer questions", confidence="established"),
            ]
        )
        assert len(data.patterns) == 2
        assert data.patterns[1].confidence == "established"

    def test_pattern_requires_nonempty(self):
        with pytest.raises(Exception):
            PersonalityPattern(pattern="")


# ---------------------------------------------------------------------------
# DB loading
# ---------------------------------------------------------------------------


class TestLoadPersonalityPreferences:
    def test_empty_user_id_returns_empty(self):
        assert load_personality_preferences("") == []

    def test_no_preference_things(self, patched_db):
        result = load_personality_preferences("test-user-123")
        assert result == []

    def test_loads_active_preferences(self, patched_db):
        from backend.database import db

        with db() as conn:
            # Create a user
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )
            # Create a preference thing
            pref_data = json.dumps({
                "patterns": [
                    {"pattern": "Be concise", "confidence": "strong", "observations": 3},
                    {"pattern": "Use examples", "confidence": "emerging"},
                ]
            })
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                ("t1", "Communication Style", "preference", 1, pref_data, "u1"),
            )

        result = load_personality_preferences("u1")
        assert len(result) == 2
        assert result[0]["pattern"] == "Be concise"
        assert result[0]["confidence"] == "strong"
        assert result[0]["observations"] == 3
        assert result[1]["pattern"] == "Use examples"
        assert result[1]["confidence"] == "emerging"
        assert result[1]["observations"] == 1  # default

    def test_inactive_preferences_filtered(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )
            pref_data = json.dumps({"patterns": [{"pattern": "Ignored"}]})
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                ("t1", "Old Pref", "preference", 0, pref_data, "u1"),
            )

        result = load_personality_preferences("u1")
        assert result == []

    def test_multi_thing_aggregation(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )
            for i, pattern in enumerate(["Be direct", "Use lists"]):
                pref_data = json.dumps({"patterns": [{"pattern": pattern}]})
                conn.execute(
                    "INSERT INTO things (id, title, type_hint, active, data, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"t{i}", f"Pref {i}", "preference", 1, pref_data, "u1"),
                )

        result = load_personality_preferences("u1")
        assert len(result) == 2
        patterns = [p["pattern"] for p in result]
        assert "Be direct" in patterns
        assert "Use lists" in patterns

    def test_malformed_data_skipped(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )
            # Thing with malformed JSON data
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                ("t1", "Bad Pref", "preference", 1, "not-json{", "u1"),
            )
            # Thing with valid JSON but no patterns key
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                ("t2", "No Patterns", "preference", 1, json.dumps({"other": "data"}), "u1"),
            )
            # Thing with null data
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                ("t3", "Null Data", "preference", 1, None, "u1"),
            )
            # Thing with valid data
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                ("t4", "Good Pref", "preference", 1, json.dumps({"patterns": [{"pattern": "Valid"}]}), "u1"),
            )

        result = load_personality_preferences("u1")
        assert len(result) == 1
        assert result[0]["pattern"] == "Valid"


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestBuildPersonalityOverlay:
    def test_empty_patterns(self):
        assert _build_personality_overlay([]) == ""

    def test_formatted_output(self):
        patterns = [
            {"pattern": "Be concise", "confidence": "strong"},
            {"pattern": "Use examples", "confidence": "emerging"},
        ]
        result = _build_personality_overlay(patterns)
        assert "Learned Personality Preferences" in result
        assert "[strong] Be concise" in result
        assert "[emerging] Use examples" in result

    def test_all_confidence_levels(self):
        patterns = [
            {"pattern": "A", "confidence": "emerging"},
            {"pattern": "B", "confidence": "established"},
            {"pattern": "C", "confidence": "strong"},
        ]
        result = _build_personality_overlay(patterns)
        assert "[emerging] A" in result
        assert "[established] B" in result
        assert "[strong] C" in result


class TestGetResponseSystemPromptWithPersonality:
    def test_without_patterns(self):
        prompt = get_response_system_prompt("auto")
        assert "Learned Personality Preferences" not in prompt

    def test_with_patterns(self):
        patterns = [{"pattern": "Be terse", "confidence": "strong"}]
        prompt = get_response_system_prompt("auto", personality_patterns=patterns)
        assert "Learned Personality Preferences" in prompt
        assert "[strong] Be terse" in prompt

    def test_coach_style_with_patterns(self):
        patterns = [{"pattern": "Focus on feelings", "confidence": "emerging"}]
        prompt = get_response_system_prompt("coach", personality_patterns=patterns)
        assert "COACHING" in prompt or "coach" in prompt.lower()
        assert "[emerging] Focus on feelings" in prompt

    def test_empty_patterns_no_overlay(self):
        prompt = get_response_system_prompt("auto", personality_patterns=[])
        assert "Learned Personality Preferences" not in prompt


# ---------------------------------------------------------------------------
# Signal detection prompt presence
# ---------------------------------------------------------------------------


class TestSignalDetectionInPrompts:
    """Verify that personality signal detection instructions are present in
    both the tool-calling and legacy reasoning agent system prompts."""

    def test_tool_calling_prompt_has_signal_detection(self):
        from backend.reasoning_agent import REASONING_AGENT_TOOL_SYSTEM

        assert "Personality Signal Detection" in REASONING_AGENT_TOOL_SYSTEM
        assert "POSITIVE signals" in REASONING_AGENT_TOOL_SYSTEM
        assert "NEGATIVE signals" in REASONING_AGENT_TOOL_SYSTEM
        assert "EXPLICIT CORRECTION" in REASONING_AGENT_TOOL_SYSTEM
        assert "IMPLICIT CORRECTION" in REASONING_AGENT_TOOL_SYSTEM

    def test_legacy_prompt_has_signal_detection(self):
        from backend.agents import REASONING_AGENT_SYSTEM

        assert "Personality Signal Detection" in REASONING_AGENT_SYSTEM
        assert "POSITIVE signals" in REASONING_AGENT_SYSTEM
        assert "NEGATIVE signals" in REASONING_AGENT_SYSTEM
        assert "EXPLICIT CORRECTION" in REASONING_AGENT_SYSTEM
        assert "IMPLICIT CORRECTION" in REASONING_AGENT_SYSTEM

    def test_signal_detection_mentions_preference_type(self):
        from backend.reasoning_agent import REASONING_AGENT_TOOL_SYSTEM

        assert 'type_hint="preference"' in REASONING_AGENT_TOOL_SYSTEM
        # Must instruct to use existing preference Things
        assert "fetch_context" in REASONING_AGENT_TOOL_SYSTEM

    def test_confidence_levels_documented(self):
        from backend.reasoning_agent import REASONING_AGENT_TOOL_SYSTEM

        assert '"emerging"' in REASONING_AGENT_TOOL_SYSTEM
        assert '"established"' in REASONING_AGENT_TOOL_SYSTEM
        assert '"strong"' in REASONING_AGENT_TOOL_SYSTEM

    def test_all_modes_include_signal_detection(self):
        from backend.reasoning_agent import get_system_prompt_for_mode

        for mode in ("normal", "planning"):
            for style in ("auto", "coach", "consultant"):
                prompt = get_system_prompt_for_mode(mode, style)
                assert "Personality Signal Detection" in prompt, (
                    f"Signal detection missing from mode={mode}, style={style}"
                )

    def test_over_detection_guard(self):
        """The prompt should warn against over-detecting casual signals."""
        from backend.reasoning_agent import REASONING_AGENT_TOOL_SYSTEM

        assert "over-detect" in REASONING_AGENT_TOOL_SYSTEM.lower()


# ---------------------------------------------------------------------------
# Preference Thing schema for signal storage
# ---------------------------------------------------------------------------


class TestPreferenceThingForSignals:
    """Verify the schema supports storing signal-detected preferences."""

    def test_pattern_confidence_levels(self):
        """All confidence levels from the signal detection spec are valid."""
        for level in ("emerging", "established", "strong"):
            p = PersonalityPattern(pattern="Test pattern", confidence=level)
            assert p.confidence == level

    def test_observations_increment(self):
        """Observations field supports incrementing for repeated signals."""
        p = PersonalityPattern(pattern="Be concise", observations=1)
        # Simulate increment
        p2 = PersonalityPattern(
            pattern=p.pattern,
            confidence=p.confidence,
            observations=p.observations + 1,
        )
        assert p2.observations == 2

    def test_preference_thing_with_signal_patterns(self, patched_db):
        """A preference Thing can store patterns from all signal types."""
        from backend.database import db

        patterns = {
            "patterns": [
                {"pattern": "Prefers concise responses", "confidence": "established", "observations": 5},
                {"pattern": "No emoji", "confidence": "strong", "observations": 1},
                {"pattern": "Likes proactive suggestions", "confidence": "emerging", "observations": 2},
                {"pattern": "Prefers bullet points over prose", "confidence": "emerging", "observations": 2},
            ]
        }

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, surface, user_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("t1", "Communication Style", "preference", 1, json.dumps(patterns), 0, "u1"),
            )

        result = load_personality_preferences("u1")
        assert len(result) == 4
        # Verify confidence levels survived round-trip
        by_pattern = {p["pattern"]: p for p in result}
        assert by_pattern["No emoji"]["confidence"] == "strong"
        assert by_pattern["Prefers concise responses"]["confidence"] == "established"
        assert by_pattern["Prefers concise responses"]["observations"] == 5
