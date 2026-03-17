"""Tests for the daily briefing endpoint."""

from datetime import date, datetime, timedelta


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


class TestStalenessReport:
    def test_empty_report(self, client):
        resp = client.get("/api/briefing/staleness")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overdue"] == []
        assert data["neglected"] == []
        assert data["stale"] == []
        assert data["total"] == 0
        assert data["stale_days"] == 14  # default

    def test_overdue_findings_appear(self, client):
        finding = _create_finding_of_type(client, "overdue", "Overdue by 3d: Test")
        resp = client.get("/api/briefing/staleness")
        data = resp.json()
        assert len(data["overdue"]) == 1
        assert data["overdue"][0]["id"] == finding["id"]

    def test_neglected_findings_appear(self, client):
        finding = _create_finding_of_type(client, "neglected", "Neglected for 20d: Test")
        resp = client.get("/api/briefing/staleness")
        data = resp.json()
        assert len(data["neglected"]) == 1
        assert data["neglected"][0]["id"] == finding["id"]

    def test_stale_findings_appear(self, client):
        finding = _create_finding_of_type(client, "stale", "Untouched for 20d: Test")
        resp = client.get("/api/briefing/staleness")
        data = resp.json()
        assert len(data["stale"]) == 1
        assert data["stale"][0]["id"] == finding["id"]

    def test_dismissed_findings_excluded(self, client):
        finding = _create_finding_of_type(client, "overdue", "Dismissed overdue")
        client.patch(f"/api/briefing/findings/{finding['id']}/dismiss")
        resp = client.get("/api/briefing/staleness")
        assert resp.json()["total"] == 0


class TestBatchNotification:
    def test_empty_notification(self, client):
        resp = client.get("/api/briefing/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overdue_count"] == 0
        assert data["neglected_count"] == 0
        assert data["stale_count"] == 0
        assert "All clear" in data["summary"]

    def test_notification_counts(self, client):
        _create_finding_of_type(client, "overdue", "Overdue item")
        _create_finding_of_type(client, "neglected", "Neglected item")
        _create_finding_of_type(client, "stale", "Stale item")
        _create_finding_of_type(client, "approaching_date", "Coming up")

        resp = client.get("/api/briefing/notifications")
        data = resp.json()
        assert data["overdue_count"] == 1
        assert data["neglected_count"] == 1
        assert data["stale_count"] == 1
        assert data["finding_count"] == 1  # the approaching_date one
        assert len(data["items"]) == 4
        assert "overdue" in data["summary"]
        assert "neglected" in data["summary"]

    def test_dismissed_excluded(self, client):
        finding = _create_finding_of_type(client, "overdue", "Dismissed")
        client.patch(f"/api/briefing/findings/{finding['id']}/dismiss")
        resp = client.get("/api/briefing/notifications")
        assert resp.json()["overdue_count"] == 0


def _create_finding_of_type(client, finding_type: str, message: str) -> dict:
    """Helper to create a finding with a specific type."""
    payload = {"finding_type": finding_type, "message": message, "priority": 2}
    resp = client.post("/api/briefing/findings", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()
