"""Tests for feedback endpoint sanitization (SEC-032)."""

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def feedback_client(monkeypatch):
    """TestClient with auth and GitHub API mocked."""
    from backend.auth import require_user
    from backend.config import settings
    from backend.http_client import get_http_client
    from backend.main import app

    monkeypatch.setattr(settings, "GITHUB_FEEDBACK_TOKEN", "fake-token")
    monkeypatch.setattr(settings, "GITHUB_FEEDBACK_REPO", "owner/repo")

    app.dependency_overrides[require_user] = lambda: "test-user"

    mock_request = httpx.Request("POST", "https://api.github.com/repos/owner/repo/issues")
    mock_response = httpx.Response(
        201,
        json={"html_url": "https://github.com/owner/repo/issues/1"},
        request=mock_request,
    )

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    app.dependency_overrides[get_http_client] = lambda: mock_client

    with TestClient(app) as c:
        yield c, mock_client

    app.dependency_overrides.pop(require_user, None)
    app.dependency_overrides.pop(get_http_client, None)


def _get_issue_body(mock_http: AsyncMock) -> str:
    """Extract the issue body from the last GitHub API call."""
    call_kwargs = mock_http.post.call_args
    json_payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
    return json_payload["body"]


class TestFeedbackSanitization:
    def test_newline_in_user_agent_is_stripped(self, feedback_client):
        """SEC-032: newlines in user_agent must not inject markdown.

        The fix replaces \\n with a space so injected text stays on the
        **Browser:** line instead of becoming its own markdown heading.
        """
        client, mock_http = feedback_client
        resp = client.post(
            "/api/feedback",
            json={
                "category": "bug",
                "message": "Something broke",
                "user_agent": "Mozilla/5.0\n## Injected Header",
                "url": "",
            },
        )
        assert resp.status_code == 200

        issue_body = _get_issue_body(mock_http)
        # The injected heading must NOT appear on its own line
        lines = issue_body.split("\n")
        assert not any(ln.strip() == "## Injected Header" for ln in lines)
        # But the browser line should contain the sanitized value
        browser_line = [ln for ln in lines if ln.startswith("**Browser:**")][0]
        assert "Mozilla/5.0" in browser_line

    def test_newline_in_url_is_stripped(self, feedback_client):
        """SEC-032: newlines in url must not inject markdown."""
        client, mock_http = feedback_client
        resp = client.post(
            "/api/feedback",
            json={
                "category": "bug",
                "message": "Something broke",
                "user_agent": "",
                "url": "https://example.com\n## Injected",
            },
        )
        assert resp.status_code == 200

        issue_body = _get_issue_body(mock_http)
        lines = issue_body.split("\n")
        # The injected heading must NOT appear on its own line
        assert not any(ln.strip() == "## Injected" for ln in lines)
        # The page line should contain the sanitized URL
        page_line = [ln for ln in lines if ln.startswith("**Page:**")][0]
        assert "https://example.com" in page_line

    def test_carriage_return_in_user_agent_is_stripped(self, feedback_client):
        """SEC-032: \\r in user_agent must also be removed."""
        client, mock_http = feedback_client
        resp = client.post(
            "/api/feedback",
            json={
                "category": "bug",
                "message": "Something broke",
                "user_agent": "Mozilla/5.0\r\n## Injected",
                "url": "",
            },
        )
        assert resp.status_code == 200

        issue_body = _get_issue_body(mock_http)
        lines = issue_body.split("\n")
        # Neither \\r nor the injected heading on its own line
        assert not any("\r" in ln for ln in lines)
        assert not any(ln.strip() == "## Injected" for ln in lines)
