"""Tests for the feedback submission endpoint."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from backend.http_client import get_http_client


@pytest.fixture()
def feedback_client(patched_db, monkeypatch):
    """TestClient with GitHub feedback config patched and httpx client mocked."""
    from backend.main import app
    import backend.routers.feedback as feedback_mod

    fake_settings = MagicMock()
    fake_settings.GITHUB_FEEDBACK_TOKEN = "tok"
    fake_settings.GITHUB_FEEDBACK_REPO = "org/repo"
    monkeypatch.setattr(feedback_mod, "settings", fake_settings)

    mock_client = AsyncMock()
    app.dependency_overrides[get_http_client] = lambda: mock_client
    with TestClient(app) as c:
        yield c, mock_client
    app.dependency_overrides.pop(get_http_client, None)


class TestFeedbackScreenshotCDN:
    def _make_upload_resp(self, url: str) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"url": url}
        return resp

    def _make_issue_resp(self, html_url: str) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"html_url": html_url}
        return resp

    def test_screenshot_cdn_upload_success_embeds_url(self, feedback_client):
        """When CDN upload succeeds, issue body includes the screenshot markdown."""
        client, mock_http = feedback_client
        mock_http.post = AsyncMock(side_effect=[
            self._make_upload_resp("https://cdn.github.com/img.jpg"),
            self._make_issue_resp("https://github.com/org/repo/issues/1"),
        ])

        resp = client.post("/api/feedback", json={
            "category": "bug",
            "message": "Something broke",
            "screenshot_base64": "aGVsbG8=",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        issue_call = mock_http.post.call_args_list[1]
        issue_body = issue_call.kwargs.get("json", {}).get("body", "")
        assert "## Screenshot" in issue_body
        assert "https://cdn.github.com/img.jpg" in issue_body

    def test_screenshot_cdn_failure_still_submits(self, feedback_client):
        """When CDN upload fails, issue is still created without screenshot (silent degradation)."""
        client, mock_http = feedback_client

        failed_upload = MagicMock()
        failed_upload.raise_for_status.side_effect = Exception("CDN error")

        mock_http.post = AsyncMock(side_effect=[
            failed_upload,
            self._make_issue_resp("https://github.com/org/repo/issues/2"),
        ])

        resp = client.post("/api/feedback", json={
            "category": "bug",
            "message": "Something broke",
            "screenshot_base64": "aGVsbG8=",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        issue_call = mock_http.post.call_args_list[1]
        issue_body = issue_call.kwargs.get("json", {}).get("body", "")
        assert "## Screenshot" not in issue_body

    def test_no_screenshot_skips_cdn_upload(self, feedback_client):
        """When no screenshot is provided, CDN upload is skipped; only one POST made."""
        client, mock_http = feedback_client
        mock_http.post = AsyncMock(return_value=self._make_issue_resp("https://github.com/org/repo/issues/3"))

        resp = client.post("/api/feedback", json={
            "category": "feature",
            "message": "Feature request without screenshot",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert mock_http.post.call_count == 1

    def test_oversized_screenshot_rejected(self, feedback_client):
        """screenshot_base64 exceeding 2.8M chars is rejected with 422."""
        client, mock_http = feedback_client
        oversized = "A" * 2_800_001

        resp = client.post("/api/feedback", json={
            "category": "bug",
            "message": "Test",
            "screenshot_base64": oversized,
        })
        assert resp.status_code == 422
        mock_http.post.assert_not_called()
