"""Tests for Thing Types CRUD endpoints."""

from collections.abc import Generator
from contextlib import contextmanager

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_type(client: TestClient, **kwargs) -> dict:
    payload = {"name": "custom-type", "icon": "🔧", **kwargs}
    resp = client.post("/api/thing-types", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


@contextmanager
def _auth_client(user_id: str) -> Generator[TestClient, None, None]:
    """Context manager: TestClient with require_user overridden to return user_id.

    Use sequentially (not simultaneously) per the NOTE in conftest._make_authenticated_client —
    app.dependency_overrides is a shared dict and only one override can be active at a time.
    """
    from backend.auth import require_user
    from backend.main import app

    saved = app.dependency_overrides.get(require_user)
    app.dependency_overrides[require_user] = lambda: user_id
    try:
        with TestClient(app) as c:
            yield c
    finally:
        if saved is None:
            app.dependency_overrides.pop(require_user, None)
        else:
            app.dependency_overrides[require_user] = saved


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

    def test_create_seeded_name_allowed_for_user(self, client):
        """Users can create a type with the same name as a system type (different scope)."""
        resp = client.post("/api/thing-types", json={"name": "task"})
        assert resp.status_code == 201

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

    def test_delete_seeded_type_forbidden(self, client):
        """System-seeded types (user_id=NULL) cannot be deleted by a user."""
        resp = client.delete("/api/thing-types/task")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# User Isolation (cross-user security invariants)
# ---------------------------------------------------------------------------


class TestUserIsolation:
    """Verify that per-user scoping prevents cross-user access.

    Uses _auth_client() context manager sequentially — app.dependency_overrides
    is a shared dict; only one user override can be active at a time.
    """

    def test_other_user_cannot_see_private_type(self, patched_db):
        with _auth_client("user-a") as c:
            t = create_type(c, name="private-a")
        with _auth_client("other-user") as c:
            resp = c.get(f"/api/thing-types/{t['id']}")
            assert resp.status_code == 404

    def test_other_user_cannot_update_private_type(self, patched_db):
        with _auth_client("user-a") as c:
            t = create_type(c, name="private-b")
        with _auth_client("other-user") as c:
            resp = c.patch(f"/api/thing-types/{t['id']}", json={"name": "hijacked"})
            assert resp.status_code == 404

    def test_other_user_cannot_delete_private_type(self, patched_db):
        with _auth_client("user-a") as c:
            t = create_type(c, name="private-c")
        with _auth_client("other-user") as c:
            resp = c.delete(f"/api/thing-types/{t['id']}")
            assert resp.status_code == 404

    def test_other_user_cannot_see_private_type_in_list(self, patched_db):
        with _auth_client("user-a") as c:
            create_type(c, name="list-private")
        with _auth_client("other-user") as c:
            resp = c.get("/api/thing-types")
            names = {t["name"] for t in resp.json()}
            assert "list-private" not in names

    def test_system_types_visible_to_all(self, patched_db):
        """NULL user_id types are visible to every authenticated user."""
        for uid in ("user-a", "other-user"):
            with _auth_client(uid) as c:
                resp = c.get("/api/thing-types/task")
                assert resp.status_code == 200

    def test_two_users_can_have_same_type_name(self, patched_db):
        """Per-user uniqueness: two users may both own a type with the same name."""
        with _auth_client("user-a") as c:
            resp_a = c.post("/api/thing-types", json={"name": "widget"})
            assert resp_a.status_code == 201
        with _auth_client("other-user") as c:
            resp_b = c.post("/api/thing-types", json={"name": "widget"})
            assert resp_b.status_code == 201
        assert resp_a.json()["id"] != resp_b.json()["id"]

    def test_authenticated_user_cannot_update_system_type(self, patched_db):
        """Authenticated user gets 404 when patching a system type (user_id=NULL)."""
        with _auth_client("user-a") as c:
            resp = c.patch("/api/thing-types/task", json={"name": "hacked"})
            assert resp.status_code == 404

    def test_authenticated_user_cannot_delete_system_type(self, patched_db):
        """Authenticated user gets 404 when deleting a system type (user_id=NULL)."""
        with _auth_client("user-a") as c:
            resp = c.delete("/api/thing-types/task")
            assert resp.status_code == 404

    def test_authenticated_user_can_read_system_type(self, patched_db):
        """Authenticated user can still GET a system type (user_id=NULL is included)."""
        with _auth_client("user-a") as c:
            resp = c.get("/api/thing-types/task")
            assert resp.status_code == 200
            assert resp.json()["name"] == "task"

    def test_update_to_name_used_by_other_user_succeeds(self, patched_db):
        """Renaming to a name owned by a different user should not conflict."""
        with _auth_client("other-user") as c:
            c.post("/api/thing-types", json={"name": "shared-name"})
        with _auth_client("user-a") as c:
            t = create_type(c, name="my-name")
            resp = c.patch(f"/api/thing-types/{t['id']}", json={"name": "shared-name"})
            assert resp.status_code == 200
            assert resp.json()["name"] == "shared-name"
