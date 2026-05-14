"""Tests for the /api/focus endpoint (PR #957)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _insert_thing(db, user_id: str, title: str, importance: int = 2) -> str:
    thing_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            """INSERT INTO things
               (id, title, type_hint, importance, active, surface,
                data, checkin_date, user_id, created_at, updated_at)
               VALUES (?, ?, 'task', ?, 1, 1, NULL, NULL, ?, datetime('now'), datetime('now'))""",
            (thing_id, title, importance, user_id),
        )
    return thing_id


def _insert_rel(db, from_id: str, to_id: str, rel_type: str) -> str:
    rel_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            "INSERT INTO thing_relationships"
            " (id, from_thing_id, to_thing_id, relationship_type)"
            " VALUES (?, ?, ?, ?)",
            (rel_id, from_id, to_id, rel_type),
        )
    return rel_id


def _create_thing(client, title: str, **kwargs) -> dict:
    payload = {"title": title, "active": True, **kwargs}
    resp = client.post("/api/things", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestFocusEndpoint:
    """Basic endpoint tests for GET /api/focus."""

    def test_focus_returns_ok_empty(self, client):
        """GET /api/focus returns 200 with no things (exercises empty thing_ids guard)."""
        resp = client.get("/api/focus")
        assert resp.status_code == 200
        data = resp.json()
        assert data["recommendations"] == []
        assert data["total"] == 0

    def test_focus_returns_recommendations(self, client):
        """Focus returns scored recommendations for active things."""
        _create_thing(client, "Write report", type_hint="task", importance=0)
        _create_thing(client, "Buy groceries", type_hint="task", importance=2)

        resp = client.get("/api/focus")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        titles = [r["thing"]["title"] for r in data["recommendations"]]
        assert "Write report" in titles
        assert "Buy groceries" in titles

    def test_focus_limit_parameter(self, client):
        """Limit parameter caps the number of recommendations."""
        for i in range(5):
            _create_thing(client, f"Task {i}", type_hint="task", importance=1)

        resp = client.get("/api/focus?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["recommendations"]) <= 2

    def test_focus_excludes_non_actionable_types(self, client):
        """Person, place, concept, reference, preference types are excluded from focus."""
        _create_thing(client, "Alice", type_hint="person")
        _create_thing(client, "Home Office", type_hint="place")
        _create_thing(client, "Do something", type_hint="task", importance=1)

        resp = client.get("/api/focus")
        assert resp.status_code == 200
        titles = [r["thing"]["title"] for r in resp.json()["recommendations"]]
        assert "Alice" not in titles
        assert "Home Office" not in titles
        assert "Do something" in titles


class TestFocusUserIsolation:
    """Cross-user isolation tests for the user-scoped relationship query in _compute_recommendations."""

    def test_other_user_blocks_relationship_not_applied(self, patched_db, db):
        """User B's 'blocks' relationship must not affect User A's focus scoring."""
        from backend.routers.focus import _compute_recommendations

        user_a = "user-focus-a"
        user_b = "user-focus-b"

        a1 = _insert_thing(db, user_a, "A: Important task", importance=0)
        b1 = _insert_thing(db, user_b, "B: Task 1")
        b2 = _insert_thing(db, user_b, "B: Task 2")
        # B1 blocks B2 — must not affect A's scoring at all
        _insert_rel(db, b1, b2, "blocks")

        result = _compute_recommendations(user_id=user_a, limit=10)
        recs = {r.thing.id: r for r in result.recommendations}
        # A's task must not be marked as blocked
        if a1 in recs:
            assert not recs[a1].is_blocked

    def test_empty_user_returns_no_recommendations(self, patched_db):
        """With no things for user, relationship query short-circuits to empty list (no SQL error)."""
        from backend.routers.focus import _compute_recommendations

        result = _compute_recommendations(user_id="no-things-user", limit=10)
        assert result.total == 0
        assert result.recommendations == []

    def test_user_own_blocks_relationship_is_applied(self, patched_db, db):
        """A 'blocks' relationship between User A's own things should be reflected in scoring."""
        from backend.routers.focus import _compute_recommendations

        user_a = "user-focus-a3"

        a1 = _insert_thing(db, user_a, "A Blocker task", importance=1)
        a2 = _insert_thing(db, user_a, "A Blocked task", importance=1)
        # a1 blocks a2 — a2 should be marked as blocked
        _insert_rel(db, a1, a2, "blocks")

        result = _compute_recommendations(user_id=user_a, limit=10)
        recs = {r.thing.id: r for r in result.recommendations}
        if a2 in recs:
            assert recs[a2].is_blocked

    def test_cross_user_isolation_via_endpoint(self, patched_db, db):
        """User B's things must not appear in User A's /api/focus response."""
        from backend.auth import require_user
        from backend.main import app

        user_a = "user-focus-ep-a"
        user_b = "user-focus-ep-b"

        _insert_thing(db, user_a, "A Task (focus endpoint)", importance=1)
        b1 = _insert_thing(db, user_b, "B Task 1 (focus)")
        b2 = _insert_thing(db, user_b, "B Task 2 (focus)")
        _insert_rel(db, b1, b2, "blocks")

        app.dependency_overrides[require_user] = lambda: user_a
        try:
            with TestClient(app) as c:
                resp = c.get("/api/focus")
                assert resp.status_code == 200
                data = resp.json()
                rec_ids = {r["thing"]["id"] for r in data["recommendations"]}
                assert b1 not in rec_ids
                assert b2 not in rec_ids
        finally:
            app.dependency_overrides.pop(require_user, None)
