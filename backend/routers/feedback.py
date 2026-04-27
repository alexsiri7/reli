"""Feedback endpoint: creates GitHub issues with app context."""

import base64
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import require_user
from ..config import settings
from ..http_client import get_http_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    """User feedback submission."""

    category: str = Field(description="bug, feature, or other")
    message: str = Field(min_length=1, max_length=5000)
    user_agent: str = ""
    url: str = ""
    screenshot_base64: str | None = None


class FeedbackResponse(BaseModel):
    """Response after submitting feedback."""

    success: bool
    issue_url: str | None = None
    message: str = ""


def _category_label(category: str) -> str:
    labels = {"bug": "bug", "feature": "enhancement"}
    return labels.get(category, "feedback")


@router.post("", response_model=FeedbackResponse, summary="Submit feedback")
async def submit_feedback(
    body: FeedbackRequest,
    user_id: str = Depends(require_user),
    client: httpx.AsyncClient = Depends(get_http_client),
) -> FeedbackResponse:
    """Create a GitHub issue with the user's feedback and app context."""
    token = settings.GITHUB_FEEDBACK_TOKEN
    repo = settings.GITHUB_FEEDBACK_REPO

    if not token or not repo:
        raise HTTPException(
            status_code=501,
            detail="Feedback is not configured. GITHUB_FEEDBACK_TOKEN and GITHUB_FEEDBACK_REPO must be set.",
        )

    # Build issue body with context
    context_lines = []
    if body.user_agent:
        context_lines.append(f"**Browser:** {body.user_agent}")
    if body.url:
        context_lines.append(f"**Page:** {body.url}")
    if user_id:
        context_lines.append(f"**User:** {user_id}")

    context_section = "\n".join(context_lines)
    issue_body = f"{body.message}\n\n---\n\n{context_section}" if context_lines else body.message

    # Upload screenshot to GitHub CDN if provided
    screenshot_url: str | None = None
    if body.screenshot_base64 and token and repo:
        try:
            image_data = base64.b64decode(body.screenshot_base64)
            upload_resp = await client.post(
                f"https://uploads.github.com/repos/{repo}/issues/uploads",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "Content-Type": "image/jpeg",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                content=image_data,
                timeout=30.0,
            )
            upload_resp.raise_for_status()
            screenshot_url = upload_resp.json().get("url")
        except Exception as exc:
            logger.warning("Failed to upload screenshot to GitHub CDN: %s", exc)

    if screenshot_url:
        issue_body += f"\n\n## Screenshot\n\n![Screenshot]({screenshot_url})"

    # Map category to title prefix
    prefix_map = {"bug": "Bug", "feature": "Feature request", "other": "Feedback"}
    title_prefix = prefix_map.get(body.category, "Feedback")

    # Truncate message for title (first line, max 80 chars)
    first_line = body.message.split("\n")[0].strip()
    title_summary = first_line[:80] + ("..." if len(first_line) > 80 else "")
    title = f"[{title_prefix}] {title_summary}"

    label = _category_label(body.category)

    try:
        resp = await client.post(
            f"https://api.github.com/repos/{repo}/issues",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "title": title,
                "body": issue_body,
                "labels": [label],
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return FeedbackResponse(
            success=True,
            issue_url=data.get("html_url"),
            message="Feedback submitted successfully.",
        )
    except httpx.HTTPStatusError as exc:
        logger.error("GitHub API error creating feedback issue: %s %s", exc.response.status_code, exc.response.text)
        raise HTTPException(status_code=502, detail="Failed to create feedback issue on GitHub.") from exc
    except Exception as exc:
        logger.error("Failed to submit feedback: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to submit feedback.") from exc
