"""Tests for rate limiting middleware."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from backend.rate_limit import RateLimitMiddleware, _Bucket, get_rate_limit_config

# ---------------------------------------------------------------------------
# Bucket unit tests
# ---------------------------------------------------------------------------


class TestBucket:
    def test_consume_within_limit(self):
        bucket = _Bucket(tokens=5.0, max_tokens=5.0, refill_rate=1.0)
        for _ in range(5):
            assert bucket.consume() is True
        assert bucket.consume() is False

    def test_refill(self):
        import time

        bucket = _Bucket(tokens=1.0, max_tokens=2.0, refill_rate=100.0)  # fast refill
        assert bucket.consume() is True
        assert bucket.consume() is False
        time.sleep(0.05)  # wait for refill
        assert bucket.consume() is True

    def test_retry_after(self):
        bucket = _Bucket(tokens=0.0, max_tokens=5.0, refill_rate=1.0)
        assert bucket.retry_after > 0
        assert bucket.retry_after <= 1.0


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestGetConfig:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch):
        from backend.config import settings

        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        monkeypatch.setattr(settings, "rate_limit_llm_rpm", 10)
        monkeypatch.setattr(settings, "rate_limit_api_rpm", 60)
        config = get_rate_limit_config()
        assert config["enabled"] is True
        assert config["llm_rpm"] == 10
        assert config["api_rpm"] == 60

    def test_disabled(self, monkeypatch: pytest.MonkeyPatch):
        from backend.config import settings

        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        config = get_rate_limit_config()
        assert config["enabled"] is False

    def test_custom_limits(self, monkeypatch: pytest.MonkeyPatch):
        from backend.config import settings

        monkeypatch.setattr(settings, "rate_limit_llm_rpm", 5)
        monkeypatch.setattr(settings, "rate_limit_api_rpm", 30)
        config = get_rate_limit_config()
        assert config["llm_rpm"] == 5
        assert config["api_rpm"] == 30


# ---------------------------------------------------------------------------
# Integration tests with a minimal FastAPI app
# ---------------------------------------------------------------------------


def _make_app(llm_rpm: int = 3, api_rpm: int = 5) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, llm_rpm=llm_rpm, api_rpm=api_rpm, enabled=True)

    @app.get("/api/things")
    def list_things():
        return JSONResponse({"items": []})

    @app.post("/api/chat")
    def chat():
        return JSONResponse({"reply": "hello"})

    @app.post("/api/sweep/run")
    def sweep():
        return JSONResponse({"findings": []})

    @app.get("/healthz")
    def health():
        return JSONResponse({"status": "ok"})

    return app


class TestRateLimitMiddleware:
    def test_allows_within_limit(self):
        app = _make_app(api_rpm=5)
        client = TestClient(app)
        for _ in range(5):
            res = client.get("/api/things")
            assert res.status_code == 200

    def test_blocks_over_limit(self):
        app = _make_app(api_rpm=3)
        client = TestClient(app)
        for _ in range(3):
            res = client.get("/api/things")
            assert res.status_code == 200
        res = client.get("/api/things")
        assert res.status_code == 429
        assert "retry_after" in res.json()
        assert "Retry-After" in res.headers

    def test_llm_endpoint_stricter(self):
        app = _make_app(llm_rpm=2, api_rpm=100)
        client = TestClient(app)
        for _ in range(2):
            res = client.post("/api/chat")
            assert res.status_code == 200
        res = client.post("/api/chat")
        assert res.status_code == 429

    def test_sweep_endpoint_rate_limited(self):
        app = _make_app(llm_rpm=1, api_rpm=100)
        client = TestClient(app)
        res = client.post("/api/sweep/run")
        assert res.status_code == 200
        res = client.post("/api/sweep/run")
        assert res.status_code == 429

    def test_healthz_not_limited(self):
        app = _make_app(api_rpm=1)
        client = TestClient(app)
        for _ in range(10):
            res = client.get("/healthz")
            assert res.status_code == 200

    def test_rate_limit_headers(self):
        app = _make_app(api_rpm=10)
        client = TestClient(app)
        res = client.get("/api/things")
        assert "X-RateLimit-Limit" in res.headers
        assert "X-RateLimit-Remaining" in res.headers

    def test_disabled_middleware(self):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, llm_rpm=1, api_rpm=1, enabled=False)

        @app.post("/api/chat")
        def chat():
            return JSONResponse({"reply": "hello"})

        client = TestClient(app)
        for _ in range(10):
            res = client.post("/api/chat")
            assert res.status_code == 200
