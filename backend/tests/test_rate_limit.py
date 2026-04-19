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

    def test_refill(self, monkeypatch: pytest.MonkeyPatch):
        import time as time_mod

        fake_time = [1000.0]
        monkeypatch.setattr(time_mod, "monotonic", lambda: fake_time[0])

        bucket = _Bucket(tokens=1.0, max_tokens=2.0, refill_rate=100.0, last_refill=fake_time[0])
        assert bucket.consume() is True
        assert bucket.consume() is False

        # Advance fake clock by 0.05s → 5 tokens refilled (capped at max_tokens=2)
        fake_time[0] += 0.05
        assert bucket.consume() is True

    def test_retry_after(self):
        bucket = _Bucket(tokens=0.0, max_tokens=5.0, refill_rate=1.0)
        assert bucket.retry_after > 0
        assert bucket.retry_after <= 1.0

    def test_refill_caps_at_max_tokens(self, monkeypatch: pytest.MonkeyPatch):
        """After a long idle period, tokens should not exceed max_tokens."""
        import time as time_mod

        fake_time = [1000.0]
        monkeypatch.setattr(time_mod, "monotonic", lambda: fake_time[0])

        bucket = _Bucket(tokens=0.0, max_tokens=5.0, refill_rate=1.0, last_refill=fake_time[0])
        # Advance by 10x the refill period (600s for 5 tokens at 1/s)
        fake_time[0] += 600.0
        assert bucket.consume() is True
        # After consume, tokens should be capped at max_tokens - 1
        assert bucket.tokens <= 4.0

    def test_retry_after_returns_zero_when_tokens_available(self):
        """retry_after is 0 when tokens are available."""
        bucket = _Bucket(tokens=3.0, max_tokens=5.0, refill_rate=1.0)
        assert bucket.retry_after == 0.0


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestGetConfig:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
        monkeypatch.delenv("RATE_LIMIT_LLM_RPM", raising=False)
        monkeypatch.delenv("RATE_LIMIT_API_RPM", raising=False)
        config = get_rate_limit_config()
        assert config["enabled"] is True
        assert config["llm_rpm"] == 30
        assert config["api_rpm"] == 60

    def test_disabled(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
        config = get_rate_limit_config()
        assert config["enabled"] is False

    def test_custom_limits(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RATE_LIMIT_LLM_RPM", "5")
        monkeypatch.setenv("RATE_LIMIT_API_RPM", "30")
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

    @app.post("/api/chat/stream")
    def chat_stream():
        return JSONResponse({"reply": "hello"})

    @app.post("/api/sweep/run")
    def sweep():
        return JSONResponse({"findings": []})

    @app.post("/api/sweep/gaps")
    def sweep_gaps():
        return JSONResponse({"gaps": []})

    @app.post("/api/sweep/connections")
    def sweep_connections():
        return JSONResponse({"connections": []})

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

    def test_chat_and_stream_share_llm_bucket(self):
        app = _make_app(llm_rpm=2, api_rpm=100)
        client = TestClient(app)
        res = client.post("/api/chat")
        assert res.status_code == 200
        res = client.post("/api/chat/stream")
        assert res.status_code == 200
        # Third request to either chat path should be blocked
        res = client.post("/api/chat/stream")
        assert res.status_code == 429

    def test_chat_stream_endpoint_rate_limited(self):
        app = _make_app(llm_rpm=2, api_rpm=100)
        client = TestClient(app)
        for _ in range(2):
            res = client.post("/api/chat/stream")
            assert res.status_code == 200
        res = client.post("/api/chat/stream")
        assert res.status_code == 429

    def test_sweep_endpoint_rate_limited(self):
        app = _make_app(llm_rpm=1, api_rpm=100)
        client = TestClient(app)
        res = client.post("/api/sweep/run")
        assert res.status_code == 200
        res = client.post("/api/sweep/run")
        assert res.status_code == 429

    def test_sweep_gaps_endpoint_rate_limited(self):
        app = _make_app(llm_rpm=1, api_rpm=100)
        client = TestClient(app)
        res = client.post("/api/sweep/gaps")
        assert res.status_code == 200
        res = client.post("/api/sweep/gaps")
        assert res.status_code == 429

    def test_sweep_connections_endpoint_rate_limited(self):
        app = _make_app(llm_rpm=1, api_rpm=100)
        client = TestClient(app)
        res = client.post("/api/sweep/connections")
        assert res.status_code == 200
        res = client.post("/api/sweep/connections")
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

    def test_warning_logged_on_rate_limit_exceeded(self):
        """log.warning is emitted with key, path, and retry_after when rate limited."""
        from unittest.mock import patch

        app = _make_app(api_rpm=1)
        client = TestClient(app)

        # Exhaust the bucket
        res = client.get("/api/things")
        assert res.status_code == 200

        with patch("backend.rate_limit.log") as mock_log:
            res = client.get("/api/things")

        assert res.status_code == 429
        mock_log.warning.assert_called_once()
        call_args = mock_log.warning.call_args[0]
        assert "Rate limit exceeded" in call_args[0]
        assert "retry_after" in call_args[0]
