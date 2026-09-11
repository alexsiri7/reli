"""What the assembled app routes where."""


def test_healthz_reports_ok(client):
    """staging-pipeline.yml greps this body and the Dockerfile HEALTHCHECK fetches this path."""
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "reli"}


def test_the_google_callback_is_routed_before_the_api_catch_all(client):
    """A 400 from the callback itself: not the catch-all's 404, and not the Basic check's 401."""
    response = client.get("/api/auth/google/callback", params={"state": "nope"})

    assert response.status_code == 400


def test_bare_mcp_is_redirected_to_the_slash_path_ahead_of_the_mount(client):
    response = client.post("/mcp", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].endswith("/mcp/")
