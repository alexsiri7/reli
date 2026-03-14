"""Tests for Things CRUD endpoints."""

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_thing(client: TestClient, **kwargs) -> dict:
    payload = {"title": "Test Thing", **kwargs}
    resp = client.post("/api/things", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class TestCreateThing:
    def test_create_minimal(self, client):
        data = create_thing(client, title="My Task")
        assert data["title"] == "My Task"
        assert data["id"]
        assert data["active"] is True
        assert data["priority"] == 3

    def test_create_full(self, client):
        payload = {
            "title": "Full Thing",
            "type_hint": "task",
            "priority": 1,
            "active": True,
            "checkin_date": "2026-03-15T00:00:00",
            "data": {"notes": "some notes"},
        }
        resp = client.post("/api/things", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["type_hint"] == "task"
        assert data["priority"] == 1
        assert data["data"] == {"notes": "some notes"}

    def test_create_with_valid_parent(self, client):
        parent = create_thing(client, title="Parent")
        child = create_thing(client, title="Child", parent_id=parent["id"])
        assert child["parent_id"] == parent["id"]

    def test_create_with_invalid_parent_returns_404(self, client):
        resp = client.post("/api/things", json={"title": "Orphan", "parent_id": "nonexistent-id"})
        assert resp.status_code == 404

    def test_create_empty_title_returns_422(self, client):
        resp = client.post("/api/things", json={"title": ""})
        assert resp.status_code == 422

    def test_create_title_too_long_returns_422(self, client):
        resp = client.post("/api/things", json={"title": "x" * 501})
        assert resp.status_code == 422

    def test_create_invalid_priority_returns_422(self, client):
        resp = client.post("/api/things", json={"title": "Bad Priority", "priority": 10})
        assert resp.status_code == 422

    def test_create_upserts_vector_store(self, client, mock_vector_store):
        create_thing(client, title="Vector Thing")
        # upsert is called via background task; TestClient flushes bg tasks
        mock_vector_store["upsert"].assert_called_once()


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class TestListThings:
    def test_list_empty(self, client):
        resp = client.get("/api/things")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_returns_active_only_by_default(self, client):
        create_thing(client, title="Active")
        inactive_id = create_thing(client, title="Inactive")["id"]
        client.patch(f"/api/things/{inactive_id}", json={"active": False})

        resp = client.get("/api/things")
        titles = [t["title"] for t in resp.json()]
        assert "Active" in titles
        assert "Inactive" not in titles

    def test_list_active_only_false_returns_all(self, client):
        create_thing(client, title="Active")
        inactive_id = create_thing(client, title="Inactive")["id"]
        client.patch(f"/api/things/{inactive_id}", json={"active": False})

        resp = client.get("/api/things?active_only=false")
        titles = [t["title"] for t in resp.json()]
        assert "Active" in titles
        assert "Inactive" in titles

    def test_list_pagination(self, client):
        for i in range(5):
            create_thing(client, title=f"Thing {i}")

        resp = client.get("/api/things?limit=2&offset=0")
        assert len(resp.json()) == 2

        resp2 = client.get("/api/things?limit=2&offset=2")
        assert len(resp2.json()) == 2


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------

class TestGetThing:
    def test_get_existing(self, client):
        created = create_thing(client, title="Fetch Me")
        resp = client.get(f"/api/things/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Fetch Me"

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/api/things/does-not-exist")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Update (PATCH)
# ---------------------------------------------------------------------------

class TestUpdateThing:
    def test_update_title(self, client):
        thing = create_thing(client, title="Old Title")
        resp = client.patch(f"/api/things/{thing['id']}", json={"title": "New Title"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    def test_update_priority(self, client):
        thing = create_thing(client, title="Low Priority")
        resp = client.patch(f"/api/things/{thing['id']}", json={"priority": 1})
        assert resp.status_code == 200
        assert resp.json()["priority"] == 1

    def test_update_active_false(self, client):
        thing = create_thing(client, title="To Archive")
        resp = client.patch(f"/api/things/{thing['id']}", json={"active": False})
        assert resp.status_code == 200
        assert resp.json()["active"] is False

    def test_update_nonexistent_returns_404(self, client):
        resp = client.patch("/api/things/no-such-id", json={"title": "Ghost"})
        assert resp.status_code == 404

    def test_update_self_parent_returns_422(self, client):
        thing = create_thing(client, title="Self Loop")
        resp = client.patch(f"/api/things/{thing['id']}", json={"parent_id": thing["id"]})
        assert resp.status_code == 422

    def test_update_invalid_parent_returns_404(self, client):
        thing = create_thing(client, title="Lost Child")
        resp = client.patch(f"/api/things/{thing['id']}", json={"parent_id": "ghost-parent"})
        assert resp.status_code == 404

    def test_update_upserts_vector_store(self, client, mock_vector_store):
        thing = create_thing(client, title="VS Thing")
        mock_vector_store["upsert"].reset_mock()
        client.patch(f"/api/things/{thing['id']}", json={"title": "VS Updated"})
        mock_vector_store["upsert"].assert_called_once()


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

class TestDeleteThing:
    def test_delete_existing(self, client):
        thing = create_thing(client, title="Delete Me")
        resp = client.delete(f"/api/things/{thing['id']}")
        assert resp.status_code == 204
        # Confirm gone
        assert client.get(f"/api/things/{thing['id']}").status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/things/not-here")
        assert resp.status_code == 404

    def test_delete_calls_vector_store(self, client, mock_vector_store):
        thing = create_thing(client, title="Delete VS")
        mock_vector_store["delete"].reset_mock()
        client.delete(f"/api/things/{thing['id']}")
        mock_vector_store["delete"].assert_called_once_with(thing["id"])
