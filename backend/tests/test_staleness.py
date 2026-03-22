"""Tests for the staleness & neglect detection endpoint."""

from datetime import date, timedelta


def _create_thing(client, title: str, **kwargs) -> dict:
    payload = {"title": title, **kwargs}
    resp = client.post("/api/things", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestStalenessEndpoint:
    def test_empty_staleness_report(self, client):
        resp = client.get("/api/staleness")
        assert resp.status_code == 200
        data = resp.json()
        assert data["stale_items"] == []
        assert data["overdue_checkins"] == []
        assert data["total"] == 0
        assert data["stale_threshold_days"] == 14
        assert "as_of" in data

    def test_stale_item_detected(self, client, patched_db):
        from backend.database import db

        # Create a thing and manually backdate its updated_at
        thing = _create_thing(client, "Old Task")
        old_date = (date.today() - timedelta(days=20)).isoformat()
        with db() as conn:
            conn.execute("UPDATE things SET updated_at = ? WHERE id = ?", (old_date, thing["id"]))

        resp = client.get("/api/staleness")
        data = resp.json()
        assert data["total"] >= 1
        stale_ids = [s["thing"]["id"] for s in data["stale_items"]]
        assert thing["id"] in stale_ids

    def test_overdue_checkin_detected(self, client):
        past = (date.today() - timedelta(days=5)).isoformat()
        thing = _create_thing(client, "Overdue Check-in", checkin_date=f"{past}T09:00:00")

        resp = client.get("/api/staleness")
        data = resp.json()
        overdue_ids = [o["thing"]["id"] for o in data["overdue_checkins"]]
        assert thing["id"] in overdue_ids
        overdue = next(o for o in data["overdue_checkins"] if o["thing"]["id"] == thing["id"])
        assert overdue["days_overdue"] >= 5

    def test_custom_stale_days_override(self, client, patched_db):
        from backend.database import db

        thing = _create_thing(client, "Slightly Old")
        # Updated 5 days ago — stale only if threshold is < 5
        old_date = (date.today() - timedelta(days=5)).isoformat()
        with db() as conn:
            conn.execute("UPDATE things SET updated_at = ? WHERE id = ?", (old_date, thing["id"]))

        # Default threshold (14) — not stale
        resp = client.get("/api/staleness")
        stale_ids = [s["thing"]["id"] for s in resp.json()["stale_items"]]
        assert thing["id"] not in stale_ids

        # Override to 3 days — now stale
        resp = client.get("/api/staleness?stale_days=3")
        data = resp.json()
        assert data["stale_threshold_days"] == 3
        stale_ids = [s["thing"]["id"] for s in data["stale_items"]]
        assert thing["id"] in stale_ids

    def test_neglected_vs_stale_distinction(self, client, patched_db):
        from backend.database import db

        # High-priority thing — should be neglected
        high_pri = _create_thing(client, "Urgent Thing", priority=1)
        # Low-priority thing — should be plain stale
        low_pri = _create_thing(client, "Low Priority Note", priority=5)

        old_date = (date.today() - timedelta(days=20)).isoformat()
        with db() as conn:
            conn.execute("UPDATE things SET updated_at = ? WHERE id = ?", (old_date, high_pri["id"]))
            conn.execute("UPDATE things SET updated_at = ? WHERE id = ?", (old_date, low_pri["id"]))

        resp = client.get("/api/staleness")
        data = resp.json()

        stale_map = {s["thing"]["id"]: s for s in data["stale_items"]}
        assert stale_map[high_pri["id"]]["is_neglected"] is True
        assert stale_map[low_pri["id"]]["is_neglected"] is False

        assert data["counts"]["neglected"] >= 1
        assert data["counts"]["stale"] >= 1

    def test_inactive_things_excluded(self, client):
        past = (date.today() - timedelta(days=5)).isoformat()
        thing = _create_thing(client, "Done Thing", checkin_date=f"{past}T09:00:00")
        # Mark as inactive
        client.patch(f"/api/things/{thing['id']}", json={"active": False})

        resp = client.get("/api/staleness")
        data = resp.json()
        all_ids = [s["thing"]["id"] for s in data["stale_items"]] + [o["thing"]["id"] for o in data["overdue_checkins"]]
        assert thing["id"] not in all_ids

    def test_counts_structure(self, client):
        resp = client.get("/api/staleness")
        data = resp.json()
        counts = data["counts"]
        assert "stale" in counts
        assert "neglected" in counts
        assert "overdue_checkins" in counts
        assert data["total"] == counts["stale"] + counts["neglected"] + counts["overdue_checkins"]
