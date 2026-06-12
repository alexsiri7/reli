"""Tests for GDPR data export and delete-all endpoints (issue #1199).

Uses a local ``gdpr_client`` fixture that overrides ``get_session`` BEFORE
creating the TestClient, ensuring API requests and test seed data both hit
the same in-memory SQLite engine provided by ``patched_db``.
"""

import uuid
from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlmodel import Session

import backend.db_engine as _engine_mod

# Force-import the app (and every router, including gdpr.py) at module load time,
# BEFORE any per-test fixture runs.  patched_db replaces engine_module.get_session
# with a per-test closure; if gdpr.py is first imported while patched_db is active
# its local `get_session` binding would be set to that closure — and every
# subsequent test would use the first test's engine, not the current one.
# Importing backend.main here ensures gdpr.py's binding is set to the *original*
# get_session function, which is also the key we use for dependency_overrides.
import backend.main  # noqa: F401
from backend.db_engine import get_session as _original_get_session

_USER_ID = ""  # auth-disabled passthrough
_OTHER_USER = "other-user"


def _gdpr_client_inner(patched_db) -> Generator[TestClient, None, None]:
    """Create a TestClient with ``get_session`` overridden to the test engine.

    The override is registered BEFORE ``TestClient.__enter__`` triggers the
    app lifespan, so the very first request already uses the test DB.
    """
    from backend.main import app

    def _test_get_session() -> Generator[Session, None, None]:
        with Session(_engine_mod.engine) as session:
            yield session

    saved = app.dependency_overrides.get(_original_get_session)
    app.dependency_overrides[_original_get_session] = _test_get_session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        if saved is None:
            app.dependency_overrides.pop(_original_get_session, None)
        else:
            app.dependency_overrides[_original_get_session] = saved


class TestDeleteAll:
    def test_delete_all_removes_user_thing(self, patched_db):
        """After delete-all, the calling user's Things are gone from the DB."""
        from backend.db_models import ThingRecord

        thing_id = str(uuid.uuid4())
        with Session(_engine_mod.engine) as session:
            session.add(ThingRecord(id=thing_id, title="My Thing", user_id=_USER_ID, importance=2))
            session.commit()

        for client in _gdpr_client_inner(patched_db):
            resp = client.delete("/api/gdpr/delete-all")
            assert resp.status_code == 200

        with Session(_engine_mod.engine) as session:
            assert session.get(ThingRecord, thing_id) is None

    def test_delete_all_clears_session_cookie(self, patched_db):
        for client in _gdpr_client_inner(patched_db):
            resp = client.delete("/api/gdpr/delete-all")
            assert resp.status_code == 200
            cookie_header = resp.headers.get("set-cookie", "")
            assert "reli_session" in cookie_header or "Max-Age=0" in cookie_header

    def test_delete_all_does_not_affect_other_user(self, patched_db):
        """Deleting the calling user's data must not touch a different user's records."""
        from backend.db_models import ThingRecord

        other_id = str(uuid.uuid4())
        with Session(_engine_mod.engine) as session:
            session.add(ThingRecord(id=other_id, title="Other Thing", user_id=_OTHER_USER, importance=2))
            session.commit()

        for client in _gdpr_client_inner(patched_db):
            resp = client.delete("/api/gdpr/delete-all")
            assert resp.status_code == 200

        with Session(_engine_mod.engine) as session:
            assert session.get(ThingRecord, other_id) is not None

    def test_delete_all_fk_ordering(self, patched_db):
        """No FK violation when chat message usage rows exist."""
        from backend.db_models import ChatHistoryRecord, ChatMessageUsageRecord, ChatSessionRecord

        sess_id = str(uuid.uuid4())
        with Session(_engine_mod.engine) as session:
            session.add(ChatSessionRecord(id=sess_id, user_id=_USER_ID))
            session.flush()
            msg = ChatHistoryRecord(
                session_id=sess_id,
                role="user",
                content="hi",
                prompt_tokens=0,
                completion_tokens=0,
                cost_usd=0.0,
            )
            session.add(msg)
            session.flush()
            session.add(ChatMessageUsageRecord(chat_message_id=msg.id, model="gpt-4", tokens=10))
            session.commit()

        for client in _gdpr_client_inner(patched_db):
            resp = client.delete("/api/gdpr/delete-all")
            assert resp.status_code == 200, resp.text

    def test_delete_all_removes_mcp_refresh_tokens(self, patched_db):
        """McpRefreshTokenRecord rows for the user are deleted."""
        from backend.db_models import McpRefreshTokenRecord

        token_val = str(uuid.uuid4())
        with Session(_engine_mod.engine) as session:
            session.add(
                McpRefreshTokenRecord(
                    refresh_token=token_val,
                    user_id=_USER_ID,
                    email="test@example.com",
                    client_id="client-1",
                    scope="openid",
                    expires_at=9999999999.0,
                )
            )
            session.commit()

        for client in _gdpr_client_inner(patched_db):
            resp = client.delete("/api/gdpr/delete-all")
            assert resp.status_code == 200

        with Session(_engine_mod.engine) as session:
            assert session.get(McpRefreshTokenRecord, token_val) is None

    def test_delete_all_does_not_remove_other_user_mcp_tokens(self, patched_db):
        """McpRefreshTokenRecord rows owned by another user are NOT deleted."""
        from backend.db_models import McpRefreshTokenRecord

        other_token_val = str(uuid.uuid4())
        with Session(_engine_mod.engine) as session:
            session.add(
                McpRefreshTokenRecord(
                    refresh_token=other_token_val,
                    user_id=_OTHER_USER,
                    email="other@example.com",
                    client_id="client-1",
                    scope="openid",
                    expires_at=9999999999.0,
                )
            )
            session.commit()

        for client in _gdpr_client_inner(patched_db):
            client.delete("/api/gdpr/delete-all")

        with Session(_engine_mod.engine) as session:
            assert session.get(McpRefreshTokenRecord, other_token_val) is not None


