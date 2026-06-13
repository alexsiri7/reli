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
        monkeypatch.delenv("RATE_LIMIT_AUTH_RPM", raising=False)
        monkeypatch.delenv("RATE_LIMIT_REG_RPM", raising=False)
        monkeypatch.delenv("RATE_LIMIT_API_RPM", raising=False)
        config = get_rate_limit_config()
        assert config["enabled"] is True
        assert config["llm_rpm"] == 30
        assert config["auth_rpm"] == 10
        assert config["reg_rpm"] == 5
        assert config["api_rpm"] == 60

    def test_disabled(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
        config = get_rate_limit_config()
        assert config["enabled"] is False

    def test_custom_limits(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RATE_LIMIT_LLM_RPM", "5")
        monkeypatch.setenv("RATE_LIMIT_AUTH_RPM", "3")
        monkeypatch.setenv("RATE_LIMIT_REG_RPM", "3")
        monkeypatch.setenv("RATE_LIMIT_API_RPM", "30")
        config = get_rate_limit_config()
        assert config["llm_rpm"] == 5
        assert config["auth_rpm"] == 3
        assert config["reg_rpm"] == 3
        assert config["api_rpm"] == 30


# ---------------------------------------------------------------------------
# Integration tests with a minimal FastAPI app
# ---------------------------------------------------------------------------


def _make_app(llm_rpm: int = 3, auth_rpm: int = 5, reg_rpm: int = 5, api_rpm: int = 5) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, llm_rpm=llm_rpm, auth_rpm=auth_rpm, reg_rpm=reg_rpm, api_rpm=api_rpm, enabled=True)

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

    @app.get("/api/auth/google")
    def auth_google():
        return JSONResponse({"url": "https://accounts.google.com"})

    @app.get("/api/auth/me")
    def auth_me():
        return JSONResponse({"user": None})

    @app.post("/oauth/token")
    def oauth_token():
        return JSONResponse({"access_token": "tok"})

    @app.post("/oauth/register")
    def oauth_register():
        return JSONResponse({"client_id": "test"}, status_code=201)

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

    def test_x_forwarded_for_ignored_without_trusted_cidr(self):
        """X-Forwarded-For is ignored when no trusted CIDRs are configured."""
        app = _make_app(api_rpm=1)  # no trusted_proxy_cidrs
        client = TestClient(app)
        # Exhaust bucket for the real IP
        res = client.get("/api/things")
        assert res.status_code == 200
        # Spoofed header should NOT get a fresh bucket
        res = client.get("/api/things", headers={"X-Forwarded-For": "1.2.3.4"})
        assert res.status_code == 429

    def test_x_forwarded_for_trusted_from_known_proxy(self):
        """X-Forwarded-For is used when direct IP is within a trusted CIDR."""
        from starlette.types import ASGIApp, Receive, Scope, Send

        class _FakeClientIP:
            """ASGI middleware that overrides client IP for testing."""

            def __init__(self, app: ASGIApp, ip: str = "127.0.0.1") -> None:
                self.app = app
                self.ip = ip

            async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                if scope["type"] == "http":
                    scope["client"] = (self.ip, 0)
                await self.app(scope, receive, send)

        app = FastAPI()
        # RateLimitMiddleware is added first (outermost), then _FakeClientIP
        # wraps it so that by the time RateLimitMiddleware sees the request,
        # client.host is "127.0.0.1" instead of "testclient".
        app.add_middleware(
            RateLimitMiddleware,
            llm_rpm=3,
            api_rpm=1,
            enabled=True,
            trusted_proxy_cidrs="127.0.0.0/8",
        )
        app.add_middleware(_FakeClientIP, ip="127.0.0.1")

        @app.get("/api/things")
        def list_things():
            return JSONResponse({"items": []})

        client = TestClient(app)
        # First request from "1.1.1.1" via trusted proxy
        res = client.get("/api/things", headers={"X-Forwarded-For": "1.1.1.1"})
        assert res.status_code == 200
        # Second request from "1.1.1.1" hits its bucket (exhausted at rpm=1)
        res = client.get("/api/things", headers={"X-Forwarded-For": "1.1.1.1"})
        assert res.status_code == 429
        # Different spoofed IP gets its own fresh bucket
        res = client.get("/api/things", headers={"X-Forwarded-For": "2.2.2.2"})
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


class TestAuthRateLimit:
    def test_auth_endpoint_stricter_than_api(self):
        """Auth endpoints use auth_rpm bucket, not the api_rpm bucket."""
        app = _make_app(auth_rpm=2, api_rpm=100)
        client = TestClient(app)
        for _ in range(2):
            res = client.get("/api/auth/google")
            assert res.status_code == 200
        res = client.get("/api/auth/google")
        assert res.status_code == 429

    def test_auth_bucket_independent_of_api_bucket(self):
        """Exhausting the auth bucket doesn't affect the general API bucket."""
        app = _make_app(auth_rpm=1, api_rpm=10)
        client = TestClient(app)
        # Exhaust auth bucket
        client.get("/api/auth/google")
        res = client.get("/api/auth/google")
        assert res.status_code == 429
        # General API still works
        res = client.get("/api/things")
        assert res.status_code == 200

    def test_auth_rate_limit_headers(self):
        """X-RateLimit-Limit header reflects auth_rpm for auth endpoints."""
        app = _make_app(auth_rpm=7, api_rpm=100)
        client = TestClient(app)
        res = client.get("/api/auth/google")
        assert res.headers["X-RateLimit-Limit"] == "7"

    def test_auth_me_uses_auth_bucket(self):
        """Non-google auth paths such as /api/auth/me are also rate-limited by auth_rpm."""
        app = _make_app(auth_rpm=2, api_rpm=100)
        client = TestClient(app)
        for _ in range(2):
            res = client.get("/api/auth/me")
            assert res.status_code == 200
        res = client.get("/api/auth/me")
        assert res.status_code == 429

    def test_oauth_token_uses_auth_bucket(self):
        """/oauth/token uses auth_rpm bucket, not api_rpm."""
        app = _make_app(auth_rpm=2, api_rpm=100)
        client = TestClient(app)
        for _ in range(2):
            res = client.post("/oauth/token")
            assert res.status_code == 200
        res = client.post("/oauth/token")
        assert res.status_code == 429

    def test_oauth_token_rate_limit_header(self):
        """X-RateLimit-Limit reflects auth_rpm for /oauth/token."""
        app = _make_app(auth_rpm=7, api_rpm=100)
        client = TestClient(app)
        res = client.post("/oauth/token")
        assert res.headers["X-RateLimit-Limit"] == "7"


class TestRegistrationRateLimit:
    def test_oauth_register_uses_reg_bucket(self):
        """/oauth/register uses reg_rpm bucket, not auth_rpm."""
        app = _make_app(reg_rpm=2, auth_rpm=100, api_rpm=100)
        client = TestClient(app)
        for _ in range(2):
            res = client.post("/oauth/register", json={})
            assert res.status_code == 201
        res = client.post("/oauth/register", json={})
        assert res.status_code == 429

    def test_oauth_register_rate_limit_header(self):
        """X-RateLimit-Limit reflects reg_rpm for /oauth/register."""
        app = _make_app(reg_rpm=7, auth_rpm=3, api_rpm=100)
        client = TestClient(app)
        res = client.post("/oauth/register", json={})
        assert res.headers["X-RateLimit-Limit"] == "7"

    def test_oauth_register_does_not_consume_auth_bucket(self):
        """/oauth/register exhaustion does not block /oauth/token (separate buckets)."""
        app = _make_app(reg_rpm=1, auth_rpm=100, api_rpm=100)
        client = TestClient(app)
        # exhaust registration bucket
        client.post("/oauth/register", json={})
        res = client.post("/oauth/register", json={})
        assert res.status_code == 429
        # auth bucket unaffected
        res = client.post("/oauth/token")
        assert res.status_code == 200

    def test_get_rate_limit_config_includes_reg_rpm(self, monkeypatch):
        monkeypatch.delenv("RATE_LIMIT_REG_RPM", raising=False)
        config = get_rate_limit_config()
        assert config["reg_rpm"] == 5

    def test_get_rate_limit_config_custom_reg_rpm(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_REG_RPM", "2")
        config = get_rate_limit_config()
        assert config["reg_rpm"] == 2


# ---------------------------------------------------------------------------
# Bucket pruning tests
# ---------------------------------------------------------------------------


class TestBucketPruning:
    def test_prune_removes_stale_buckets(self, monkeypatch: pytest.MonkeyPatch):
        """Buckets inactive for longer than _BUCKET_TTL are removed."""
        import time as time_mod

        import backend.rate_limit as rl_mod

        fake_time = [1000.0]
        monkeypatch.setattr(time_mod, "monotonic", lambda: fake_time[0])
        monkeypatch.setattr(rl_mod, "_BUCKET_TTL", 60.0)

        # Construct middleware directly to avoid middleware-stack traversal issues
        mw = RateLimitMiddleware(app=FastAPI(), api_rpm=5, llm_rpm=3, auth_rpm=5)

        # Directly insert a bucket with last_refill at the current fake time
        mw._api_buckets["test_key"] = _Bucket(
            tokens=5.0, max_tokens=5.0, refill_rate=5.0 / 60.0, last_refill=fake_time[0]
        )
        assert len(mw._api_buckets) == 1

        # Advance clock past TTL
        fake_time[0] += 61.0
        mw._prune_stale_buckets()
        assert len(mw._api_buckets) == 0

    def test_prune_keeps_active_buckets(self, monkeypatch: pytest.MonkeyPatch):
        """Buckets that were recently active are NOT pruned."""
        import time as time_mod

        import backend.rate_limit as rl_mod

        fake_time = [1000.0]
        monkeypatch.setattr(time_mod, "monotonic", lambda: fake_time[0])
        monkeypatch.setattr(rl_mod, "_BUCKET_TTL", 60.0)

        mw = RateLimitMiddleware(app=FastAPI(), api_rpm=5, llm_rpm=3, auth_rpm=5)

        mw._api_buckets["test_key"] = _Bucket(
            tokens=5.0, max_tokens=5.0, refill_rate=5.0 / 60.0, last_refill=fake_time[0]
        )
        # Only 30s elapsed — bucket should survive
        fake_time[0] += 30.0
        mw._prune_stale_buckets()
        assert len(mw._api_buckets) == 1

    def test_dispatch_triggers_cleanup_after_interval(self, monkeypatch: pytest.MonkeyPatch):
        """dispatch() triggers _prune_stale_buckets once the cleanup interval elapses."""
        import time as time_mod
        from unittest.mock import MagicMock

        import backend.rate_limit as rl_mod

        fake_time = [1000.0]
        monkeypatch.setattr(time_mod, "monotonic", lambda: fake_time[0])
        monkeypatch.setattr(rl_mod, "_CLEANUP_INTERVAL", 10.0)

        app = _make_app(api_rpm=100)
        client = TestClient(app)

        # Patch at the class level so dispatch() calls the mock
        mock_prune = MagicMock()
        monkeypatch.setattr(RateLimitMiddleware, "_prune_stale_buckets", mock_prune)

        # First request — no cleanup yet (interval not elapsed)
        client.get("/api/things")
        mock_prune.assert_not_called()

        # Advance past interval
        fake_time[0] += 11.0
        client.get("/api/things")
        mock_prune.assert_called_once()

    def test_prune_removes_stale_buckets_in_all_dicts(self, monkeypatch: pytest.MonkeyPatch):
        """_prune_stale_buckets removes stale entries from all three bucket dicts."""
        import time as time_mod

        import backend.rate_limit as rl_mod

        fake_time = [1000.0]
        monkeypatch.setattr(time_mod, "monotonic", lambda: fake_time[0])
        monkeypatch.setattr(rl_mod, "_BUCKET_TTL", 60.0)

        mw = RateLimitMiddleware(app=FastAPI(), api_rpm=5, llm_rpm=3, auth_rpm=5)
        stale_bucket = _Bucket(tokens=1.0, max_tokens=1.0, refill_rate=1.0 / 60.0, last_refill=fake_time[0])

        mw._llm_buckets["llm_key"] = stale_bucket
        mw._auth_buckets["auth_key"] = stale_bucket
        mw._api_buckets["api_key"] = stale_bucket

        fake_time[0] += 61.0
        mw._prune_stale_buckets()

        assert len(mw._llm_buckets) == 0, "llm_buckets not pruned"
        assert len(mw._auth_buckets) == 0, "auth_buckets not pruned"
        assert len(mw._api_buckets) == 0, "api_buckets not pruned"

    def test_dispatch_does_not_retrigger_cleanup_within_interval(self, monkeypatch: pytest.MonkeyPatch):
        """After cleanup is triggered, subsequent requests within the interval do not re-trigger it."""
        import time as time_mod
        from unittest.mock import MagicMock

        import backend.rate_limit as rl_mod

        fake_time = [1000.0]
        monkeypatch.setattr(time_mod, "monotonic", lambda: fake_time[0])
        monkeypatch.setattr(rl_mod, "_CLEANUP_INTERVAL", 10.0)

        app = _make_app(api_rpm=100)
        client = TestClient(app)

        # Warm-up request to initialize the middleware stack and _last_cleanup at t=1000
        # (Starlette builds middleware lazily on the first request)
        mock_prune = MagicMock()
        monkeypatch.setattr(RateLimitMiddleware, "_prune_stale_buckets", mock_prune)
        client.get("/api/things")
        assert mock_prune.call_count == 0

        # Advance past the interval — cleanup should fire exactly once
        fake_time[0] += 11.0
        client.get("/api/things")
        assert mock_prune.call_count == 1

        # Several more requests within the new interval — no additional cleanup
        client.get("/api/things")
        client.get("/api/things")
        assert mock_prune.call_count == 1

    def test_prune_keeps_bucket_at_exact_ttl_boundary(self, monkeypatch: pytest.MonkeyPatch):
        """A bucket aged exactly _BUCKET_TTL seconds is NOT pruned (strict >)."""
        import time as time_mod

        import backend.rate_limit as rl_mod

        fake_time = [1000.0]
        monkeypatch.setattr(time_mod, "monotonic", lambda: fake_time[0])
        monkeypatch.setattr(rl_mod, "_BUCKET_TTL", 60.0)

        mw = RateLimitMiddleware(app=FastAPI(), api_rpm=5, llm_rpm=3, auth_rpm=5)
        mw._api_buckets["test_key"] = _Bucket(
            tokens=5.0, max_tokens=5.0, refill_rate=5.0 / 60.0, last_refill=fake_time[0]
        )
        # Advance by exactly TTL — should NOT be pruned (strict >)
        fake_time[0] += 60.0
        mw._prune_stale_buckets()
        assert len(mw._api_buckets) == 1


# ---------------------------------------------------------------------------
# Audience enforcement tests
# ---------------------------------------------------------------------------


class TestRateLimitKeyAudienceFallback:
    """An MCP-audience cookie in the session slot must fall through to IP-based key."""

    def test_rate_limit_key_falls_back_to_ip_for_mcp_cookie(self, monkeypatch):
        """MCP-audience JWT in the session cookie must not be accepted as a user key."""
        from unittest.mock import MagicMock

        import jwt

        import backend.rate_limit as rl_mod
        from backend.auth import JWT_ALGORITHM

        secret = "test-secret-key-rl"
        token = jwt.encode(
            {"sub": "u-mcp-user", "aud": "mcp", "exp": 9999999999},
            secret,
            algorithm=JWT_ALGORITHM,
        )
        monkeypatch.setattr(rl_mod, "SECRET_KEY", secret, raising=False)

        middleware = RateLimitMiddleware(app=FastAPI(), api_rpm=60, llm_rpm=30, auth_rpm=10)
        request = MagicMock()
        request.cookies.get.return_value = token
        request.client.host = "1.2.3.4"
        request.headers.get.return_value = ""

        import backend.auth as auth_mod

        monkeypatch.setattr(auth_mod, "SECRET_KEY", secret)

        key = middleware._get_rate_limit_key(request)
        assert key.startswith("ip:"), f"Expected IP fallback for MCP-aud token, got: {key}"
