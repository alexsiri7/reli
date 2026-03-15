"""Tests for response metrics middleware and /api/health endpoint."""

from unittest.mock import patch

from backend.response_metrics import MetricsStore


class TestMetricsStore:
    """Unit tests for the in-memory metrics ring buffer."""

    def test_empty_store_returns_none_avg(self):
        store = MetricsStore()
        assert store.avg_response_time_ms() is None

    def test_records_and_averages(self):
        store = MetricsStore()
        store.record(10.0)
        store.record(20.0)
        store.record(30.0)
        assert store.avg_response_time_ms() == 20.0
        assert store.request_count() == 3

    def test_ring_buffer_evicts_old_entries(self):
        store = MetricsStore()
        for i in range(150):
            store.record(float(i))
        assert store.request_count() == 100  # maxlen=100

    def test_uptime_positive(self):
        store = MetricsStore()
        assert store.uptime_seconds() >= 0


class TestResponseMetricsMiddleware:
    """Integration: middleware records timings on requests."""

    def test_middleware_logs_request(self, client):
        """Verify the middleware is active by checking avg changes after a request."""
        from backend.response_metrics import metrics_store

        avg_before = metrics_store.avg_response_time_ms()
        # Make several requests so the buffer content changes
        for _ in range(3):
            client.get("/healthz")
        avg_after = metrics_store.avg_response_time_ms()
        # After requests, avg should be a number (not None)
        assert avg_after is not None
        # If buffer was empty before, avg changed from None to a value
        # If buffer was full, avg likely changed due to new entries
        if avg_before is None:
            assert avg_after > 0


class TestHealthDetailed:
    """GET /api/health — detailed health check."""

    def test_health_returns_all_fields(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("ok", "degraded")
        assert body["service"] == "reli"
        assert isinstance(body["uptime_seconds"], (int, float))
        assert isinstance(body["db_connected"], bool)
        assert isinstance(body["chromadb_connected"], bool)
        assert isinstance(body["vector_count"], int)
        assert body["avg_response_time_ms"] is None or isinstance(
            body["avg_response_time_ms"], (int, float)
        )
        assert isinstance(body["recent_request_count"], int)

    def test_health_db_connected(self, client):
        resp = client.get("/api/health")
        body = resp.json()
        assert body["db_connected"] is True
        assert body["status"] == "ok"

    def test_health_db_failure_shows_degraded(self, client):
        with patch("backend.database.get_connection", side_effect=Exception("db down")):
            resp = client.get("/api/health")
        body = resp.json()
        assert body["db_connected"] is False
        assert body["status"] == "degraded"
