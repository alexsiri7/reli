"""Google Custom Search integration for web search capability."""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .settings import settings

logger = logging.getLogger(__name__)

GOOGLE_SEARCH_API_KEY = settings.google_search_api_key
GOOGLE_SEARCH_CX = settings.google_search_cx

GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


def is_search_configured() -> bool:
    """Check if Google Search API credentials are configured."""
    return bool(GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX)


async def google_search(query: str, num_results: int = 5) -> list[SearchResult]:
    """Search Google using the Custom Search JSON API.

    Returns up to `num_results` results. Returns empty list on failure or
    if credentials are not configured.
    """
    if not is_search_configured():
        logger.warning("Google Search not configured — set GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX")
        return []

    params: dict[str, Any] = {
        "key": GOOGLE_SEARCH_API_KEY,
        "cx": GOOGLE_SEARCH_CX,
        "q": query,
        "num": min(num_results, 10),  # API max is 10
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(GOOGLE_SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("Google Search API error: %s %s", e.response.status_code, e.response.text[:200])
        return []
    except httpx.RequestError as e:
        logger.error("Google Search request failed: %s", e)
        return []

    results: list[SearchResult] = []
    for item in data.get("items", []):
        results.append(
            SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
            )
        )

    return results
