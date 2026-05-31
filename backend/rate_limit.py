"""In-memory rate limiting middleware for FastAPI.

Uses a simple token-bucket algorithm per user (via JWT) with IP fallback.
Three tiers:
- **LLM endpoints** (chat, sweep): strict limits to prevent cost amplification
- **Auth endpoints** (login, OAuth): stricter-than-API limits to prevent abuse
- **General API**: more lenient limits for normal usage

When a valid JWT session cookie is present the ``sub`` claim is used as the
rate-limit key so that users behind the same reverse proxy (Railway /
Cloudflare) each get their own bucket.  Unauthenticated requests (login,
health, etc.) fall back to client IP.

Configurable via environment variables:
- ``RATE_LIMIT_ENABLED``: "true" (default) or "false"
- ``RATE_LIMIT_LLM_RPM``: requests per minute for LLM endpoints (default: 30)
- ``RATE_LIMIT_AUTH_RPM``: requests per minute for auth endpoints (default: 10)
- ``RATE_LIMIT_API_RPM``: requests per minute for general API (default: 60)
"""

from __future__ import annotations

import ipaddress
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

log = logging.getLogger(__name__)

# LLM-calling paths that need strict rate limiting
_LLM_PATHS = {"/api/chat", "/api/chat/stream", "/api/sweep/run", "/api/sweep/gaps", "/api/sweep/connections"}

# Auth paths (login, OAuth flows) — rated separately to prevent credential-abuse.
# Default: stricter than general API (auth_rpm=10 vs api_rpm=60).
# NOTE: /oauth/token is intentionally excluded — MCP token refresh needs
# separate investigation before a rate limit is applied.
_AUTH_PATHS = {
    "/api/auth/google",
    "/api/auth/google/callback",
    "/api/auth/me",
    "/api/logout",
    "/oauth/authorize",
    "/oauth/register",
}



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
    """Per-user (JWT) / per-IP token-bucket rate limiter."""

    def __init__(  # type: ignore[no-untyped-def]
        self,
        app,
        *,
        llm_rpm: int = 30,
        auth_rpm: int = 10,
        api_rpm: int = 60,
        enabled: bool = True,
        trusted_proxy_cidrs: str = "",
    ) -> None:
        super().__init__(app)
        self.enabled = enabled
        self.llm_rpm = llm_rpm
        self.auth_rpm = auth_rpm
        self.api_rpm = api_rpm
        # Parse CIDR strings into network objects once at startup
        self._trusted_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for raw in trusted_proxy_cidrs.split(","):
            cidr = raw.strip()
            if not cidr:
                continue
            try:
                self._trusted_networks.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                log.warning("Invalid TRUSTED_PROXY_CIDR entry ignored: %r", cidr)
        # Separate buckets for LLM, auth, and general API, keyed by user id or IP
        self._llm_buckets: dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(tokens=float(llm_rpm), max_tokens=float(llm_rpm), refill_rate=llm_rpm / 60.0)
        )
        self._auth_buckets: dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(tokens=float(auth_rpm), max_tokens=float(auth_rpm), refill_rate=auth_rpm / 60.0)
        )
        self._api_buckets: dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(tokens=float(api_rpm), max_tokens=float(api_rpm), refill_rate=api_rpm / 60.0)
        )

    def _get_client_ip(self, request: Request) -> str:
        direct_ip = request.client.host if request.client else None
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded and direct_ip and self._trusted_networks:
            try:
                addr = ipaddress.ip_address(direct_ip)
                if any(addr in net for net in self._trusted_networks):
                    return forwarded.split(",")[0].strip()
            except ValueError:
                log.debug("Could not parse direct IP %r; ignoring X-Forwarded-For", direct_ip)
        return direct_ip or "unknown"

    def _get_rate_limit_key(self, request: Request) -> str:
        """Derive the rate-limit key from the JWT session cookie.

        If a valid JWT cookie is present, the ``sub`` claim (user id) is
        returned so each authenticated user gets their own bucket.
        Otherwise falls back to client IP (for unauthenticated endpoints
        like login or when behind a reverse proxy without a cookie).
        """
        from backend.auth import COOKIE_NAME, JWT_ALGORITHM, SECRET_KEY

        token = request.cookies.get(COOKIE_NAME)
        if token and SECRET_KEY:
            try:
                import jwt as pyjwt

                payload = pyjwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
                sub = payload.get("sub")
                if sub:
                    return f"user:{sub}"
            except Exception:
                log.debug("JWT decode failed for rate-limit key; falling back to IP")
        return f"ip:{self._get_client_ip(request)}"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self.enabled:
            return await call_next(request)

        path = request.url.path

        # Skip rate limiting for health checks and static assets only
        if path == "/healthz" or path.startswith("/assets/"):
            return await call_next(request)

        key = self._get_rate_limit_key(request)
        is_llm = path in _LLM_PATHS
        is_auth = path in _AUTH_PATHS
        if is_llm:
            bucket = self._llm_buckets[key]
        elif is_auth:
            bucket = self._auth_buckets[key]
        else:
            bucket = self._api_buckets[key]

        if not bucket.consume():
            retry_after = int(bucket.retry_after) + 1
            log.warning("Rate limit exceeded: key=%s path=%s retry_after=%ds", key, path, retry_after)
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
        if is_llm:
            limit = self.llm_rpm
        elif is_auth:
            limit = self.auth_rpm
        else:
            limit = self.api_rpm
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(int(bucket.tokens))

        return response


def get_rate_limit_config() -> dict:
    """Read rate limit configuration from settings.

    Constructs a fresh Settings instance so that tests can override env vars
    per test case via monkeypatch.
    """
    from .config import Settings

    s = Settings()
    return {
        "enabled": s.rate_limit_enabled_bool,
        "llm_rpm": max(1, s.RATE_LIMIT_LLM_RPM),
        "auth_rpm": max(1, s.RATE_LIMIT_AUTH_RPM),
        "api_rpm": max(1, s.RATE_LIMIT_API_RPM),
        "trusted_proxy_cidrs": s.RATE_LIMIT_TRUSTED_PROXY_CIDRS,
    }
