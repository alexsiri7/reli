"""What the assembled app routes where."""

import pytest


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
