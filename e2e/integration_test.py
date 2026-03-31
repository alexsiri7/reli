"""E2E integration tests for Reli API.

Run against a live server:
    BASE_URL=http://localhost:8000 RELI_API_TOKEN=<token> pytest e2e/ -v
"""

import uuid

import httpx
import pytest


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------


class TestHealth:
    def test_healthz(self, client: httpx.Client) -> None:
        """GET /healthz returns basic health status."""
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

    def test_detailed_health(self, client: httpx.Client) -> None:
        """GET /api/health returns detailed health with DB info."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body


# ---------------------------------------------------------------------------
# Things CRUD
# ---------------------------------------------------------------------------


class TestThingsAPI:
    def test_list_things_valid_response(self, client: httpx.Client) -> None:
        """GET /api/things returns a list (may be empty)."""
        resp = client.get("/api/things")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_crud_lifecycle(self, client: httpx.Client) -> None:
        """Full create -> read -> update -> delete lifecycle."""
        tag = uuid.uuid4().hex[:8]
        title = f"E2E Test Thing {tag}"

        # CREATE
        create_resp = client.post(
            "/api/things",
            json={
                "title": title,
                "type_hint": "task",
                "importance": 3,
                "data": {"source": "e2e-test", "tag": tag},
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        created = create_resp.json()
        thing_id = created["id"]
        assert created["title"] == title
        assert created["type_hint"] == "task"
        assert created["importance"] == 3

        try:
            # VERIFY IN LIST
            list_resp = client.get("/api/things", params={"active_only": "false"})
            assert list_resp.status_code == 200
            ids_in_list = [t["id"] for t in list_resp.json()]
            assert thing_id in ids_in_list

            # UPDATE (PATCH)
            updated_title = f"E2E Updated {tag}"
            patch_resp = client.patch(
                f"/api/things/{thing_id}",
                json={"title": updated_title, "importance": 1},
            )
            assert patch_resp.status_code == 200, patch_resp.text
            patched = patch_resp.json()
            assert patched["title"] == updated_title
            assert patched["importance"] == 1

            # GET single
            get_resp = client.get(f"/api/things/{thing_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["title"] == updated_title

        finally:
            # DELETE (always clean up)
            del_resp = client.delete(f"/api/things/{thing_id}")
            assert del_resp.status_code == 204

        # VERIFY GONE
        gone_resp = client.get(f"/api/things/{thing_id}")
        assert gone_resp.status_code == 404
