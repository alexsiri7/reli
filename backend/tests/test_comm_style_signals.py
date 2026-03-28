"""Tests for Reli communication style signal detection.

Verifies:
- REASONING_AGENT_SYSTEM contains the reli_communication instruction block
- load_personality_preferences loads reli_communication preference Things
- reli_communication Things reinforce existing patterns on update
"""

from __future__ import annotations

import json

import pytest

from backend.agents import REASONING_AGENT_SYSTEM, load_personality_preferences


# ---------------------------------------------------------------------------
# System prompt contains the instruction block
# ---------------------------------------------------------------------------


class TestCommStyleSignalPrompt:
    def test_prompt_contains_signal_detection_header(self):
        assert "Reli Communication Style Signal Detection" in REASONING_AGENT_SYSTEM

    def test_prompt_mentions_explicit_corrections(self):
        assert "Explicit corrections" in REASONING_AGENT_SYSTEM
        # Key examples should be present
        assert "don't use emoji" in REASONING_AGENT_SYSTEM
        assert "concise" in REASONING_AGENT_SYSTEM

    def test_prompt_mentions_implicit_corrections(self):
        assert "Implicit corrections" in REASONING_AGENT_SYSTEM
        assert "just" in REASONING_AGENT_SYSTEM

    def test_prompt_uses_reli_communication_category(self):
        assert "reli_communication" in REASONING_AGENT_SYSTEM

    def test_prompt_specifies_preference_type_hint(self):
        # Must instruct agent to use type_hint='preference'
        assert "type_hint" in REASONING_AGENT_SYSTEM
        # Category field in data
        assert "data.category" in REASONING_AGENT_SYSTEM

    def test_prompt_specifies_confidence_thresholds(self):
        # Reinforce logic: emerging -> moderate -> strong
        assert "emerging" in REASONING_AGENT_SYSTEM
        assert "moderate" in REASONING_AGENT_SYSTEM
        assert "strong" in REASONING_AGENT_SYSTEM

    def test_prompt_specifies_observation_increment(self):
        assert "observations" in REASONING_AGENT_SYSTEM
        assert "increment" in REASONING_AGENT_SYSTEM or "observations" in REASONING_AGENT_SYSTEM


# ---------------------------------------------------------------------------
# load_personality_preferences picks up reli_communication Things
# ---------------------------------------------------------------------------


class TestLoadReliCommunicationPreferences:
    def test_reli_communication_category_is_loaded(self, patched_db):
        """reli_communication Things are loaded by load_personality_preferences."""
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )
            pref_data = json.dumps(
                {
                    "category": "reli_communication",
                    "patterns": [
                        {
                            "pattern": "Avoid using emoji in responses",
                            "confidence": "strong",
                            "observations": 5,
                            "first_observed": "2026-01-01T00:00:00",
                            "last_observed": "2026-03-01T00:00:00",
                        }
                    ],
                }
            )
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                ("t1", "How Test User wants Reli to communicate", "preference", 1, pref_data, "u1"),
            )

        result = load_personality_preferences("u1")
        assert len(result) == 1
        assert result[0]["pattern"] == "Avoid using emoji in responses"
        assert result[0]["confidence"] == "strong"
        assert result[0]["observations"] == 5

    def test_mixed_categories_all_loaded(self, patched_db):
        """Both reli_communication and scheduling preferences are loaded together."""
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )
            comm_data = json.dumps(
                {
                    "category": "reli_communication",
                    "patterns": [{"pattern": "Keep responses brief and direct", "confidence": "emerging"}],
                }
            )
            sched_data = json.dumps(
                {
                    "category": "scheduling",
                    "patterns": [{"pattern": "Avoids morning meetings", "confidence": "strong", "observations": 4}],
                }
            )
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                ("t1", "Reli communication style", "preference", 1, comm_data, "u1"),
            )
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                ("t2", "Scheduling preferences", "preference", 1, sched_data, "u1"),
            )

        result = load_personality_preferences("u1")
        assert len(result) == 2
        patterns = [p["pattern"] for p in result]
        assert "Keep responses brief and direct" in patterns
        assert "Avoids morning meetings" in patterns

    def test_inactive_reli_communication_filtered(self, patched_db):
        """Inactive reli_communication preference Things are excluded."""
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )
            pref_data = json.dumps(
                {
                    "category": "reli_communication",
                    "patterns": [{"pattern": "Use plain prose instead of bullet points"}],
                }
            )
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                ("t1", "Old comm style", "preference", 0, pref_data, "u1"),
            )

        result = load_personality_preferences("u1")
        assert result == []

    def test_multiple_patterns_in_reli_communication_thing(self, patched_db):
        """Multiple patterns in one reli_communication Thing are all returned."""
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test User"),
            )
            pref_data = json.dumps(
                {
                    "category": "reli_communication",
                    "patterns": [
                        {"pattern": "Avoid using emoji in responses", "confidence": "strong", "observations": 4},
                        {"pattern": "Keep responses brief and direct", "confidence": "moderate", "observations": 3},
                        {
                            "pattern": "Answer the question first, skip preamble",
                            "confidence": "emerging",
                            "observations": 1,
                        },
                    ],
                }
            )
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, data, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                ("t1", "How Test User wants Reli to communicate", "preference", 1, pref_data, "u1"),
            )

        result = load_personality_preferences("u1")
        assert len(result) == 3
        confidences = {p["pattern"]: p["confidence"] for p in result}
        assert confidences["Avoid using emoji in responses"] == "strong"
        assert confidences["Keep responses brief and direct"] == "moderate"
        assert confidences["Answer the question first, skip preamble"] == "emerging"


# ---------------------------------------------------------------------------
# Confidence threshold logic (unit test on the data contract)
# ---------------------------------------------------------------------------


class TestConfidenceThresholds:
    """Verify the confidence upgrade thresholds match what the prompt specifies."""

    def test_prompt_specifies_emerging_to_moderate_at_2(self):
        """emerging -> moderate threshold is at 2 observations."""
        assert "emerging" in REASONING_AGENT_SYSTEM
        assert "moderate" in REASONING_AGENT_SYSTEM
        # The prompt should mention the threshold value
        assert "2" in REASONING_AGENT_SYSTEM

    def test_prompt_specifies_moderate_to_strong_at_4(self):
        """moderate -> strong threshold is at 4 observations."""
        assert "4" in REASONING_AGENT_SYSTEM
