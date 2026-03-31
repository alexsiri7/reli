"""Tests for the daily briefing endpoint."""

from datetime import date, datetime, timedelta


def _create_thing(client, title: str, checkin_date: str | None = None, active: bool = True) -> dict:
    payload = {"title": title, "active": active}
    if checkin_date:
        payload["checkin_date"] = checkin_date
    resp = client.post("/api/things", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _briefing_titles(data: dict) -> list[str]:
    """Extract all Thing titles from the new briefing response shape."""
    titles = []
    if data.get("the_one_thing"):
        titles.append(data["the_one_thing"]["thing"]["title"])
    for item in data.get("secondary", []):
        titles.append(item["thing"]["title"])
    for item in data.get("parking_lot", []):
        titles.append(item["title"])
    return titles


class TestBriefing:
    def test_empty_briefing(self, client):
        resp = client.get("/api/briefing")
        assert resp.status_code == 200
        data = resp.json()
        assert data["the_one_thing"] is None
        assert data["total"] == 0
        assert "date" in data

    def test_things_due_today_appear(self, client):
        today = date.today().isoformat()
        _create_thing(client, "Due Today", checkin_date=f"{today}T09:00:00")
        resp = client.get("/api/briefing")
        titles = _briefing_titles(resp.json())
        assert "Due Today" in titles

    def test_future_things_excluded(self, client):
        _create_thing(client, "Future Task", checkin_date="2099-01-01T00:00:00")
        resp = client.get("/api/briefing")
        titles = _briefing_titles(resp.json())
        assert "Future Task" not in titles

    def test_past_things_included(self, client):
        _create_thing(client, "Overdue Task", checkin_date="2020-01-01T00:00:00")
        resp = client.get("/api/briefing")
        titles = _briefing_titles(resp.json())
        assert "Overdue Task" in titles

    def test_inactive_things_excluded(self, client):
        today = date.today().isoformat()
        thing = _create_thing(client, "Inactive Task", checkin_date=f"{today}T00:00:00")
        client.patch(f"/api/things/{thing['id']}", json={"active": False})
        resp = client.get("/api/briefing")
        titles = _briefing_titles(resp.json())
        assert "Inactive Task" not in titles

    def test_things_without_checkin_date_excluded(self, client):
        _create_thing(client, "No Date Thing")
        resp = client.get("/api/briefing")
        titles = _briefing_titles(resp.json())
        assert "No Date Thing" not in titles

    def test_as_of_param_filters_correctly(self, client):
        _create_thing(client, "Before As-Of", checkin_date="2026-01-01T00:00:00")
        _create_thing(client, "After As-Of", checkin_date="2026-06-01T00:00:00")
        resp = client.get("/api/briefing?as_of=2026-03-01")
        data = resp.json()
        titles = _briefing_titles(data)
        assert "Before As-Of" in titles
        assert "After As-Of" not in titles
        assert data["date"] == "2026-03-01"

    def test_total_includes_scored_items(self, client):
        today = date.today().isoformat()
        _create_thing(client, "T1", checkin_date=f"{today}T00:00:00")
        _create_thing(client, "T2", checkin_date=f"{today}T01:00:00")
        resp = client.get("/api/briefing")
        data = resp.json()
        assert data["total"] == 2


def _create_finding(client, message: str = "test finding", thing_id: str | None = None) -> dict:
    payload = {"finding_type": "test", "message": message, "priority": 2}
    if thing_id:
        payload["thing_id"] = thing_id
    resp = client.post("/api/briefing/findings", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestSnoozeFinding:
    def test_snooze_sets_snoozed_until(self, client):
        finding = _create_finding(client)
        until = (datetime.utcnow() + timedelta(days=3)).isoformat()
        resp = client.post(
            f"/api/briefing/findings/{finding['id']}/snooze",
            json={"until": until},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["snoozed_until"] is not None

    def test_snoozed_finding_hidden_from_briefing(self, client):
        finding = _create_finding(client, message="snooze me")
        # Verify it appears in briefing first
        resp = client.get("/api/briefing")
        finding_ids = [f["id"] for f in resp.json()["findings"]]
        assert finding["id"] in finding_ids

        # Snooze to the future — hidden until snoozed_until passes
        until = (datetime.utcnow() + timedelta(days=7)).isoformat()
        client.post(
            f"/api/briefing/findings/{finding['id']}/snooze",
            json={"until": until},
        )

        resp = client.get("/api/briefing")
        finding_ids = [f["id"] for f in resp.json()["findings"]]
        assert finding["id"] not in finding_ids

    def test_snooze_not_found(self, client):
        resp = client.post(
            "/api/briefing/findings/nonexistent/snooze",
            json={"until": "2099-01-01T00:00:00"},
        )
        assert resp.status_code == 404

    def test_expired_snooze_reappears(self, client):
        finding = _create_finding(client, message="will reappear")
        # Snooze to the past — already expired, should reappear
        until = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        client.post(
            f"/api/briefing/findings/{finding['id']}/snooze",
            json={"until": until},
        )
        resp = client.get("/api/briefing")
        finding_ids = [f["id"] for f in resp.json()["findings"]]
        assert finding["id"] in finding_ids


class TestFindingsForInactiveThings:
    def test_finding_for_inactive_thing_excluded(self, client):
        """Findings linked to inactive (completed) Things should not appear."""
        thing = _create_thing(client, "Will Complete")
        finding = _create_finding(client, "stale finding", thing_id=thing["id"])

        # Finding visible while Thing is active
        resp = client.get("/api/briefing")
        finding_ids = [f["id"] for f in resp.json()["findings"]]
        assert finding["id"] in finding_ids

        # Deactivate the Thing
        client.patch(f"/api/things/{thing['id']}", json={"active": False})

        # Finding should now be excluded
        resp = client.get("/api/briefing")
        finding_ids = [f["id"] for f in resp.json()["findings"]]
        assert finding["id"] not in finding_ids

    def test_finding_without_thing_still_shown(self, client):
        """Findings not linked to any Thing should still appear."""
        finding = _create_finding(client, "orphan finding")
        resp = client.get("/api/briefing")
        finding_ids = [f["id"] for f in resp.json()["findings"]]
        assert finding["id"] in finding_ids

    def test_finding_for_active_thing_still_shown(self, client):
        """Findings linked to active Things should still appear."""
        thing = _create_thing(client, "Active Thing")
        finding = _create_finding(client, "active finding", thing_id=thing["id"])
        resp = client.get("/api/briefing")
        finding_ids = [f["id"] for f in resp.json()["findings"]]
        assert finding["id"] in finding_ids