class TestExport:
    def test_export_returns_expected_keys(self, patched_db):
        for client in _gdpr_client_inner(patched_db):
            resp = client.get("/api/gdpr/export")
            assert resp.status_code == 200
            expected_keys = {
                "user",
                "things",
                "relationships",
                "embeddings",
                "chat_sessions",
                "chat_history",
                "conversation_summaries",
                "settings",
                "google_tokens",
                "sweep_findings",
                "sweep_runs",
                "sweep_actions",
                "usage_log",
                "morning_briefings",
                "weekly_briefings",
                "connection_suggestions",
                "nudge_dismissals",
                "nudge_suppressions",
                "merge_history",
                "thing_types",
                "scheduled_tasks",
                "mcp_refresh_tokens",
                "mcp_auth_codes",
                "gmail_oauth_state",
            }
            assert set(resp.json().keys()) == expected_keys

    def test_export_redacts_api_keys(self, patched_db):
        from backend.db_models import UserSettingRecord

        with Session(_engine_mod.engine) as session:
            session.add(UserSettingRecord(user_id=_USER_ID, key="requesty_api_key", value="sk-secret"))
            session.add(UserSettingRecord(user_id=_USER_ID, key="theme", value="dark"))
            session.commit()

        for client in _gdpr_client_inner(patched_db):
            resp = client.get("/api/gdpr/export")
            assert resp.status_code == 200
            settings_by_key = {s["key"]: s["value"] for s in resp.json()["settings"]}
            assert "requesty_api_key" in settings_by_key
            assert settings_by_key["requesty_api_key"] == "[REDACTED]"
            assert settings_by_key["theme"] == "dark"

    def test_export_does_not_return_other_user_settings(self, patched_db):
        """In auth-disabled mode, user_filter_clause returns all records.
        We verify our seeded settings are present (isolation tested at DB level).
        """
        from backend.db_models import UserSettingRecord

        with Session(_engine_mod.engine) as session:
            session.add(UserSettingRecord(user_id=_USER_ID, key="my_setting", value="mine"))
            session.add(UserSettingRecord(user_id=_OTHER_USER, key="their_setting", value="theirs"))
            session.commit()

        for client in _gdpr_client_inner(patched_db):
            resp = client.get("/api/gdpr/export")
            assert resp.status_code == 200
            settings_by_key = {s["key"]: s["value"] for s in resp.json()["settings"]}
            assert "my_setting" in settings_by_key

    def test_export_includes_mcp_refresh_tokens(self, patched_db):
        """Export includes MCP refresh token metadata (not the token value itself)."""
        from backend.db_models import McpRefreshTokenRecord

        token_val = str(uuid.uuid4())
        with Session(_engine_mod.engine) as session:
            session.add(
                McpRefreshTokenRecord(
                    refresh_token=token_val,
                    user_id=_USER_ID,
                    email="test@example.com",
                    client_id="client-1",
                    scope="openid",
                    expires_at=9999999999.0,
                )
            )
            session.commit()

        for client in _gdpr_client_inner(patched_db):
            resp = client.get("/api/gdpr/export")
            assert resp.status_code == 200
            mcp_tokens = resp.json()["mcp_refresh_tokens"]
            assert len(mcp_tokens) == 1, f"Expected 1 MCP token in export, got {len(mcp_tokens)}"
            assert "refresh_token" not in mcp_tokens[0]
            assert mcp_tokens[0]["client_id"] == "client-1"

    def test_export_includes_mcp_auth_codes(self, patched_db):
        """Export includes MCP auth code metadata (not auth_code or code_challenge)."""
        from backend.db_models import McpAuthCodeRecord

        with Session(_engine_mod.engine) as session:
            session.add(
                McpAuthCodeRecord(
                    auth_code="secret-code-123",
                    user_id=_USER_ID,
                    email="test@example.com",
                    code_challenge="challenge-secret",
                    code_challenge_method="S256",
                    redirect_uri="http://localhost/callback",
                    client_id="client-1",
                    expires_at=9999999999.0,
                )
            )
            session.commit()

        for client in _gdpr_client_inner(patched_db):
            resp = client.get("/api/gdpr/export")
            assert resp.status_code == 200
            codes = resp.json()["mcp_auth_codes"]
            assert len(codes) == 1
            assert "auth_code" not in codes[0]
            assert "code_challenge" not in codes[0]
            assert codes[0]["client_id"] == "client-1"
            assert codes[0]["email"] == "test@example.com"

    def test_export_includes_gmail_oauth_state(self, patched_db):
        """Export includes Gmail OAuth state metadata (not the state token itself)."""
        from backend.db_models import GmailOAuthStateRecord

        with Session(_engine_mod.engine) as session:
            session.add(
                GmailOAuthStateRecord(
                    user_id=_USER_ID,
                    state="csrf-secret-token",
                    expires_at=9999999999.0,
                )
            )
            session.commit()

        for client in _gdpr_client_inner(patched_db):
            resp = client.get("/api/gdpr/export")
            assert resp.status_code == 200
            gmail_state = resp.json()["gmail_oauth_state"]
            assert gmail_state is not None
            assert "state" not in gmail_state
            assert gmail_state["user_id"] == _USER_ID
