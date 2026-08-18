"""Integration tests for GDPR export and delete-all endpoints.

These endpoints are compliance-critical: export must return all user data
categories, and delete-all must remove every record without FK violations.
"""

import uuid
from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

import backend.db_engine as _engine_mod
from backend.auth import require_user
from backend.db_engine import get_session
from backend.main import app


# ---------------------------------------------------------------------------
# Fixture: authenticated client with explicit session override
# ---------------------------------------------------------------------------


@pytest.fixture()
def gdpr_client(patched_db) -> Generator[TestClient, None, None]:
    """TestClient that overrides both require_user AND get_session.

    This ensures request-handling uses the patched engine, bypassing the
    DB-isolation issue in the default user_a_client fixture.
    """

    def _override_session() -> Generator[Session, None, None]:
        with Session(_engine_mod.engine) as session:
            yield session

    app.dependency_overrides[require_user] = lambda: "user-a"
    app.dependency_overrides[get_session] = _override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(require_user, None)
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture()
def gdpr_client_noauth(patched_db) -> Generator[TestClient, None, None]:
    """TestClient with session override but no auth (user_id='')."""

    def _override_session() -> Generator[Session, None, None]:
        with Session(_engine_mod.engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_user(db, user_id: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, google_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, f"{user_id}@test.com", f"g-{user_id}", f"Test {user_id}", _now(), _now()),
        )


def _seed_thing(db, user_id: str, title: str = "Test Thing") -> str:
    tid = _new_id()
    now = _now()
    with db() as conn:
        conn.execute(
            "INSERT INTO things (id, title, user_id, active, surface, created_at, updated_at) VALUES (?, ?, ?, 1, 1, ?, ?)",
            (tid, title, user_id, now, now),
        )
    return tid


def _seed_relationship(db, from_id: str, to_id: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type) VALUES (?, ?, ?, ?)",
            (_new_id(), from_id, to_id, "related-to"),
        )


def _seed_chat(db, user_id: str, message: str = "hello") -> str:
    sid = _new_id()
    now = _now()
    with db() as conn:
        conn.execute(
            "INSERT INTO chat_sessions (id, user_id, title, created_at, last_active_at) VALUES (?, ?, ?, ?, ?)",
            (sid, user_id, "Test chat", now, now),
        )
        conn.execute(
            "INSERT INTO chat_history (session_id, role, content) VALUES (?, ?, ?)",
            (sid, "user", message),
        )
    return sid


def _seed_setting(db, user_id: str, key: str, value: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO user_settings (user_id, key, value, updated_at) VALUES (?, ?, ?, ?)",
            (user_id, key, value, _now()),
        )


def _seed_summary(db, user_id: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO conversation_summaries (user_id, summary_text, messages_summarized_up_to, created_at) VALUES (?, ?, ?, ?)",
            (user_id, "test summary", 10, _now()),
        )


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------


class TestExportUserData:
    """GET /api/gdpr/export"""

    def test_export_returns_all_data_keys(self, db, gdpr_client):
        """Export returns the full structure with all expected keys."""
        resp = gdpr_client.get("/api/gdpr/export")
        assert resp.status_code == 200
        data = resp.json()
        expected_keys = {
            "user", "things", "relationships", "embeddings",
            "chat_sessions", "chat_history", "conversation_summaries",
            "settings", "google_tokens", "sweep_findings", "sweep_runs",
            "sweep_actions", "usage_log", "morning_briefings",
            "weekly_briefings", "connection_suggestions",
            "nudge_dismissals", "nudge_suppressions",
            "merge_history", "thing_types", "scheduled_tasks",
        }
        assert set(data.keys()) == expected_keys

    def test_export_includes_things_and_relationships(self, db, gdpr_client):
        """Export contains things and their relationships."""
        t1 = _seed_thing(db, "user-a", "Thing A1")
        t2 = _seed_thing(db, "user-a", "Thing A2")
        _seed_relationship(db, t1, t2)

        resp = gdpr_client.get("/api/gdpr/export")
        data = resp.json()
        assert len(data["things"]) == 2
        assert len(data["relationships"]) == 1
        assert data["relationships"][0]["from_thing_id"] == t1
        assert data["relationships"][0]["to_thing_id"] == t2

    def test_export_includes_chat_history(self, db, gdpr_client):
        """Export contains chat sessions and messages."""
        _seed_chat(db, "user-a", "test message")

        resp = gdpr_client.get("/api/gdpr/export")
        data = resp.json()
        assert len(data["chat_sessions"]) == 1
        assert len(data["chat_history"]) == 1
        assert data["chat_history"][0]["content"] == "test message"

    def test_export_redacts_api_key_settings(self, db, gdpr_client):
        """Settings containing API keys are redacted in export."""
        _seed_user(db, "user-a")
        _seed_setting(db, "user-a", "requesty_api_key", "sk-secret-123")
        _seed_setting(db, "user-a", "theme", "dark")

        resp = gdpr_client.get("/api/gdpr/export")
        data = resp.json()
        settings_by_key = {s["key"]: s["value"] for s in data["settings"]}
        assert settings_by_key["requesty_api_key"] == "[REDACTED]"
        assert settings_by_key["theme"] == "dark"

    def test_export_excludes_other_users_things(self, db, gdpr_client):
        """User A's export does not contain other users' things."""
        _seed_thing(db, "user-a", "A's Thing")
        _seed_thing(db, "other-user", "B's Thing")

        resp = gdpr_client.get("/api/gdpr/export")
        data = resp.json()
        assert len(data["things"]) == 1
        assert data["things"][0]["title"] == "A's Thing"

    def test_export_includes_conversation_summaries(self, db, gdpr_client):
        """Export contains conversation summaries."""
        _seed_user(db, "user-a")
        _seed_summary(db, "user-a")

        resp = gdpr_client.get("/api/gdpr/export")
        data = resp.json()
        assert len(data["conversation_summaries"]) == 1
        assert data["conversation_summaries"][0]["summary_text"] == "test summary"


