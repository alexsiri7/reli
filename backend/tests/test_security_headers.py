"""Tests for SecurityHeadersMiddleware — CSP and security header regression guards."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from backend.main import SecurityHeadersMiddleware


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/probe")
    def probe():
        return JSONResponse({"ok": True})

    return app


class TestSecurityHeadersMiddleware:
    @pytest.fixture()
    def client(self):
        return TestClient(_make_app())

    def test_csp_header_excludes_unsafe_inline_from_style_src(self, client):
        """style-src must not contain 'unsafe-inline' (SEC-033 regression guard)."""
        res = client.get("/probe")
        csp = res.headers["Content-Security-Policy"]
        assert "style-src 'self'" in csp
        assert "'unsafe-inline'" not in csp

    def test_csp_header_full_value(self, client):
        """Pin the entire CSP string to catch any future accidental directive change."""
        res = client.get("/probe")
        expected = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data: blob: https://*.googleusercontent.com; "
            "connect-src 'self'; "
            "font-src 'self'; "
            "frame-ancestors 'none'"
        )
        assert res.headers["Content-Security-Policy"] == expected

    def test_other_security_headers_present(self, client):
        """Verify all security headers are set (no header accidentally dropped)."""
        res = client.get("/probe")
        assert res.headers["X-Content-Type-Options"] == "nosniff"
        assert res.headers["X-Frame-Options"] == "DENY"
        assert "max-age=63072000" in res.headers["Strict-Transport-Security"]
        assert res.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert res.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
