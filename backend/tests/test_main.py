"""What the assembled app routes where."""

import logging
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.config import settings


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
    assert response.headers["Cache-Control"] == "no-store"


def test_an_unhandled_exception_500_off_the_api_stays_cacheable(monkeypatch):
    """The handler sends the 500 itself, so it must make the same /api choice the middleware does."""
    from backend.main import app

    def boom() -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(auth, "base_url", boom)

    response = TestClient(app, raise_server_exceptions=False).get("/.well-known/oauth-authorization-server")

    assert response.status_code == 500
    _assert_security_headers(response)
    assert "Cache-Control" not in response.headers


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/api/things", id="web-view-401-sent-by-its-own-middleware"),
        pytest.param("/api/auth/me", id="public-auth-route"),
        pytest.param("/api/nowhere", id="unmatched-api-path"),
    ],
)
def test_every_api_response_is_no_store(client, path):
    """#1709: the graph and the signed-in identity must not outlive the session in any cache, and a
    refusal is no exception."""
    assert client.get(path).headers["Cache-Control"] == "no-store"


def test_a_served_graph_is_no_store(client, monkeypatch):
    """The 200 that carries the graph, not only the refusals around it."""
    monkeypatch.setattr(settings, "SECRET_KEY", "a-test-secret-key-that-is-forty-eight-chars-long")
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "owner@example.com")
    token = auth.create_jwt("1234567890", "owner@example.com", audience=auth.WEB_AUDIENCE)

    response = client.get("/api/things", headers={"Cookie": f"{auth.SESSION_COOKIE}={token}"})

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("path", ["/healthz", "/mcp/", "/.well-known/oauth-authorization-server"])
def test_no_store_stays_off_what_is_not_the_api(client, path):
    """``/oauth/`` sets its own and nothing else here carries the graph."""
    assert "Cache-Control" not in client.get(path).headers


def _assert_security_headers(response) -> None:
    assert response.headers["Content-Security-Policy"] == "default-src 'self'; frame-ancestors 'none'"
    assert "unsafe-inline" not in response.headers["Content-Security-Policy"]
    assert response.headers["Strict-Transport-Security"] == "max-age=63072000; includeSubDomains"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    granted = [
        directive for directive in response.headers["Permissions-Policy"].split(", ") if not directive.endswith("=()")
    ]
    assert not granted, f"Permissions-Policy grants {granted}"
    assert "camera=()" in response.headers["Permissions-Policy"]


# A fresh interpreter, because the app is built once at import and its lifespan may run only once per
# process. The lifespan is not entered, so no database is reached. The bundle at argv[1] stands in for
# the frontend build every image ships, whose fallback answers any path nothing else claims.
_DOCS_PROBE = """
import pathlib, sys
from fastapi.testclient import TestClient
from backend import frontend_serving
mount_frontend = frontend_serving.mount_frontend
frontend_serving.mount_frontend = lambda app, _dist: mount_frontend(app, pathlib.Path(sys.argv[1]))
from backend.main import app
client = TestClient(app)
print(*(client.get(path).status_code for path in ("/openapi.json", "/docs", "/redoc")))
"""


@pytest.mark.parametrize(
    ("switch", "expected"),
    [
        pytest.param({"RAILWAY_ENVIRONMENT_NAME": "production"}, ["404"] * 3, id="deploy"),
        pytest.param({"HIDE_API_DOCS": "1"}, ["404"] * 3, id="hide-api-docs"),
        pytest.param({}, ["200"] * 3, id="local-run"),
    ],
)
def test_the_api_docs_are_404_in_a_deploy_and_served_locally(tmp_path, switch, expected):
    """#1476: a deploy serves no schema and no Swagger or ReDoc page, even with the bundle's fallback
    behind them; a local uvicorn keeps all three."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>Reli</title>")
    switches = {"RAILWAY_ENVIRONMENT_NAME", "PRODUCTION", "HIDE_API_DOCS"}
    env = {key: value for key, value in os.environ.items() if key not in switches}
    probe = subprocess.run(
        [sys.executable, "-c", _DOCS_PROBE, str(tmp_path)],
        env={**env, **switch},
        capture_output=True,
        text=True,
        check=True,
    )

    assert probe.stdout.split() == expected


def test_the_access_log_carries_no_query_string():
    """#1713: Google delivers ``code`` and ``state`` on the callback's URL, and uvicorn's access log
    writes the request target of every request. Served by uvicorn's CLI as the image serves it, so the line under
    test is the one uvicorn really writes after its own logging setup. The lifespan is off so no
    database is needed; the filter does not look at which route answered."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(port), "--lifespan", "off"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(300):
            if server.poll() is not None:
                break
            try:
                httpx.get(f"{base}/healthz")
                break
            except httpx.TransportError:
                time.sleep(0.1)
        started = server.poll() is None
        response = (
            httpx.get(f"{base}/healthz", params={"code": "c0de-secret", "state": "st4te-secret"}) if started else None
        )
    finally:
        server.terminate()
        log, _ = server.communicate(timeout=30)

    assert started, f"uvicorn exited before answering /healthz on port {port}:\n{log}"
    assert response is not None and response.status_code == 200
    assert log.count('"GET /healthz HTTP/1.1" 200') == 2
    assert "c0de-secret" not in log
    assert "st4te-secret" not in log


@pytest.mark.parametrize(
    ("log_level", "expected"),
    [
        ("DEBUG", (logging.DEBUG, logging.INFO, logging.INFO, logging.INFO)),
        (None, (logging.INFO, logging.INFO, logging.INFO, logging.INFO)),
        ("WARNING", (logging.WARNING, logging.WARNING, logging.WARNING, logging.WARNING)),
    ],
)
def test_log_level_below_info_reaches_only_the_backend_loggers(log_level, expected):
    """#1714: on the root logger LOG_LEVEL=DEBUG would turn on httpx's debug output too, and that
    carries the Google sign-in exchange. Reli's own loggers still go to DEBUG, stay at INFO when it
    is unset, and a level above INFO quiets everything."""
    env = {k: v for k, v in os.environ.items() if k != "LOG_LEVEL"}
    if log_level is not None:
        env["LOG_LEVEL"] = log_level
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import logging, backend.main; print(*(logging.getLogger(n).getEffectiveLevel() for n in "
            "('backend.auth', 'httpx', 'httpcore', 'root')))",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert probe.stdout.split() == [str(level) for level in expected]
