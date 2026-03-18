"""Tests for interaction style preference learning."""

from fastapi.testclient import TestClient

from backend.database import db
from backend.interaction_style import (
    DIMENSIONS,
    analyze_chat_history,
    build_style_instruction,
    get_effective_style,
    get_style_preferences,
    set_manual_override,
)


def _create_user(user_id: str = "test-user") -> str:
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
            (user_id, f"{user_id}@test.com", f"g-{user_id}", "Test User"),
        )
    return user_id


def _insert_messages(user_id: str, messages: list[tuple[str, str]]) -> None:
    """Insert (role, content) pairs into chat_history."""
    with db() as conn:
        for role, content in messages:
            conn.execute(
                "INSERT INTO chat_history (session_id, role, content, user_id) VALUES (?, ?, ?, ?)",
                ("test-session", role, content, user_id),
            )


class TestStylePreferences:
    def test_default_preferences(self, patched_db):
        prefs = get_style_preferences("")
        for dim in DIMENSIONS:
            assert prefs[dim]["value"] == 0.5
            assert prefs[dim]["manual_override"] is None
            assert prefs[dim]["sample_count"] == 0

    def test_get_preferences_no_data(self, patched_db):
        uid = _create_user()
        prefs = get_style_preferences(uid)
        for dim in DIMENSIONS:
            assert prefs[dim]["value"] == 0.5

    def test_set_manual_override(self, patched_db):
        uid = _create_user()
        set_manual_override(uid, "verbosity", 0.8)
        prefs = get_style_preferences(uid)
        assert prefs["verbosity"]["manual_override"] == 0.8
        assert prefs["verbosity"]["value"] == 0.8

    def test_clear_manual_override(self, patched_db):
        uid = _create_user()
        set_manual_override(uid, "verbosity", 0.8)
        set_manual_override(uid, "verbosity", None)
        prefs = get_style_preferences(uid)
        assert prefs["verbosity"]["manual_override"] is None

    def test_effective_style(self, patched_db):
        uid = _create_user()
        style = get_effective_style(uid)
        assert set(style.keys()) == set(DIMENSIONS)
        assert all(0.0 <= v <= 1.0 for v in style.values())


class TestStyleAnalysis:
    def test_analyze_insufficient_data(self, patched_db):
        uid = _create_user()
        _insert_messages(uid, [("user", "hello"), ("assistant", "hi")])
        prefs = analyze_chat_history(uid)
        # Should return defaults with 0 sample_count (not enough data)
        assert prefs["coaching_vs_consulting"]["sample_count"] == 0

    def test_analyze_directive_messages(self, patched_db):
        uid = _create_user()
        msgs = [("user", f"Create task number {i}") for i in range(10)]
        msgs += [("assistant", f"Done! Task {i} created.") for i in range(10)]
        _insert_messages(uid, msgs)
        prefs = analyze_chat_history(uid)
        # Directive messages should push coaching_vs_consulting toward 1.0 (consulting)
        assert prefs["coaching_vs_consulting"]["sample_count"] == 10
        assert prefs["coaching_vs_consulting"]["learned_value"] > 0.5

    def test_analyze_coaching_messages(self, patched_db):
        uid = _create_user()
        msgs = [("user", f"What do you think about option {i}? How should I approach this?") for i in range(10)]
        msgs += [("assistant", f"Here's what I think about {i}...") for i in range(10)]
        _insert_messages(uid, msgs)
        prefs = analyze_chat_history(uid)
        assert prefs["coaching_vs_consulting"]["learned_value"] < 0.5

    def test_analyze_brief_messages(self, patched_db):
        uid = _create_user()
        msgs = [("user", "ok"), ("user", "yes"), ("user", "done")] * 5
        _insert_messages(uid, msgs)
        prefs = analyze_chat_history(uid)
        assert prefs["verbosity"]["learned_value"] < 0.3

    def test_manual_override_preserved_after_analysis(self, patched_db):
        uid = _create_user()
        set_manual_override(uid, "formality", 0.9)
        msgs = [("user", f"hey lol task {i}") for i in range(10)]
        _insert_messages(uid, msgs)
        prefs = analyze_chat_history(uid)
        # Manual override should still be effective
        assert prefs["formality"]["manual_override"] == 0.9
        assert prefs["formality"]["value"] == 0.9


class TestBuildStyleInstruction:
    def test_neutral_returns_empty(self):
        style = {"coaching_vs_consulting": 0.5, "verbosity": 0.5, "formality": 0.5}
        assert build_style_instruction(style) == ""

    def test_coaching_instruction(self):
        style = {"coaching_vs_consulting": 0.2, "verbosity": 0.5, "formality": 0.5}
        result = build_style_instruction(style)
        assert "coaching" in result.lower()

    def test_consulting_instruction(self):
        style = {"coaching_vs_consulting": 0.8, "verbosity": 0.5, "formality": 0.5}
        result = build_style_instruction(style)
        assert "consulting" in result.lower()

    def test_brief_instruction(self):
        style = {"coaching_vs_consulting": 0.5, "verbosity": 0.2, "formality": 0.5}
        result = build_style_instruction(style)
        assert "brief" in result.lower()

    def test_detailed_instruction(self):
        style = {"coaching_vs_consulting": 0.5, "verbosity": 0.8, "formality": 0.5}
        result = build_style_instruction(style)
        assert "detailed" in result.lower()

    def test_casual_instruction(self):
        style = {"coaching_vs_consulting": 0.5, "verbosity": 0.5, "formality": 0.2}
        result = build_style_instruction(style)
        assert "casual" in result.lower()

    def test_formal_instruction(self):
        style = {"coaching_vs_consulting": 0.5, "verbosity": 0.5, "formality": 0.8}
        result = build_style_instruction(style)
        assert "professional" in result.lower()


class TestInteractionStyleAPI:
    def test_get_preferences(self, client: TestClient):
        resp = client.get("/api/interaction-style")
        assert resp.status_code == 200
        data = resp.json()
        assert "coaching_vs_consulting" in data
        assert "verbosity" in data
        assert "formality" in data

    def test_set_override_no_auth(self, client: TestClient):
        """Without auth (empty user_id), override is a no-op but returns 200."""
        resp = client.put(
            "/api/interaction-style",
            json={"dimension": "verbosity", "value": 0.8},
        )
        assert resp.status_code == 200
        data = resp.json()
        # No auth = defaults returned (override not persisted)
        assert data["verbosity"]["value"] == 0.5

    def test_set_and_clear_override(self, patched_db):
        """With a real user, override is persisted and can be cleared."""
        uid = _create_user("api-user")
        set_manual_override(uid, "verbosity", 0.8)
        prefs = get_style_preferences(uid)
        assert prefs["verbosity"]["manual_override"] == 0.8
        assert prefs["verbosity"]["value"] == 0.8

        set_manual_override(uid, "verbosity", None)
        prefs = get_style_preferences(uid)
        assert prefs["verbosity"]["manual_override"] is None

    def test_invalid_dimension(self, client: TestClient):
        resp = client.put(
            "/api/interaction-style",
            json={"dimension": "invalid", "value": 0.5},
        )
        assert resp.status_code == 400

    def test_analyze_endpoint(self, client: TestClient):
        resp = client.post("/api/interaction-style/analyze")
        assert resp.status_code == 200
        data = resp.json()
        assert "coaching_vs_consulting" in data
