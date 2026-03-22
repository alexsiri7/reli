"""Tests for personality signal detection and preference backpropagation."""

import json

from backend.signal_detector import (
    _CONFIDENCE_THRESHOLDS,
    _PREFERENCE_THING_TITLE,
    _compute_confidence,
    _find_preference_thing,
    _load_existing_patterns,
    _match_existing_pattern,
    apply_signals,
)

# ---------------------------------------------------------------------------
# Unit tests — confidence computation
# ---------------------------------------------------------------------------


class TestComputeConfidence:
    def test_zero_observations_is_emerging(self):
        assert _compute_confidence(0) == "emerging"

    def test_below_established_threshold(self):
        assert _compute_confidence(4) == "emerging"

    def test_at_established_threshold(self):
        assert _compute_confidence(_CONFIDENCE_THRESHOLDS["established"]) == "established"

    def test_between_established_and_strong(self):
        assert _compute_confidence(8) == "established"

    def test_at_strong_threshold(self):
        assert _compute_confidence(_CONFIDENCE_THRESHOLDS["strong"]) == "strong"

    def test_above_strong_threshold(self):
        assert _compute_confidence(100) == "strong"


# ---------------------------------------------------------------------------
# Unit tests — pattern matching
# ---------------------------------------------------------------------------


class TestMatchExistingPattern:
    def test_matches_by_dimension(self):
        existing = [
            {"pattern": "Be concise", "dimension": "response_length"},
            {"pattern": "Use bullet points", "dimension": "structure"},
        ]
        idx = _match_existing_pattern(existing, "Keep responses short", "response_length")
        assert idx == 0

    def test_matches_by_exact_text(self):
        existing = [
            {"pattern": "No emoji", "dimension": "emoji"},
        ]
        idx = _match_existing_pattern(existing, "No emoji", "different_dim")
        assert idx == 0

    def test_no_match_returns_none(self):
        existing = [
            {"pattern": "Be concise", "dimension": "response_length"},
        ]
        idx = _match_existing_pattern(existing, "Use headers", "structure")
        assert idx is None

    def test_empty_existing_returns_none(self):
        idx = _match_existing_pattern([], "Anything", "any")
        assert idx is None

    def test_case_insensitive_text_match(self):
        existing = [{"pattern": "NO EMOJI", "dimension": "emoji"}]
        idx = _match_existing_pattern(existing, "no emoji", "other")
        assert idx == 0


# ---------------------------------------------------------------------------
# Unit tests — load existing patterns
# ---------------------------------------------------------------------------


class TestLoadExistingPatterns:
    def test_valid_data(self):
        thing = {"data": json.dumps({"patterns": [{"pattern": "Be brief"}]})}
        patterns = _load_existing_patterns(thing)
        assert len(patterns) == 1
        assert patterns[0]["pattern"] == "Be brief"

    def test_null_data(self):
        assert _load_existing_patterns({"data": None}) == []

    def test_malformed_json(self):
        assert _load_existing_patterns({"data": "not-json{"}) == []

    def test_no_patterns_key(self):
        assert _load_existing_patterns({"data": json.dumps({"other": 1})}) == []

    def test_filters_invalid_entries(self):
        thing = {
            "data": json.dumps(
                {
                    "patterns": [
                        {"pattern": "Valid"},
                        "not a dict",
                        {"no_pattern_key": True},
                    ]
                }
            )
        }
        patterns = _load_existing_patterns(thing)
        assert len(patterns) == 1
        assert patterns[0]["pattern"] == "Valid"


# ---------------------------------------------------------------------------
# Integration tests — apply_signals
# ---------------------------------------------------------------------------


