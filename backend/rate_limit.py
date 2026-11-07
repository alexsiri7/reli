"""Per-tier token-bucket rate limiting for every route that is not a static asset (#1475).

Three tiers, each a per-minute limit from :mod:`backend.config`:

- ``registration`` — ``/oauth/register``, the one store an anonymous caller grows;
- ``auth`` — the rest of ``/oauth/`` and ``/api/auth/``, the paths a caller reaches to obtain or end
  a credential;
- ``api`` — ``/api``, ``/mcp`` and ``/.well-known/``.

Everything else — ``/healthz``, the bundle and its fallback — is exempt and gets no headers.

An ``api`` request presenting a JWT this Reli signed (the session cookie or an ``/mcp`` bearer) is
keyed by its subject, so the owner never shares a bucket with an attacker behind the same proxy.
Every other request is keyed by its client address: the peer, unless the peer is inside
``TRUSTED_PROXY_CIDRS``, in which case the rightmost ``X-Forwarded-For`` entry that is not itself a
trusted proxy. A token revoked by logout or naming an account no longer in ``ALLOWED_EMAILS`` is
keyed by address like any other caller, so a stolen copy cannot spend its owner's bucket.

The buckets live in this process and are lost on restart; the image runs one uvicorn process.
"""

from __future__ import annotations

import ipaddress
import logging
import math
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import NamedTuple

import jwt
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import api, auth
from .config import settings

logger = logging.getLogger(__name__)

#: How many buckets are held before the least recently used is dropped. A flood of fresh keys then
#: hands an evicted key a full bucket again rather than growing memory without bound.
MAX_BUCKETS = 10_000


class Tier(NamedTuple):
    name: str
    limit: int


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated: float
    throttled: bool = False


_BUCKETS: OrderedDict[tuple[str, str], _Bucket] = OrderedDict()


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def tier_for(path: str) -> Tier | None:
    """The tier *path* is counted in, or ``None`` when it is exempt."""
    if path == "/oauth/register":
        return Tier("registration", settings.RATE_LIMIT_REGISTRATION_PER_MINUTE)
    if path.startswith(("/oauth/", f"{auth.router.prefix}/")):
        return Tier("auth", settings.RATE_LIMIT_AUTH_PER_MINUTE)
    if _under(path, api.router.prefix) or _under(path, "/mcp") or path.startswith("/.well-known/"):
        return Tier("api", settings.RATE_LIMIT_API_PER_MINUTE)
    return None


def _is_trusted_proxy(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in settings.trusted_proxy_networks)


def client_address(scope: Scope) -> str:
    """The address a request is keyed by when it carries no credential of Reli's."""
    client = scope.get("client")
    peer: str = client[0] if client else "unknown"
    if not _is_trusted_proxy(peer):
        return peer
    hops: list[str] = [
        hop.strip()
        for name, value in scope.get("headers", [])
        if name == b"x-forwarded-for"
        for hop in value.decode("latin-1").split(",")
        if hop.strip()
    ]
    if not hops:
        return peer
    for hop in reversed(hops):
        if not _is_trusted_proxy(hop):
            return hop
    return hops[0]


async def _user_subject(scope: Scope) -> str | None:
    """The subject of a session cookie or ``/mcp`` bearer the auth layers would admit, else ``None``."""
    if not settings.secret_key_configured:
        return None
    try:
        claims = await run_in_threadpool(auth.web_session, Request(scope))
    except auth.SessionRefused:
        claims = None
    if claims is not None:
        return str(claims["sub"])
    authorization = dict(scope.get("headers", [])).get(b"authorization", b"").decode("latin-1")
    if not authorization.startswith("Bearer "):
        return None
    try:
        claims = auth.decode_jwt(authorization[7:], auth.MCP_AUDIENCE)
    except jwt.PyJWTError:
        return None
    if auth.is_allowed(str(claims.get("email", ""))) and not await run_in_threadpool(auth.is_revoked, claims):
        return str(claims["sub"])
    return None


def _take(tier: Tier, key: str, now: float) -> tuple[bool, int, int]:
    """Spend one token from *key*'s bucket in *tier*: whether allowed, tokens left, and seconds to retry."""
    rate = tier.limit / 60
    bucket = _BUCKETS.get((tier.name, key))
    if bucket is None:
        bucket = _BUCKETS[(tier.name, key)] = _Bucket(tokens=tier.limit, updated=now)
        if len(_BUCKETS) > MAX_BUCKETS:
            _BUCKETS.popitem(last=False)
    else:
        _BUCKETS.move_to_end((tier.name, key))
        bucket.tokens = min(tier.limit, bucket.tokens + (now - bucket.updated) * rate)
        bucket.updated = now

    if bucket.tokens >= 1:
        bucket.tokens -= 1
        bucket.throttled = False
        return True, math.floor(bucket.tokens), 0

    if not bucket.throttled:
        bucket.throttled = True
        # The kind only: neither an address nor a subject belongs in a log this repository's owner
        # does not control.
        logger.warning("rate limit reached: tier=%s key=%s", tier.name, key.partition(":")[0])
    return False, 0, max(1, math.ceil((1 - bucket.tokens) / rate))


class RateLimit:
    """Counts each request against its tier's bucket and answers 429 once the bucket is empty.

    Raw ASGI, like ``_SecurityHeaders`` in :mod:`backend.main`, so the streamable-HTTP responses
    under ``/mcp`` are not buffered.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        tier = tier_for(scope.get("path", "")) if scope["type"] == "http" else None
        if tier is None:
            await self._app(scope, receive, send)
            return

        subject = await _user_subject(scope) if tier.name == "api" else None
        key = f"user:{subject}" if subject is not None else f"addr:{client_address(scope)}"
        allowed, remaining, retry_after = _take(tier, key, time.monotonic())
        headers = {"X-RateLimit-Limit": str(tier.limit), "X-RateLimit-Remaining": str(remaining)}

        if not allowed:
            response = JSONResponse(
                {"detail": f"Too many requests: retry after {retry_after} seconds."},
                status_code=429,
                headers={**headers, "Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).update(headers)
            await send(message)

        await self._app(scope, receive, send_with_headers)
