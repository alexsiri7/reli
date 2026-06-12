"""Tests for the focus recommendations endpoint."""

from datetime import date, timedelta


def _create_thing(client, title: str, **kwargs) -> dict:
    payload = {"title": title, **kwargs}
    resp = client.post("/api/things", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestFocusEndpoint:
    def test_empty_focus(self, client):
        resp = client.get("/api/focus")
        assert resp.status_code == 200
        data = resp.json()
        assert "recommendations" in data
        assert "total" in data
        assert "calendar_active" in data
        assert data["recommendations"] == []
        assert data["total"] == 0

    def test_focus_with_task(self, client):
        _create_thing(client, "Important task", type_hint="task", importance=0)
        resp = client.get("/api/focus")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert len(data["recommendations"]) >= 1
        rec = data["recommendations"][0]
        assert "thing" in rec
        assert "score" in rec
        assert "reasons" in rec
        assert "is_blocked" in rec

    def test_focus_limit_query_param(self, client):
        for i in range(5):
            _create_thing(client, f"Task {i}", type_hint="task", importance=1)
        resp = client.get("/api/focus?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["recommendations"]) <= 2

    def test_focus_respects_active_flag(self, client):
        thing = _create_thing(client, "Active task", type_hint="task", importance=0)
        # Deactivate the thing
        client.patch(f"/api/things/{thing['id']}", json={"active": False})
        resp = client.get("/api/focus")
        assert resp.status_code == 200
        data = resp.json()
        ids_in_focus = [r["thing"]["id"] for r in data["recommendations"]]
        assert thing["id"] not in ids_in_focus

    def test_focus_overdue_checkin_boosts_score(self, client):
        past = (date.today() - timedelta(days=3)).isoformat()
        overdue = _create_thing(
            client, "Overdue check-in task", type_hint="task", importance=2, checkin_date=f"{past}T09:00:00"
        )
        normal = _create_thing(client, "Normal task", type_hint="task", importance=2)
        resp = client.get("/api/focus?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        ids = [r["thing"]["id"] for r in data["recommendations"]]
        assert overdue["id"] in ids
        assert normal["id"] in ids
        # Overdue check-in should appear before normal task
        assert ids.index(overdue["id"]) < ids.index(normal["id"])
