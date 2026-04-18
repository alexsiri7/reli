"""Tests for Things CRUD endpoints."""

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
        assert data["importance"] == 2

    def test_create_full(self, client):
        payload = {
            "title": "Full Thing",
            "type_hint": "task",
            "importance": 0,
            "active": True,
            "checkin_date": "2026-03-15T00:00:00",
            "data": {"notes": "some notes"},
        }
        resp = client.post("/api/things", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["type_hint"] == "task"
        assert data["importance"] == 0
        assert data["data"] == {"notes": "some notes"}

    def test_create_empty_title_returns_422(self, client):
        resp = client.post("/api/things", json={"title": ""})
        assert resp.status_code == 422

    def test_create_title_too_long_returns_422(self, client):
        resp = client.post("/api/things", json={"title": "x" * 501})
        assert resp.status_code == 422

    def test_create_invalid_importance_returns_422(self, client):
        resp = client.post("/api/things", json={"title": "Bad Importance", "importance": 10})
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

    def test_update_importance(self, client):
        thing = create_thing(client, title="Low Importance")
        resp = client.patch(f"/api/things/{thing['id']}", json={"importance": 0})
        assert resp.status_code == 200
        assert resp.json()["importance"] == 0

    def test_update_active_false(self, client):
        thing = create_thing(client, title="To Archive")
        resp = client.patch(f"/api/things/{thing['id']}", json={"active": False})
        assert resp.status_code == 200
        assert resp.json()["active"] is False

    def test_update_nonexistent_returns_404(self, client):
        resp = client.patch("/api/things/no-such-id", json={"title": "Ghost"})
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


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


class TestGetGraph:
    def test_graph_empty(self, client):
        resp = client.get("/api/things/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []
        assert data["edges"] == []

    def test_graph_returns_active_nodes(self, client):
        t1 = create_thing(client, title="Active Node", type_hint="task")
        t2 = create_thing(client, title="Inactive Node")
        client.patch(f"/api/things/{t2['id']}", json={"active": False})

        resp = client.get("/api/things/graph")
        assert resp.status_code == 200
        data = resp.json()
        node_ids = [n["id"] for n in data["nodes"]]
        assert t1["id"] in node_ids
        assert t2["id"] not in node_ids

    def test_graph_returns_edges(self, client):
        t1 = create_thing(client, title="Node A")
        t2 = create_thing(client, title="Node B")
        rel = client.post(
            "/api/things/relationships",
            json={"from_thing_id": t1["id"], "to_thing_id": t2["id"], "relationship_type": "related_to"},
        )
        assert rel.status_code == 201

        resp = client.get("/api/things/graph")
        data = resp.json()
        assert len(data["edges"]) == 1
        edge = data["edges"][0]
        assert edge["source"] == t1["id"]
        assert edge["target"] == t2["id"]
        assert edge["relationship_type"] == "related_to"

    def test_graph_excludes_edges_to_inactive_nodes(self, client):
        t1 = create_thing(client, title="Active")
        t2 = create_thing(client, title="Will Deactivate")
        client.post(
            "/api/things/relationships",
            json={"from_thing_id": t1["id"], "to_thing_id": t2["id"], "relationship_type": "knows"},
        )
        client.patch(f"/api/things/{t2['id']}", json={"active": False})

        resp = client.get("/api/things/graph")
        data = resp.json()
        assert len(data["edges"]) == 0

    def test_graph_node_has_icon_from_thing_type(self, client):
        # Create a thing type first
        client.post("/api/thing-types", json={"name": "person", "icon": "👤"})
        t = create_thing(client, title="Alice", type_hint="person")

        resp = client.get("/api/things/graph")
        data = resp.json()
        node = next(n for n in data["nodes"] if n["id"] == t["id"])
        assert node["icon"] == "👤"
        assert node["type_hint"] == "person"


# ---------------------------------------------------------------------------
# Orphan Relationships
# ---------------------------------------------------------------------------


def _insert_orphan_relationship(db, from_id: str, to_id: str, rel_type: str = "orphan_link") -> str:
    """Directly insert a relationship bypassing FK validation (simulates orphan)."""
    import uuid

    rel_id = str(uuid.uuid4())
    with db() as conn:
        # Temporarily disable FK constraints to insert an orphan
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type) VALUES (?, ?, ?, ?)",
            (rel_id, from_id, to_id, rel_type),
        )
        conn.execute("PRAGMA foreign_keys=ON")
    return rel_id


class TestOrphanRelationships:
    def test_orphans_empty(self, client):
        resp = client.get("/api/things/relationships/orphans")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_orphans_detects_missing_to_thing(self, client, db):
        t1 = create_thing(client, title="Existing")
        _insert_orphan_relationship(db, t1["id"], "nonexistent-id")

        resp = client.get("/api/things/relationships/orphans")
        assert resp.status_code == 200
        orphans = resp.json()
        assert len(orphans) == 1
        assert orphans[0]["to_thing_id"] == "nonexistent-id"

    def test_orphans_detects_missing_from_thing(self, client, db):
        t1 = create_thing(client, title="Existing")
        _insert_orphan_relationship(db, "nonexistent-id", t1["id"])

        resp = client.get("/api/things/relationships/orphans")
        orphans = resp.json()
        assert len(orphans) == 1
        assert orphans[0]["from_thing_id"] == "nonexistent-id"

    def test_valid_relationship_not_reported_as_orphan(self, client):
        t1 = create_thing(client, title="A")
        t2 = create_thing(client, title="B")
        client.post(
            "/api/things/relationships",
            json={"from_thing_id": t1["id"], "to_thing_id": t2["id"], "relationship_type": "related_to"},
        )

        resp = client.get("/api/things/relationships/orphans")
        assert resp.json() == []

    def test_cleanup_deletes_orphans(self, client, db):
        t1 = create_thing(client, title="Keeper")
        orphan_id = _insert_orphan_relationship(db, t1["id"], "ghost-thing")

        resp = client.post("/api/things/relationships/cleanup")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted_count"] == 1
        assert orphan_id in data["deleted_ids"]

        # Verify orphan is gone
        resp2 = client.get("/api/things/relationships/orphans")
        assert resp2.json() == []

    def test_cleanup_preserves_valid_relationships(self, client, db):
        t1 = create_thing(client, title="A")
        t2 = create_thing(client, title="B")
        rel = client.post(
            "/api/things/relationships",
            json={"from_thing_id": t1["id"], "to_thing_id": t2["id"], "relationship_type": "valid"},
        )
        assert rel.status_code == 201

        _insert_orphan_relationship(db, "ghost1", "ghost2")

        resp = client.post("/api/things/relationships/cleanup")
        assert resp.json()["deleted_count"] == 1

        # Valid relationship still exists
        rels = client.get(f"/api/things/{t1['id']}/relationships")
        assert len(rels.json()) == 1

    def test_cleanup_noop_when_no_orphans(self, client):
        resp = client.post("/api/things/relationships/cleanup")
        assert resp.status_code == 200
        assert resp.json()["deleted_count"] == 0
        assert resp.json()["deleted_ids"] == []
