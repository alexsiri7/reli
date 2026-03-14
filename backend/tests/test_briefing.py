"""Tests for the daily briefing endpoint."""

from datetime import date


def _create_thing(client, title: str, checkin_date: str | None = None, active: bool = True) -> dict:
    payload = {"title": title, "active": active}
    if checkin_date:
        payload["checkin_date"] = checkin_date
    resp = client.post("/api/things", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestBriefing:
    def test_empty_briefing(self, client):
        resp = client.get("/api/briefing")
        assert resp.status_code == 200
        data = resp.json()
        assert data["things"] == []
        assert data["total"] == 0
        assert "date" in data

    def test_things_due_today_appear(self, client):
        today = date.today().isoformat()
        _create_thing(client, "Due Today", checkin_date=f"{today}T09:00:00")
        resp = client.get("/api/briefing")
        titles = [t["title"] for t in resp.json()["things"]]
        assert "Due Today" in titles

    def test_future_things_excluded(self, client):
        _create_thing(client, "Future Task", checkin_date="2099-01-01T00:00:00")
        resp = client.get("/api/briefing")
        titles = [t["title"] for t in resp.json()["things"]]
        assert "Future Task" not in titles

    def test_past_things_included(self, client):
        _create_thing(client, "Overdue Task", checkin_date="2020-01-01T00:00:00")
        resp = client.get("/api/briefing")
        titles = [t["title"] for t in resp.json()["things"]]
        assert "Overdue Task" in titles

    def test_inactive_things_excluded(self, client):
        today = date.today().isoformat()
        thing = _create_thing(client, "Inactive Task", checkin_date=f"{today}T00:00:00")
        client.patch(f"/api/things/{thing['id']}", json={"active": False})
        resp = client.get("/api/briefing")
        titles = [t["title"] for t in resp.json()["things"]]
        assert "Inactive Task" not in titles

    def test_things_without_checkin_date_excluded(self, client):
        _create_thing(client, "No Date Thing")
        resp = client.get("/api/briefing")
        titles = [t["title"] for t in resp.json()["things"]]
        assert "No Date Thing" not in titles

    def test_as_of_param_filters_correctly(self, client):
        _create_thing(client, "Before As-Of", checkin_date="2026-01-01T00:00:00")
        _create_thing(client, "After As-Of", checkin_date="2026-06-01T00:00:00")
        resp = client.get("/api/briefing?as_of=2026-03-01")
        data = resp.json()
        titles = [t["title"] for t in data["things"]]
        assert "Before As-Of" in titles
        assert "After As-Of" not in titles
        assert data["date"] == "2026-03-01"

    def test_total_matches_things_count(self, client):
        today = date.today().isoformat()
        _create_thing(client, "T1", checkin_date=f"{today}T00:00:00")
        _create_thing(client, "T2", checkin_date=f"{today}T01:00:00")
        resp = client.get("/api/briefing")
        data = resp.json()
        assert data["total"] == len(data["things"])
        assert data["total"] == 2
