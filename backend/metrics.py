"""Prometheus-compatible /metrics endpoint and request instrumentation."""

from __future__ import annotations

import time

from fastapi import Request, Response
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response as StarletteResponse

# Use a custom registry so we don't collide with default process/platform
# collectors in tests (and to keep output focused on app metrics).
REGISTRY = CollectorRegistry()

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests by method, path, and status code.",
    ["method", "path", "status"],
    registry=REGISTRY,
)

REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

CHROMA_VECTOR_COUNT = Gauge(
    "chroma_vector_count",
    "Number of vectors indexed in ChromaDB.",
    registry=REGISTRY,
)

DB_THINGS_COUNT = Gauge(
    "db_things_total",
    "Total number of Things stored in SQLite.",
    registry=REGISTRY,
)

DB_USERS_COUNT = Gauge(
    "db_users_total",
    "Total number of registered users.",
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Path normalization (avoid high-cardinality labels)
# ---------------------------------------------------------------------------

_KNOWN_PREFIXES = (
    "/api/things",
    "/api/thing-types",
    "/api/briefing",
    "/api/chat",
    "/api/gmail",
    "/api/calendar",
    "/api/proactive",
    "/api/settings",
    "/api/sweep",
    "/api/auth",
)


def _normalize_path(path: str) -> str:
    """Collapse dynamic path segments to avoid label explosion."""
    for prefix in _KNOWN_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return prefix
    if path in ("/healthz", "/metrics"):
        return path
    return "/other"


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request count and duration for every HTTP request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = _normalize_path(request.url.path)
        method = request.method

        start = time.monotonic()
        response = await call_next(request)
        elapsed = time.monotonic() - start

        REQUEST_COUNT.labels(method=method, path=path, status=str(response.status_code)).inc()
        REQUEST_DURATION.labels(method=method, path=path).observe(elapsed)

        return response


# ---------------------------------------------------------------------------
# /metrics endpoint helper
# ---------------------------------------------------------------------------


def _refresh_gauges() -> None:
    """Update gauge values from live data sources."""
    # ChromaDB vector count
    try:
        from .vector_store import vector_count

        CHROMA_VECTOR_COUNT.set(vector_count())
    except Exception:
        pass

    # SQLite stats (no connection pool — just counts)
    try:
        from sqlalchemy import func
        from sqlmodel import Session, select

        import backend.db_engine as _engine_mod
        from .db_models import ThingRecord, UserRecord

        with Session(_engine_mod.engine) as session:
            things = session.exec(select(func.count()).select_from(ThingRecord)).one()
            DB_THINGS_COUNT.set(things)
            users = session.exec(select(func.count()).select_from(UserRecord)).one()
            DB_USERS_COUNT.set(users)
    except Exception:
        pass


def metrics_response() -> StarletteResponse:
    """Generate the Prometheus text exposition response."""
    _refresh_gauges()
    body = generate_latest(REGISTRY)
    return StarletteResponse(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