class TestApplySignals:
    def test_empty_signals(self):
        result = apply_signals([], "user-1")
        assert result == {"updated": 0, "created": 0}

    def test_empty_user_id(self):
        result = apply_signals([{"type": "positive", "pattern": "x", "direction": "strengthen"}], "")
        assert result == {"updated": 0, "created": 0}

    def test_creates_preference_thing(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test"),
            )

        signals = [
            {
                "type": "explicit_correction",
                "pattern": "No emoji in responses",
                "dimension": "emoji",
                "direction": "strengthen",
                "confidence": "high",
            }
        ]

        result = apply_signals(signals, "u1")
        assert result["created"] == 1
        assert result["updated"] == 0

        # Verify the Thing was created
        pref = _find_preference_thing("u1")
        assert pref is not None
        assert pref["title"] == _PREFERENCE_THING_TITLE
        assert pref["type_hint"] == "preference"

        patterns = _load_existing_patterns(pref)
        assert len(patterns) == 1
        assert patterns[0]["pattern"] == "No emoji in responses"
        assert patterns[0]["dimension"] == "emoji"
        assert patterns[0]["observations"] == 3  # explicit_correction + high = 3

    def test_updates_existing_pattern(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test"),
            )
            pref_data = json.dumps(
                {
                    "patterns": [
                        {
                            "pattern": "Be concise",
                            "dimension": "response_length",
                            "confidence": "emerging",
                            "observations": 2,
                        },
                    ]
                }
            )
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, surface, data, user_id) "
                "VALUES (?, ?, 'preference', 1, 0, ?, ?)",
                ("pref-1", _PREFERENCE_THING_TITLE, pref_data, "u1"),
            )

        signals = [
            {
                "type": "positive",
                "pattern": "Prefers short responses",
                "dimension": "response_length",
                "direction": "strengthen",
                "confidence": "high",
            }
        ]

        result = apply_signals(signals, "u1")
        assert result["updated"] == 1
        assert result["created"] == 0

        pref = _find_preference_thing("u1")
        patterns = _load_existing_patterns(pref)
        assert len(patterns) == 1
        assert patterns[0]["observations"] == 4  # was 2, +2 for positive/high
        assert patterns[0]["pattern"] == "Prefers short responses"  # updated text

    def test_weaken_reduces_observations(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test"),
            )
            pref_data = json.dumps(
                {
                    "patterns": [
                        {
                            "pattern": "Use bullet points",
                            "dimension": "structure",
                            "confidence": "established",
                            "observations": 6,
                        },
                    ]
                }
            )
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, surface, data, user_id) "
                "VALUES (?, ?, 'preference', 1, 0, ?, ?)",
                ("pref-1", _PREFERENCE_THING_TITLE, pref_data, "u1"),
            )

        signals = [
            {
                "type": "negative",
                "pattern": "Dislikes bullet points",
                "dimension": "structure",
                "direction": "weaken",
                "confidence": "high",
            }
        ]

        result = apply_signals(signals, "u1")
        assert result["updated"] == 1

        pref = _find_preference_thing("u1")
        patterns = _load_existing_patterns(pref)
        assert len(patterns) == 1
        assert patterns[0]["observations"] == 4  # was 6, -2 for negative/high

    def test_weaken_to_zero_removes_pattern(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test"),
            )
            pref_data = json.dumps(
                {
                    "patterns": [
                        {
                            "pattern": "Use headers",
                            "dimension": "structure",
                            "confidence": "emerging",
                            "observations": 1,
                        },
                    ]
                }
            )
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, surface, data, user_id) "
                "VALUES (?, ?, 'preference', 1, 0, ?, ?)",
                ("pref-1", _PREFERENCE_THING_TITLE, pref_data, "u1"),
            )

        signals = [
            {
                "type": "negative",
                "pattern": "Stop using headers",
                "dimension": "structure",
                "direction": "weaken",
                "confidence": "medium",
            }
        ]

        result = apply_signals(signals, "u1")
        assert result["updated"] == 1

        pref = _find_preference_thing("u1")
        patterns = _load_existing_patterns(pref)
        assert len(patterns) == 0  # pattern removed when observations hit 0

    def test_weaken_nonexistent_pattern_skipped(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test"),
            )

        signals = [
            {
                "type": "negative",
                "pattern": "No such pattern",
                "dimension": "unknown",
                "direction": "weaken",
                "confidence": "high",
            }
        ]

        result = apply_signals(signals, "u1")
        assert result["created"] == 0
        assert result["updated"] == 0

    def test_multiple_signals_one_call(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test"),
            )

        signals = [
            {
                "type": "explicit_correction",
                "pattern": "No emoji",
                "dimension": "emoji",
                "direction": "strengthen",
                "confidence": "high",
            },
            {
                "type": "positive",
                "pattern": "Likes concise responses",
                "dimension": "response_length",
                "direction": "strengthen",
                "confidence": "medium",
            },
        ]

        result = apply_signals(signals, "u1")
        assert result["created"] == 2

        pref = _find_preference_thing("u1")
        patterns = _load_existing_patterns(pref)
        assert len(patterns) == 2
        dims = {p["dimension"] for p in patterns}
        assert "emoji" in dims
        assert "response_length" in dims

    def test_confidence_upgrades_with_observations(self, patched_db):
        from backend.database import db

        with db() as conn:
            conn.execute(
                "INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
                ("u1", "test@test.com", "g1", "Test"),
            )
            pref_data = json.dumps(
                {
                    "patterns": [
                        {"pattern": "Be direct", "dimension": "formality", "confidence": "emerging", "observations": 4},
                    ]
                }
            )
            conn.execute(
                "INSERT INTO things (id, title, type_hint, active, surface, data, user_id) "
                "VALUES (?, ?, 'preference', 1, 0, ?, ?)",
                ("pref-1", _PREFERENCE_THING_TITLE, pref_data, "u1"),
            )

        # Add 2 more observations → total 6 → should upgrade to "established"
        signals = [
            {
                "type": "positive",
                "pattern": "Direct communication",
                "dimension": "formality",
                "direction": "strengthen",
                "confidence": "high",
            }
        ]

        apply_signals(signals, "u1")

        pref = _find_preference_thing("u1")
        patterns = _load_existing_patterns(pref)
        assert patterns[0]["observations"] == 6
        assert patterns[0]["confidence"] == "established"
