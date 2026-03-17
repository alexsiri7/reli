"""Tests for the meta-learning pattern detection and learning storage."""

import json
from datetime import datetime, timedelta, timezone

from backend.database import db
from backend.meta_learning import (  # noqa: I001
    MIN_OBSERVATIONS,
    PatternCandidate,
    _save_candidates_directly,
    _upsert_learning,
    collect_pattern_candidates,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_thing(conn, thing_id, title, *, type_hint=None, user_id=None, created_at=None):
    now = (created_at or datetime.now(timezone.utc)).isoformat()
    conn.execute(
        """INSERT INTO things (id, title, type_hint, active, surface, created_at, updated_at, user_id)
           VALUES (?, ?, ?, 1, 1, ?, ?, ?)""",
        (thing_id, title, type_hint, now, now, user_id),
    )


def _insert_chat(conn, session_id, role, content, *, user_id=None, timestamp=None, applied_changes=None):
    ts = (timestamp or datetime.now(timezone.utc)).isoformat()
    conn.execute(
        """INSERT INTO chat_history (session_id, role, content, timestamp, user_id, applied_changes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, role, content, ts, user_id, json.dumps(applied_changes) if applied_changes else None),
    )


def _get_learnings(conn):
    return conn.execute("SELECT * FROM learnings ORDER BY created_at").fetchall()


# ---------------------------------------------------------------------------
# Thing type pattern detection
# ---------------------------------------------------------------------------


class TestThingTypePatterns:
    def test_detects_frequent_type(self, patched_db):
        with db() as conn:
            for i in range(MIN_OBSERVATIONS + 1):
                _insert_thing(conn, f"t{i}", f"Task {i}", type_hint="task")
        candidates = collect_pattern_candidates()
        type_candidates = [c for c in candidates if c.category == "thing_type"]
        assert len(type_candidates) >= 1
        assert any("task" in c.title.lower() for c in type_candidates)

    def test_below_threshold_excluded(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "One task", type_hint="task")
            _insert_thing(conn, "t2", "Two task", type_hint="task")
        candidates = collect_pattern_candidates()
        type_candidates = [c for c in candidates if c.category == "thing_type"]
        assert len(type_candidates) == 0

    def test_null_type_hint_excluded(self, patched_db):
        with db() as conn:
            for i in range(5):
                _insert_thing(conn, f"t{i}", f"No type {i}")
        candidates = collect_pattern_candidates()
        type_candidates = [c for c in candidates if c.category == "thing_type"]
        assert len(type_candidates) == 0


# ---------------------------------------------------------------------------
# Session frequency (temporal) patterns
# ---------------------------------------------------------------------------


class TestTemporalPatterns:
    def test_detects_active_hour(self, patched_db):
        with db() as conn:
            base = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0)
            for i in range(MIN_OBSERVATIONS + 1):
                ts = base + timedelta(minutes=i * 5)
                _insert_chat(conn, f"s{i}", "user", f"msg {i}", timestamp=ts)
        candidates = collect_pattern_candidates()
        temporal = [c for c in candidates if c.category == "temporal"]
        assert len(temporal) >= 1

    def test_below_threshold_excluded(self, patched_db):
        with db() as conn:
            base = datetime.now(timezone.utc).replace(hour=14, minute=0)
            for i in range(2):
                _insert_chat(conn, f"s{i}", "user", f"msg {i}", timestamp=base + timedelta(minutes=i))
        candidates = collect_pattern_candidates()
        temporal = [c for c in candidates if c.category == "temporal"]
        assert len(temporal) == 0


# ---------------------------------------------------------------------------
# Topic patterns (from applied_changes)
# ---------------------------------------------------------------------------


class TestTopicPatterns:
    def test_detects_creation_pattern(self, patched_db):
        with db() as conn:
            for i in range(MIN_OBSERVATIONS + 1):
                changes = {"created": [{"id": f"t{i}", "title": f"Note {i}", "type_hint": "note"}]}
                _insert_chat(conn, f"s{i}", "assistant", f"Created note {i}", applied_changes=changes)
        candidates = collect_pattern_candidates()
        topic = [c for c in candidates if c.category == "topic"]
        assert any("note" in c.title.lower() for c in topic)

    def test_detects_update_pattern(self, patched_db):
        with db() as conn:
            for i in range(MIN_OBSERVATIONS + 1):
                changes = {"updated": [{"id": f"t{i}", "title": f"Task {i}", "type_hint": "task"}]}
                _insert_chat(conn, f"s{i}", "assistant", f"Updated task {i}", applied_changes=changes)
        candidates = collect_pattern_candidates()
        workflow = [c for c in candidates if c.category == "workflow"]
        assert any("task" in c.title.lower() for c in workflow)


# ---------------------------------------------------------------------------
# Session length patterns
# ---------------------------------------------------------------------------


class TestSessionLengthPatterns:
    def test_detects_short_session_pattern(self, patched_db):
        with db() as conn:
            for i in range(MIN_OBSERVATIONS + 2):
                _insert_chat(conn, f"s{i}", "user", f"quick msg {i}")
        candidates = collect_pattern_candidates()
        workflow = [c for c in candidates if c.category == "workflow"]
        assert any("quick" in c.title.lower() or "brief" in c.title.lower() or "focused" in c.title.lower()
                    for c in workflow)

    def test_detects_long_session_pattern(self, patched_db):
        with db() as conn:
            for sess in range(MIN_OBSERVATIONS + 2):
                for msg in range(6):
                    _insert_chat(conn, f"s{sess}", "user", f"msg {msg} in session {sess}")
        candidates = collect_pattern_candidates()
        workflow = [c for c in candidates if c.category == "workflow"]
        assert any("extended" in c.title.lower() or "conversation" in c.title.lower()
                    for c in workflow)


# ---------------------------------------------------------------------------
# Learning upsert
# ---------------------------------------------------------------------------


class TestUpsertLearning:
    def test_creates_new_learning(self, patched_db):
        with db() as conn:
            lid, is_new = _upsert_learning(
                conn, "", "Test pattern", "A description", "workflow", 0.7, ["evidence1"]
            )
        assert is_new is True
        assert lid.startswith("lr-")
        with db() as conn:
            rows = _get_learnings(conn)
        assert len(rows) == 1
        assert rows[0]["title"] == "Test pattern"
        assert rows[0]["observation_count"] == 1

    def test_updates_existing_same_category(self, patched_db):
        with db() as conn:
            lid1, _ = _upsert_learning(conn, "", "Pattern A", "Desc A", "workflow", 0.6, ["ev1"])
        with db() as conn:
            lid2, is_new = _upsert_learning(conn, "", "Pattern A updated", "Desc B", "workflow", 0.8, ["ev2"])
        assert is_new is False
        assert lid2 == lid1
        with db() as conn:
            rows = _get_learnings(conn)
        assert len(rows) == 1
        assert rows[0]["observation_count"] == 2
        assert rows[0]["confidence"] == 0.8

    def test_different_category_creates_new(self, patched_db):
        with db() as conn:
            _upsert_learning(conn, "", "Pattern", "Desc", "workflow", 0.6, ["ev1"])
        with db() as conn:
            _, is_new = _upsert_learning(conn, "", "Pattern", "Desc", "temporal", 0.6, ["ev2"])
        assert is_new is True
        with db() as conn:
            rows = _get_learnings(conn)
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# Save candidates directly (LLM fallback)
# ---------------------------------------------------------------------------


class TestSaveCandidatesDirectly:
    def test_saves_high_confidence_candidates(self, patched_db):
        from backend.meta_learning import MetaLearningResult

        candidates = [
            PatternCandidate("Good pattern", "Desc", "workflow", 5, 0.7, ["ev"]),
            PatternCandidate("Weak pattern", "Desc", "topic", 2, 0.3, ["ev"]),
        ]
        result = _save_candidates_directly(candidates, "", MetaLearningResult())
        assert result.learnings_created == 1  # only the 0.7 confidence one
        with db() as conn:
            rows = _get_learnings(conn)
        assert len(rows) == 1
        assert rows[0]["title"] == "Good pattern"

    def test_empty_candidates(self, patched_db):
        from backend.meta_learning import MetaLearningResult

        result = _save_candidates_directly([], "", MetaLearningResult())
        assert result.learnings_created == 0


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestLearningsAPI:
    def _seed_learning(self, conn, learning_id="lr-test1", title="Test learning"):
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO learnings
               (id, title, description, category, confidence, observation_count,
                evidence, active, last_observed_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (learning_id, title, "A test learning", "workflow", 0.8, 3,
             json.dumps(["ev1", "ev2"]), now, now, now),
        )

    def test_list_learnings(self, client):
        with db() as conn:
            self._seed_learning(conn)
        resp = client.get("/api/learnings")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "lr-test1"
        assert data[0]["title"] == "Test learning"

    def test_list_learnings_filter_category(self, client):
        with db() as conn:
            self._seed_learning(conn, "lr-1", "Workflow one")
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT INTO learnings
                   (id, title, description, category, confidence, observation_count,
                    active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                ("lr-2", "Temporal one", "desc", "temporal", 0.6, 2, now, now),
            )
        resp = client.get("/api/learnings?category=temporal")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["category"] == "temporal"

    def test_get_learning(self, client):
        with db() as conn:
            self._seed_learning(conn)
        resp = client.get("/api/learnings/lr-test1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "lr-test1"

    def test_get_learning_not_found(self, client):
        resp = client.get("/api/learnings/lr-nonexistent")
        assert resp.status_code == 404

    def test_update_learning(self, client):
        with db() as conn:
            self._seed_learning(conn)
        resp = client.patch("/api/learnings/lr-test1", json={"title": "Updated title", "active": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Updated title"
        assert data["active"] is False

    def test_update_learning_not_found(self, client):
        resp = client.patch("/api/learnings/lr-nope", json={"title": "x"})
        assert resp.status_code == 404

    def test_delete_learning(self, client):
        with db() as conn:
            self._seed_learning(conn)
        resp = client.delete("/api/learnings/lr-test1")
        assert resp.status_code == 204
        # Verify deleted
        resp = client.get("/api/learnings/lr-test1")
        assert resp.status_code == 404

    def test_delete_learning_not_found(self, client):
        resp = client.delete("/api/learnings/lr-nope")
        assert resp.status_code == 404

    def test_list_inactive_learnings(self, client):
        with db() as conn:
            self._seed_learning(conn)
            # Deactivate
            conn.execute("UPDATE learnings SET active = 0 WHERE id = 'lr-test1'")
        # Default: active_only=true
        resp = client.get("/api/learnings")
        assert resp.status_code == 200
        assert len(resp.json()) == 0
        # Explicit active_only=false
        resp = client.get("/api/learnings?active_only=false")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
