"""Smoke E2E tests for Reli API.

Run against a live server:
    BASE_URL=http://localhost:8000 RELI_API_TOKEN=<token> pytest e2e/ -v
"""

import httpx


class TestSmoke:
    def test_healthz(self, client: httpx.Client) -> None:
        """Basic health endpoint responds."""
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_detailed_health(self, client: httpx.Client) -> None:
        """Detailed health returns DB info."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "db" in body or "database" in body or body["status"] in ("ok", "degraded")

    def test_things_api_responds(self, client: httpx.Client) -> None:
        """Things API is reachable and returns a list."""
        resp = client.get("/api/things")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_auth_rejects_bad_token(self, base_url: str) -> None:
        """API rejects requests with invalid auth."""
        with httpx.Client(base_url=base_url, timeout=10.0) as c:
            resp = c.get("/api/things", headers={"Authorization": "Bearer bad-token"})
            assert resp.status_code == 401
