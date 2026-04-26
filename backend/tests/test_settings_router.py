"""Tests for settings API key encrypt/decrypt round-trip."""

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

_TEST_FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture()
def auth_client(patched_db, monkeypatch):
    """TestClient with require_user patched and a valid Fernet key."""
    from backend.auth import require_user
    from backend.main import app
    from backend.token_encryption import reset_for_testing

    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", _TEST_FERNET_KEY)
    reset_for_testing()

    app.dependency_overrides[require_user] = lambda: "test-user-settings"
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(require_user, None)
    reset_for_testing()


class TestSettingsUserEndpoint:
    def test_put_api_key_then_get_returns_masked(self, auth_client):
        """Store an API key, retrieve it, verify it comes back masked."""

        resp = auth_client.put("/api/settings/user", json={
            "requesty_api_key": "sk-test-key-12345678",
        })
        assert resp.status_code == 200

        resp = auth_client.get("/api/settings/user")
        assert resp.status_code == 200
        body = resp.json()
        assert body["requesty_api_key"].endswith("5678")
        assert "*" in body["requesty_api_key"]

    def test_put_empty_key_clears(self, auth_client):
        """PUT with empty key stores empty string."""
        auth_client.put("/api/settings/user", json={"requesty_api_key": "sk-temp"})
        auth_client.put("/api/settings/user", json={"requesty_api_key": ""})

        resp = auth_client.get("/api/settings/user")
        assert resp.status_code == 200
        body = resp.json()
        assert body["requesty_api_key"] in ("", "****")

    def test_get_without_prior_put_returns_empty(self, auth_client):
        """GET without prior PUT returns empty string for API key."""
        resp = auth_client.get("/api/settings/user")
        assert resp.status_code == 200
        body = resp.json()
        assert body["requesty_api_key"] == ""

    def test_update_model_override(self, auth_client):
        """PUT model override, GET reflects new value."""
        resp = auth_client.put("/api/settings/user", json={
            "context_model": "gpt-4o-mini",
        })
        assert resp.status_code == 200

        resp = auth_client.get("/api/settings/user")
        assert resp.status_code == 200
        body = resp.json()
        assert body["context_model"] == "gpt-4o-mini"

    def test_get_user_settings_with_empty_chat_context_window(self, auth_client, patched_db):
        """GET /settings/user must not crash when chat_context_window is stored as ''."""
        from sqlmodel import Session

        import backend.db_engine as _engine_mod
        from backend.routers.settings import _set_user_setting

        with Session(_engine_mod.engine) as session:
            _set_user_setting(session, "test-user-settings", "chat_context_window", "")
            session.commit()

        resp = auth_client.get("/api/settings/user")
        assert resp.status_code == 200
        body = resp.json()
        assert body["chat_context_window"] is None
