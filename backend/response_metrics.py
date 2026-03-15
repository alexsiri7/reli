"""Response time tracking middleware and metrics store."""

import logging
import time
from collections import deque
from dataclasses import dataclass, field

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

BUFFER_SIZE = 100


@dataclass
class MetricsStore:
    """In-memory ring buffer of recent API response times."""

    _buffer: deque[float] = field(default_factory=lambda: deque(maxlen=BUFFER_SIZE))
    _start_time: float = field(default_factory=time.monotonic)

    def record(self, duration_ms: float) -> None:
        self._buffer.append(duration_ms)

    def avg_response_time_ms(self) -> float | None:
        if not self._buffer:
            return None
        return sum(self._buffer) / len(self._buffer)

    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_time

    def request_count(self) -> int:
        return len(self._buffer)


# Singleton store shared across the app
metrics_store = MetricsStore()


class ResponseMetricsMiddleware(BaseHTTPMiddleware):
    """Logs method, path, status, and duration_ms for every request."""

    async def dispatch(  # type: ignore[override]
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.monotonic()
        response: Response = await call_next(request)  # type: ignore[misc]
        duration_ms = (time.monotonic() - start) * 1000

        metrics_store.record(duration_ms)

        logger.info(
            "%s %s %d %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
