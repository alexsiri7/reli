"""Shared httpx client — managed by the app lifespan to prevent resource leaks.

Usage in endpoints:
    from ..http_client import get_http_client

    @router.get("/example")
    async def example(client: httpx.AsyncClient = Depends(get_http_client)):
        resp = await client.get("https://example.com")
"""

import httpx
from fastapi import Request


def get_http_client(request: Request) -> httpx.AsyncClient:
    """FastAPI dependency that returns the shared httpx.AsyncClient."""
    client: httpx.AsyncClient = request.app.state.httpx_client
    return client
