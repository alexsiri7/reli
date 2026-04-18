"""Tests for the daily briefing endpoint."""

from datetime import date, datetime, timedelta

from backend.routers.briefing import _confidence_label


class TestConfidenceLabel:
    def test_strong(self):
        assert _confidence_label({"confidence": 0.7}) == "strong"
        assert _confidence_label({"confidence": 1.0}) == "strong"

    def test_moderate(self):
        assert _confidence_label({"confidence": 0.5}) == "moderate"
        assert _confidence_label({"confidence": 0.69}) == "moderate"

    def test_emerging(self):
        assert _confidence_label({"confidence": 0.0}) == "emerging"
        assert _confidence_label({"confidence": 0.49}) == "emerging"
        assert _confidence_label({}) == "emerging"

    def test_non_numeric_confidence_falls_back_to_emerging(self):
        assert _confidence_label({"confidence": "high"}) == "emerging"
        assert _confidence_label({"confidence": None}) == "emerging"

    def test_patterns_path_string_label(self):
        data = {"patterns": [{"confidence": "strong"}], "confidence": 0.1}
        assert _confidence_label(data) == "strong"

    def test_patterns_path_invalid_string_falls_back_to_emerging(self):
        data = {"patterns": [{"confidence": "0.8"}]}
        assert _confidence_label(data) == "emerging"

    def test_patterns_path_float_confidence(self):
        data = {"patterns": [{"confidence": 0.8}]}
        assert _confidence_label(data) == "strong"

    def test_patterns_path_float_moderate(self):
        data = {"patterns": [{"confidence": 0.6}]}
        assert _confidence_label(data) == "moderate"

    def test_patterns_path_float_emerging(self):
        data = {"patterns": [{"confidence": 0.3}]}
        assert _confidence_label(data) == "emerging"

    def test_patterns_empty_falls_through_to_float(self):
        data = {"patterns": [], "confidence": 0.8}
        assert _confidence_label(data) == "strong"


def _create_thing(client, title: str, checkin_date: str | None = None, active: bool = True) -> dict:
    payload = {"title": title, "active": active}
    if checkin_date:
        payload["checkin_date"] = checkin_date
    resp = client.post("/api/things", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _briefing_titles(data: dict) -> list[str]:
    titles = []
    if t := data.get("the_one_thing"):
        titles.append(t["thing"]["title"])
    titles.extend(item["thing"]["title"] for item in data.get("secondary", []))
    titles.extend(item["title"] for item in data.get("parking_lot", []))
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

    def test_preference_things_appear_in_briefing(self, client):
        """Learned preferences (type_hint='preference') must appear in learned_preferences."""
        resp = client.post("/api/things", json={
            "title": "Prefers afternoon meetings",
            "type_hint": "preference",
            "data": {"confidence": 0.6, "category": "scheduling"},
        })
        assert resp.status_code == 201
        pref_id = resp.json()["id"]

        resp = client.get("/api/briefing")
        assert resp.status_code == 200
        data = resp.json()
        assert "learned_preferences" in data
        ids = [p["id"] for p in data["learned_preferences"]]
        assert pref_id in ids

    def test_preference_confidence_label_in_briefing(self, client):
        """confidence_label is correctly derived from float confidence."""
        client.post("/api/things", json={
            "title": "Cost conscious",
            "type_hint": "preference",
            "data": {"confidence": 0.8, "category": "spending"},
        })
        resp = client.get("/api/briefing")
        prefs = resp.json()["learned_preferences"]
        cost_pref = next((p for p in prefs if p["title"] == "Cost conscious"), None)
        assert cost_pref is not None
        assert cost_pref["confidence_label"] == "strong"

    def test_preference_cap_at_five(self, client):
        """learned_preferences is capped at 5 even when more preferences exist."""
        for i in range(6):
            client.post("/api/things", json={
                "title": f"Preference {i}",
                "type_hint": "preference",
                "data": {"confidence": 0.6},
            })
        resp = client.get("/api/briefing")
        prefs = resp.json()["learned_preferences"]
        assert len(prefs) <= 5

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
