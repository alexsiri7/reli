"""Tests for personality preference schema, DB loading, prompt building, and signal detection."""

import json

import pytest

from backend.agents import (
    _build_personality_overlay,
    get_response_system_prompt,
    load_personality_preferences,
)
from backend.models import PersonalityPattern, PersonalityPreferenceData
from backend.reasoning_agent import _make_reasoning_tools


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
# Signal detection tool
# ---------------------------------------------------------------------------


def _get_signal_tool(user_id: str, patched_db):
    """Helper to extract the detect_personality_signal tool from reasoning tools."""
    from backend.database import db

    with db() as conn:
        conn.execute(
            "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
            (user_id, "test@test.com", "g1", "Test User"),
        )

    tools, applied, fetched = _make_reasoning_tools(user_id)
    # The detect_personality_signal tool is the last one
    signal_tool = None
    for t in tools:
        if t.__name__ == "detect_personality_signal":
            signal_tool = t
            break
    assert signal_tool is not None, "detect_personality_signal tool not found"
    return signal_tool, applied


class TestDetectPersonalitySignal:
    def test_explicit_correction_creates_preference(self, patched_db):
        tool, applied = _get_signal_tool("u1", patched_db)
        result = tool(
            signal_type="explicit_correction",
            pattern="No emoji in messages",
            reasoning="User said 'don't use emoji'",
        )
        assert result["status"] == "created"
        assert result["signal_type"] == "explicit_correction"
        assert result["pattern"] == "No emoji in messages"
        assert result["preference_thing_id"] is not None

        # Verify the preference Thing was created
        patterns = load_personality_preferences("u1")
        assert len(patterns) == 1
        assert patterns[0]["pattern"] == "No emoji in messages"
        assert patterns[0]["confidence"] == "established"  # boost=3 → established
        assert patterns[0]["observations"] == 3

    def test_positive_signal_creates_emerging(self, patched_db):
        tool, applied = _get_signal_tool("u1", patched_db)
        result = tool(
            signal_type="positive",
            pattern="Likes proactive suggestions",
            reasoning="User followed a suggestion",
        )
        assert result["status"] == "created"

        patterns = load_personality_preferences("u1")
        assert len(patterns) == 1
        assert patterns[0]["confidence"] == "emerging"  # boost=1
        assert patterns[0]["observations"] == 1

    def test_repeated_signals_strengthen_confidence(self, patched_db):
        tool, applied = _get_signal_tool("u1", patched_db)

        # First signal
        tool(signal_type="positive", pattern="Prefers concise responses")

        # Second signal
        result = tool(signal_type="positive", pattern="Prefers concise responses")
        assert result["status"] == "strengthened"

        patterns = load_personality_preferences("u1")
        assert len(patterns) == 1
        assert patterns[0]["observations"] == 2
        assert patterns[0]["confidence"] == "emerging"

        # Third signal → established
        tool(signal_type="positive", pattern="Prefers concise responses")
        patterns = load_personality_preferences("u1")
        assert patterns[0]["observations"] == 3
        assert patterns[0]["confidence"] == "established"

        # Two more → strong
        tool(signal_type="positive", pattern="Prefers concise responses")
        tool(signal_type="positive", pattern="Prefers concise responses")
        patterns = load_personality_preferences("u1")
        assert patterns[0]["observations"] == 5
        assert patterns[0]["confidence"] == "strong"

    def test_negative_signal_weakens(self, patched_db):
        tool, applied = _get_signal_tool("u1", patched_db)

        # Create a pattern with some observations
        tool(signal_type="explicit_correction", pattern="Prefers concise responses")
        patterns = load_personality_preferences("u1")
        assert patterns[0]["observations"] == 3  # explicit_correction boost=3

        # Negative signal weakens it
        result = tool(signal_type="negative", pattern="Prefers concise responses")
        assert result["status"] == "weakened"

        patterns = load_personality_preferences("u1")
        assert patterns[0]["observations"] == 2  # 3 - 1

    def test_negative_for_unknown_pattern_skips(self, patched_db):
        tool, applied = _get_signal_tool("u1", patched_db)
        result = tool(
            signal_type="negative",
            pattern="Unknown pattern",
        )
        assert result["status"] == "skipped"

    def test_implicit_correction_medium_boost(self, patched_db):
        tool, applied = _get_signal_tool("u1", patched_db)
        result = tool(
            signal_type="implicit_correction",
            pattern="Prefers shorter Thing titles",
            reasoning="User shortened 3 titles created by Reli",
        )
        assert result["status"] == "created"

        patterns = load_personality_preferences("u1")
        assert len(patterns) == 1
        assert patterns[0]["observations"] == 2  # implicit boost=2
        assert patterns[0]["confidence"] == "emerging"

    def test_invalid_signal_type(self, patched_db):
        tool, applied = _get_signal_tool("u1", patched_db)
        result = tool(signal_type="invalid", pattern="test")
        assert "error" in result

    def test_empty_pattern_rejected(self, patched_db):
        tool, applied = _get_signal_tool("u1", patched_db)
        result = tool(signal_type="positive", pattern="  ")
        assert "error" in result

    def test_multiple_patterns_coexist(self, patched_db):
        tool, applied = _get_signal_tool("u1", patched_db)
        tool(signal_type="explicit_correction", pattern="No emoji")
        tool(signal_type="positive", pattern="Likes bullet points")

        patterns = load_personality_preferences("u1")
        assert len(patterns) == 2
        pattern_texts = {p["pattern"] for p in patterns}
        assert "No emoji" in pattern_texts
        assert "Likes bullet points" in pattern_texts

    def test_case_insensitive_matching(self, patched_db):
        tool, applied = _get_signal_tool("u1", patched_db)
        tool(signal_type="positive", pattern="Be concise")
        tool(signal_type="positive", pattern="be concise")

        patterns = load_personality_preferences("u1")
        assert len(patterns) == 1
        assert patterns[0]["observations"] == 2

    def test_uses_existing_preference_thing(self, patched_db):
        """When a preference Thing already exists, new signals update it."""
        from backend.database import db

        # Pre-create a preference Thing
        pref_data = json.dumps({
            "patterns": [
                {"pattern": "Be direct", "confidence": "established", "observations": 4}
            ]
        })
        with db() as conn:
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, user_id)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("existing-pref", "My Prefs", "preference", 1, pref_data, "u1"),
            )

        tool, applied = _get_signal_tool("u1", patched_db)
        result = tool(signal_type="positive", pattern="Likes examples")
        assert result["status"] == "created"
        assert result["preference_thing_id"] == "existing-pref"

        # Both patterns should be in the same Thing
        patterns = load_personality_preferences("u1")
        assert len(patterns) == 2

    def test_observations_never_below_one(self, patched_db):
        tool, applied = _get_signal_tool("u1", patched_db)

        # Create with minimum observations
        tool(signal_type="positive", pattern="Test pattern")
        patterns = load_personality_preferences("u1")
        assert patterns[0]["observations"] == 1

        # Negative can't go below 1
        tool(signal_type="negative", pattern="Test pattern")
        patterns = load_personality_preferences("u1")
        assert patterns[0]["observations"] == 1


class TestSignalDetectionInSystemPrompt:
    def test_normal_mode_includes_signal_instructions(self):
        from backend.reasoning_agent import get_system_prompt_for_mode

        prompt = get_system_prompt_for_mode("normal")
        assert "detect_personality_signal" in prompt
        assert "Personality Signal Detection" in prompt

    def test_planning_mode_includes_signal_tool(self):
        from backend.reasoning_agent import get_system_prompt_for_mode

        prompt = get_system_prompt_for_mode("planning")
        assert "detect_personality_signal" in prompt
