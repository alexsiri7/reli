"""Tests for the feedback endpoint (SEC-022 regression guard)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from backend.auth import require_user
from backend.http_client import get_http_client
from backend.main import app


@pytest.fixture()
def _feedback_env(monkeypatch: pytest.MonkeyPatch):
    """Set required feedback config so the endpoint doesn't return 501."""
    monkeypatch.setattr("backend.routers.feedback.settings.GITHUB_FEEDBACK_TOKEN", "ghp_test")
    monkeypatch.setattr("backend.routers.feedback.settings.GITHUB_FEEDBACK_REPO", "owner/repo")


@pytest.fixture()
def auth_client(_feedback_env) -> TestClient:
    """TestClient authenticated as 'test-user-id' with mocked HTTP client."""
    mock_client = httpx.AsyncClient()

    app.dependency_overrides[require_user] = lambda: "test-user-id"
    app.dependency_overrides[get_http_client] = lambda: mock_client
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(require_user, None)
        app.dependency_overrides.pop(get_http_client, None)


_GITHUB_ISSUES_URL = "https://api.github.com/repos/owner/repo/issues"


class TestFeedbackUserIdNotLeaked:
    """SEC-022: user_id must never appear in the GitHub issue body."""

    @respx.mock
    def test_user_id_absent_from_issue_body(self, auth_client: TestClient):
        """The internal user_id must not be included in the GitHub issue body."""
        route = respx.post(_GITHUB_ISSUES_URL).mock(
            return_value=httpx.Response(
                201,
                json={"html_url": "https://github.com/owner/repo/issues/1"},
            )
        )

        resp = auth_client.post(
            "/api/feedback",
            json={
                "category": "bug",
                "message": "Something broke",
                "user_agent": "TestBrowser/1.0",
                "url": "http://localhost/page",
            },
        )

        assert resp.status_code == 200
        body = route.calls.last.request.content.decode()
        assert "test-user-id" not in body
        assert "**User:**" not in body

    @respx.mock
    def test_context_still_includes_browser_and_page(self, auth_client: TestClient):
        """Browser and page context should still appear in the issue body."""
        route = respx.post(_GITHUB_ISSUES_URL).mock(
            return_value=httpx.Response(
                201,
                json={"html_url": "https://github.com/owner/repo/issues/2"},
            )
        )

        resp = auth_client.post(
            "/api/feedback",
            json={
                "category": "feature",
                "message": "Add dark mode",
                "user_agent": "TestBrowser/1.0",
                "url": "http://localhost/settings",
            },
        )

        assert resp.status_code == 200
        body = route.calls.last.request.content.decode()
        assert "TestBrowser/1.0" in body
        assert "http://localhost/settings" in body
