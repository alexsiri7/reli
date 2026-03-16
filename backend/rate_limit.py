"""In-memory rate limiting middleware for FastAPI.

Uses a simple token-bucket algorithm per client IP. Two tiers:
- **LLM endpoints** (chat, sweep): strict limits to prevent cost amplification
- **General API**: more lenient limits for normal usage

Configurable via environment variables:
- ``RATE_LIMIT_ENABLED``: "true" (default) or "false"
- ``RATE_LIMIT_LLM_RPM``: requests per minute for LLM endpoints (default: 10)
- ``RATE_LIMIT_API_RPM``: requests per minute for general API (default: 60)
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from .settings import settings

# LLM-calling paths that need strict rate limiting
_LLM_PATHS = {"/api/chat", "/api/sweep/run"}


def _is_llm_path(path: str) -> bool:
    return path in _LLM_PATHS


@dataclass
class _Bucket:
    """Token bucket for a single client."""

    tokens: float
    max_tokens: float
    refill_rate: float  # tokens per second
    last_refill: float = field(default_factory=time.monotonic)

    def consume(self) -> bool:
        """Try to consume one token.  Returns True if allowed."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    @property
    def retry_after(self) -> float:
        """Seconds until a token is available."""
        if self.tokens >= 1.0:
            return 0.0
        return (1.0 - self.tokens) / self.refill_rate


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP token-bucket rate limiter."""

    def __init__(self, app, *, llm_rpm: int = 10, api_rpm: int = 60, enabled: bool = True) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.enabled = enabled
        self.llm_rpm = llm_rpm
        self.api_rpm = api_rpm
        # Separate buckets for LLM and general API per client IP
        self._llm_buckets: dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(tokens=float(llm_rpm), max_tokens=float(llm_rpm), refill_rate=llm_rpm / 60.0)
        )
        self._api_buckets: dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(tokens=float(api_rpm), max_tokens=float(api_rpm), refill_rate=api_rpm / 60.0)
        )

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self.enabled:
            return await call_next(request)

        path = request.url.path

        # Skip rate limiting for health checks and static assets
        if path in ("/healthz", "/metrics") or path.startswith("/assets") or not path.startswith("/api"):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        is_llm = _is_llm_path(path)
        bucket = self._llm_buckets[client_ip] if is_llm else self._api_buckets[client_ip]

        if not bucket.consume():
            retry_after = int(bucket.retry_after) + 1
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Please try again later.",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        response = await call_next(request)

        # Add rate limit headers for visibility
        response.headers["X-RateLimit-Limit"] = str(self.llm_rpm if is_llm else self.api_rpm)
        response.headers["X-RateLimit-Remaining"] = str(int(bucket.tokens))

        return response


def get_rate_limit_config() -> dict:
    """Read rate limit configuration from settings."""
    return {
        "enabled": settings.rate_limit_is_enabled,
        "llm_rpm": max(1, settings.rate_limit_llm_rpm),
        "api_rpm": max(1, settings.rate_limit_api_rpm),
    }
