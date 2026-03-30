"""Tests for the /metrics endpoint and Prometheus instrumentation."""

from unittest.mock import patch

from fastapi.testclient import TestClient


class TestMetricsEndpoint:
    """The /metrics endpoint returns Prometheus text exposition."""

    def test_returns_200(self, client: TestClient):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]

    def test_contains_request_count(self, client: TestClient):
        # Hit healthz first to generate a counter
        client.get("/healthz")
        resp = client.get("/metrics")
        body = resp.text
        assert "http_requests_total" in body

    def test_contains_request_duration(self, client: TestClient):
        client.get("/healthz")
        resp = client.get("/metrics")
        assert "http_request_duration_seconds" in resp.text

    def test_contains_vector_count(self, client: TestClient):
        resp = client.get("/metrics")
        assert "vector_count" in resp.text

    def test_contains_db_things_total(self, client: TestClient):
        resp = client.get("/metrics")
        assert "db_things_total" in resp.text

    def test_contains_db_users_total(self, client: TestClient):
        resp = client.get("/metrics")
        assert "db_users_total" in resp.text

    def test_no_auth_required(self, patched_db):
        """The /metrics endpoint must be accessible without a session cookie."""
        from backend.main import app

        with TestClient(app) as c:
            resp = c.get("/metrics")
            assert resp.status_code == 200


class TestPathNormalization:
    """Dynamic path segments are collapsed to avoid label explosion."""

    def test_thing_detail_collapsed(self, client: TestClient):
        # A thing detail URL should be collapsed to /api/things
        client.get("/api/things/some-uuid-123")
        resp = client.get("/metrics")
        body = resp.text
        assert 'path="/api/things"' in body

    def test_unknown_paths_collapsed(self, client: TestClient):
        client.get("/unknown/route")
        resp = client.get("/metrics")
        body = resp.text
        assert 'path="/other"' in body


class TestMetricsMiddleware:
    """The middleware correctly increments counters."""

    def test_status_codes_tracked(self, client: TestClient):
        client.get("/healthz")
        resp = client.get("/metrics")
        body = resp.text
        assert 'status="200"' in body

    def test_methods_tracked(self, client: TestClient):
        client.get("/healthz")
        resp = client.get("/metrics")
        body = resp.text
        assert 'method="GET"' in body


class TestGaugeRefresh:
    """Gauge values are refreshed from live data on each /metrics call."""

    def test_vector_count_uses_vector_store(self, client: TestClient):
        with patch("backend.vector_store.vector_count", return_value=42):
            resp = client.get("/metrics")
        assert "vector_count 42.0" in resp.text

    def test_db_counts_reflect_data(self, client: TestClient):
        # The patched_db is empty, so counts should be 0
        resp = client.get("/metrics")
        assert "db_things_total 0.0" in resp.text
        assert "db_users_total 0.0" in resp.text
