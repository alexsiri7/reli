"""Tests for the focus recommendations endpoint."""

from datetime import date, timedelta


def _create_thing(client, title: str, **kwargs) -> dict:
    payload = {"title": title, **kwargs}
    resp = client.post("/api/things", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_relationship(client, from_id: str, to_id: str, rel_type: str) -> dict:
    resp = client.post(
        "/api/things/relationships",
        json={"from_thing_id": from_id, "to_thing_id": to_id, "relationship_type": rel_type},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestFocusRecommendations:
    def test_empty_returns_empty_list(self, client):
        resp = client.get("/api/focus")
        assert resp.status_code == 200
        data = resp.json()
        assert data["recommendations"] == []
        assert data["total_active"] == 0
        assert "generated_at" in data

    def test_returns_active_things_ranked(self, client):
        _create_thing(client, "Low priority", priority=5)
        _create_thing(client, "High priority", priority=1)
        _create_thing(client, "Medium priority", priority=3)

        resp = client.get("/api/focus")
        data = resp.json()
        assert len(data["recommendations"]) == 3
        assert data["total_active"] == 3

        titles = [r["thing"]["title"] for r in data["recommendations"]]
        assert titles[0] == "High priority"

    def test_deadline_boosts_score(self, client):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        _create_thing(client, "No deadline", priority=2)
        _create_thing(client, "Due tomorrow", priority=3, data={"deadline": tomorrow})

        resp = client.get("/api/focus")
        recs = resp.json()["recommendations"]
        due_rec = next(r for r in recs if r["thing"]["title"] == "Due tomorrow")
        no_rec = next(r for r in recs if r["thing"]["title"] == "No deadline")
        assert due_rec["score"] > no_rec["score"]
        assert due_rec["deadline"] is not None

    def test_blocked_things_penalized(self, client):
        blocker = _create_thing(client, "Blocker task", priority=3)
        blocked = _create_thing(client, "Blocked task", priority=3)
        _create_relationship(client, blocked["id"], blocker["id"], "depends-on")

        resp = client.get("/api/focus")
        recs = resp.json()["recommendations"]
        blocker_rec = next(r for r in recs if r["thing"]["title"] == "Blocker task")
        blocked_rec = next(r for r in recs if r["thing"]["title"] == "Blocked task")
        assert blocked_rec["is_blocked"] is True
        assert blocker_rec["score"] > blocked_rec["score"]

    def test_reasons_included(self, client):
        _create_thing(client, "P1 task", priority=1)
        resp = client.get("/api/focus")
        recs = resp.json()["recommendations"]
        assert len(recs) == 1
        assert len(recs[0]["reasons"]) > 0
        assert any("priority" in r.lower() for r in recs[0]["reasons"])

    def test_limit_parameter(self, client):
        for i in range(5):
            _create_thing(client, f"Task {i}")

        resp = client.get("/api/focus?limit=2")
        recs = resp.json()["recommendations"]
        assert len(recs) == 2

    def test_inactive_things_excluded(self, client):
        thing = _create_thing(client, "Will be inactive", priority=1)
        client.patch(f"/api/things/{thing['id']}", json={"active": False})

        resp = client.get("/api/focus")
        assert resp.json()["total_active"] == 0

    def test_rank_is_sequential(self, client):
        for i in range(3):
            _create_thing(client, f"Task {i}")

        resp = client.get("/api/focus")
        ranks = [r["rank"] for r in resp.json()["recommendations"]]
        assert ranks == [1, 2, 3]

    def test_checkin_date_boosts_score(self, client):
        today = date.today().isoformat()
        _create_thing(client, "No checkin", priority=3)
        _create_thing(client, "Checkin today", priority=3, checkin_date=f"{today}T09:00:00")

        resp = client.get("/api/focus")
        recs = resp.json()["recommendations"]
        checkin_rec = next(r for r in recs if r["thing"]["title"] == "Checkin today")
        no_rec = next(r for r in recs if r["thing"]["title"] == "No checkin")
        assert checkin_rec["score"] > no_rec["score"]
