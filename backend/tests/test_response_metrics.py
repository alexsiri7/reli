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
        """Verify the middleware is active by checking it records timings."""
        fresh_store = MetricsStore()
        with patch("backend.response_metrics.metrics_store", fresh_store):
            for _ in range(3):
                client.get("/healthz")
        assert fresh_store.request_count() == 3
        assert fresh_store.avg_response_time_ms() is not None


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
        assert body["avg_response_time_ms"] is None or body["avg_response_time_ms"] > 0
        assert isinstance(body["recent_request_count"], int)

    def test_health_db_connected(self, client):
        resp = client.get("/api/health")
        body = resp.json()
        assert body["db_connected"] is True
        assert body["status"] == "ok"

    def test_health_db_failure_shows_degraded(self, client):
        import backend.db_engine as _engine_mod
        with patch.object(_engine_mod.engine, "connect", side_effect=Exception("db down")):
            resp = client.get("/api/health")
        body = resp.json()
        assert body["db_connected"] is False
        assert body["status"] == "degraded"