# ---------------------------------------------------------------------------
# Delete-all tests
# ---------------------------------------------------------------------------


class TestDeleteAllUserData:
    """DELETE /api/gdpr/delete-all"""

    def test_delete_removes_things_and_relationships(self, db, gdpr_client):
        """Delete-all removes user's things and relationships in FK-safe order."""
        t1 = _seed_thing(db, "user-a", "A")
        t2 = _seed_thing(db, "user-a", "B")
        _seed_relationship(db, t1, t2)

        resp = gdpr_client.delete("/api/gdpr/delete-all")
        assert resp.status_code == 200

        export = gdpr_client.get("/api/gdpr/export")
        assert len(export.json()["things"]) == 0
        assert len(export.json()["relationships"]) == 0

    def test_delete_removes_chat_history(self, db, gdpr_client):
        """Delete-all removes chat sessions and messages."""
        _seed_chat(db, "user-a", "bye")

        resp = gdpr_client.delete("/api/gdpr/delete-all")
        assert resp.status_code == 200

        export = gdpr_client.get("/api/gdpr/export")
        assert len(export.json()["chat_sessions"]) == 0
        assert len(export.json()["chat_history"]) == 0

    def test_delete_removes_settings_and_user(self, db, gdpr_client):
        """Delete-all removes user settings and user record."""
        _seed_user(db, "user-a")
        _seed_setting(db, "user-a", "theme", "dark")

        resp = gdpr_client.delete("/api/gdpr/delete-all")
        assert resp.status_code == 200

        export = gdpr_client.get("/api/gdpr/export")
        assert len(export.json()["settings"]) == 0
        assert export.json()["user"] is None

    def test_delete_preserves_other_users_data(self, db, gdpr_client):
        """Delete-all for User A does not touch other users' data."""
        _seed_thing(db, "user-a", "A's Thing")
        _seed_thing(db, "other-user", "B's Thing")
        _seed_chat(db, "user-a", "A says hi")
        _seed_chat(db, "other-user", "B says hi")

        gdpr_client.delete("/api/gdpr/delete-all")

        # Verify other user's data persists via direct DB query
        with db() as conn:
            rows = conn.execute("SELECT title FROM things WHERE user_id = 'other-user'").fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "B's Thing"

            sessions = conn.execute("SELECT id FROM chat_sessions WHERE user_id = 'other-user'").fetchall()
            assert len(sessions) == 1

    def test_delete_clears_session_cookie(self, db, gdpr_client):
        """Delete-all response clears the auth cookie."""
        _seed_thing(db, "user-a", "Placeholder")

        resp = gdpr_client.delete("/api/gdpr/delete-all")
        assert resp.status_code == 200
        set_cookie = resp.headers.get("set-cookie", "")
        assert "reli_session" in set_cookie

    def test_delete_removes_summaries(self, db, gdpr_client):
        """Delete-all removes conversation summaries."""
        _seed_user(db, "user-a")
        _seed_summary(db, "user-a")

        resp = gdpr_client.delete("/api/gdpr/delete-all")
        assert resp.status_code == 200

        export = gdpr_client.get("/api/gdpr/export")
        assert len(export.json()["conversation_summaries"]) == 0
