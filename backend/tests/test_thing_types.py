"""Tests for Thing Types CRUD endpoints."""

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_type(client: TestClient, **kwargs) -> dict:
    payload = {"name": "custom-type", "icon": "🔧", **kwargs}
    resp = client.post("/api/thing-types", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# List (seeded defaults)
# ---------------------------------------------------------------------------


class TestListThingTypes:
    def test_list_returns_seeded_defaults(self, client):
        resp = client.get("/api/thing-types")
        assert resp.status_code == 200
        data = resp.json()
        names = {t["name"] for t in data}
        assert "task" in names
        assert "note" in names
        assert "project" in names
        assert "person" in names
        assert len(data) >= 11  # 11 default types

    def test_list_pagination(self, client):
        resp = client.get("/api/thing-types?limit=3&offset=0")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

        resp2 = client.get("/api/thing-types?limit=3&offset=3")
        assert resp2.status_code == 200
        assert len(resp2.json()) == 3

        # No overlap
        ids1 = {t["id"] for t in resp.json()}
        ids2 = {t["id"] for t in resp2.json()}
        assert ids1.isdisjoint(ids2)

    def test_list_ordered_by_name(self, client):
        resp = client.get("/api/thing-types")
        data = resp.json()
        names = [t["name"] for t in data]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------


class TestGetThingType:
    def test_get_existing(self, client):
        # "task" is a seeded default with id="task"
        resp = client.get("/api/thing-types/task")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "task"
        assert data["icon"] == "📋"

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/api/thing-types/does-not-exist")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreateThingType:
    def test_create_minimal(self, client):
        data = create_type(client, name="widget")
        assert data["name"] == "widget"
        assert data["id"]
        assert data["icon"] == "🔧"
        assert data["created_at"]

    def test_create_with_all_fields(self, client):
        resp = client.post(
            "/api/thing-types",
            json={
                "name": "fancy",
                "icon": "✨",
                "color": "#ff0000",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "fancy"
        assert data["icon"] == "✨"
        assert data["color"] == "#ff0000"

    def test_create_default_icon(self, client):
        resp = client.post("/api/thing-types", json={"name": "plain"})
        assert resp.status_code == 201
        assert resp.json()["icon"] == "📌"

    def test_create_duplicate_name_returns_409(self, client):
        create_type(client, name="unique-type")
        resp = client.post("/api/thing-types", json={"name": "unique-type"})
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_create_duplicate_seeded_name_returns_409(self, client):
        resp = client.post("/api/thing-types", json={"name": "task"})
        assert resp.status_code == 409

    def test_create_empty_name_returns_422(self, client):
        resp = client.post("/api/thing-types", json={"name": ""})
        assert resp.status_code == 422

    def test_create_name_too_long_returns_422(self, client):
        resp = client.post("/api/thing-types", json={"name": "x" * 101})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Update (PATCH)
# ---------------------------------------------------------------------------


class TestUpdateThingType:
    def test_update_name(self, client):
        t = create_type(client, name="old-name")
        resp = client.patch(f"/api/thing-types/{t['id']}", json={"name": "new-name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "new-name"

    def test_update_icon(self, client):
        t = create_type(client, name="icon-test")
        resp = client.patch(f"/api/thing-types/{t['id']}", json={"icon": "🚀"})
        assert resp.status_code == 200
        assert resp.json()["icon"] == "🚀"

    def test_update_color(self, client):
        t = create_type(client, name="color-test")
        resp = client.patch(f"/api/thing-types/{t['id']}", json={"color": "#00ff00"})
        assert resp.status_code == 200
        assert resp.json()["color"] == "#00ff00"

    def test_update_no_fields_returns_unchanged(self, client):
        t = create_type(client, name="no-change")
        resp = client.patch(f"/api/thing-types/{t['id']}", json={})
        assert resp.status_code == 200
        assert resp.json()["name"] == "no-change"

    def test_update_nonexistent_returns_404(self, client):
        resp = client.patch("/api/thing-types/no-such-id", json={"name": "ghost"})
        assert resp.status_code == 404

    def test_update_duplicate_name_returns_409(self, client):
        create_type(client, name="first")
        t2 = create_type(client, name="second")
        resp = client.patch(f"/api/thing-types/{t2['id']}", json={"name": "first"})
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_update_same_name_succeeds(self, client):
        """Renaming to the same name should not conflict with itself."""
        t = create_type(client, name="keep-same")
        resp = client.patch(f"/api/thing-types/{t['id']}", json={"name": "keep-same"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "keep-same"


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDeleteThingType:
    def test_delete_existing(self, client):
        t = create_type(client, name="delete-me")
        resp = client.delete(f"/api/thing-types/{t['id']}")
        assert resp.status_code == 204
        # Confirm gone
        assert client.get(f"/api/thing-types/{t['id']}").status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/thing-types/not-here")
        assert resp.status_code == 404

    def test_delete_seeded_type(self, client):
        """Seeded types can be deleted."""
        resp = client.delete("/api/thing-types/task")
        assert resp.status_code == 204
        assert client.get("/api/thing-types/task").status_code == 404
