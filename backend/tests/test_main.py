"""What the assembled app routes where."""

import pytest
from fastapi.testclient import TestClient

from backend import auth


def test_healthz_reports_ok(client):
    """staging-pipeline.yml greps this body and the Dockerfile HEALTHCHECK fetches this path."""
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "reli"}


def test_the_google_callback_is_routed_before_the_api_catch_all(client):
    """A 400 from the callback itself: not the catch-all's 404, and not the Basic check's 401."""
    response = client.get("/api/auth/google/callback", params={"state": "nope"})

    assert response.status_code == 400


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
def test_bare_mcp_is_served_by_the_mount_and_never_redirected(client, method):
    """The claude.ai connector POSTs /mcp and follows a 307 without its bearer, so a redirect is a
    401 on the second hop and an "Authorization with Reli failed" for the user (#1450). The bare path
    must get the mount's own answer — here the bearer check's 401 — with no 3xx in between."""
    bare = client.request(method, "/mcp", follow_redirects=False)
    canonical = client.request(method, "/mcp/", follow_redirects=False)

    assert not 300 <= bare.status_code < 400
    assert "location" not in bare.headers
    assert bare.status_code == canonical.status_code == 401
    assert bare.json() == canonical.json()
    assert bare.headers["WWW-Authenticate"] == canonical.headers["WWW-Authenticate"]


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/healthz", id="route"),
        pytest.param("/api/things", id="web-view-401-sent-by-its-own-middleware"),
        pytest.param("/mcp/", id="mount-401"),
    ],
)
def test_every_response_carries_the_security_headers(client, path):
    """#1527: one policy on every surface, including the responses that never reach a route — the web
    view's middleware answers its own 401 before anything inside it runs, and the /mcp mount's bearer
    check answers its own."""
    _assert_security_headers(client.get(path))


def test_an_unhandled_exception_500_carries_the_security_headers(monkeypatch):
    """Starlette's ``ServerErrorMiddleware`` wraps every ``add_middleware`` layer and sends its
    fallback 500 through the raw ``send``, past ``_SecurityHeaders``; the registered handler is what
    puts the headers on that response. A bare client, because the session one re-raises server
    exceptions and the app's lifespan may run only once."""
    from backend.main import app

    def boom() -> list[str]:
        raise RuntimeError("boom")

    monkeypatch.setattr(auth, "missing_sign_in_settings", boom)

    response = TestClient(app, raise_server_exceptions=False).get("/api/auth/google")

    assert response.status_code == 500
    _assert_security_headers(response)


def _assert_security_headers(response) -> None:
    assert response.headers["Content-Security-Policy"] == "default-src 'self'; frame-ancestors 'none'"
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "same-origin"
