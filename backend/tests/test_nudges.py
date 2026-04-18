"""Tests for the nudges router — especially the stop_nudge_type prefix mapping."""

from fastapi.testclient import TestClient


def test_stop_nudge_type_maps_proactive_prefix(client: TestClient) -> None:
    """proactive_<id>_<key> nudge IDs must suppress 'approaching_date', not 'proactive'."""
    nudge_id = "proactive_abc123_birthday"
    resp = client.post(f"/api/nudges/{nudge_id}/stop")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["suppressed_type"] == "approaching_date"


def test_stop_nudge_type_unknown_prefix_falls_back_to_prefix(client: TestClient) -> None:
    """Unknown prefix suppresses that prefix and does NOT create a preference."""
    # "future_xyz_birthday" → split("_")[0] → "future" (fallback since not in _PREFIX_TO_NUDGE_TYPE)
    nudge_id = "future_xyz_birthday"
    resp = client.post(f"/api/nudges/{nudge_id}/stop")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["suppressed_type"] == "future"
    assert "preference" not in body


def test_stop_nudge_type_no_underscore_id(client: TestClient) -> None:
    """Nudge IDs without underscore should use the entire id as the suppressed type."""
    nudge_id = "approaching"
    resp = client.post(f"/api/nudges/{nudge_id}/stop")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["suppressed_type"] == "approaching"


def test_dismiss_nudge(client: TestClient) -> None:
    """Dismissing a nudge returns ok and is idempotent."""
    nudge_id = "proactive_abc123_birthday"
    resp = client.post(f"/api/nudges/{nudge_id}/dismiss")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # Idempotent — second dismiss should also succeed
    resp2 = client.post(f"/api/nudges/{nudge_id}/dismiss")
    assert resp2.status_code == 200
    assert resp2.json() == {"ok": True}


def test_stop_nudge_type_is_idempotent(client: TestClient) -> None:
    """Stopping a nudge type twice should succeed without error (INSERT OR IGNORE semantics)."""
    nudge_id = "proactive_abc123_birthday"
    resp1 = client.post(f"/api/nudges/{nudge_id}/stop")
    assert resp1.status_code == 200
    resp2 = client.post(f"/api/nudges/{nudge_id}/stop")
    assert resp2.status_code == 200
    assert resp2.json()["suppressed_type"] == "approaching_date"


def test_stop_creates_preference_thing(client: TestClient) -> None:
    """Stopping a nudge type creates a preference Thing with correct data."""
    resp = client.post("/api/nudges/proactive_abc123_birthday/stop")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["preference"]["action"] == "created"
    assert body["preference"]["title"] == "Prefers fewer date-based reminders"
    assert body["preference"]["confidence_label"] == "moderate"


def test_stop_updates_preference_on_repeat(client: TestClient) -> None:
    """Second stop (different nudge, same type) updates the existing preference."""
    resp1 = client.post("/api/nudges/proactive_abc123_birthday/stop")
    assert resp1.status_code == 200
    assert resp1.json()["preference"]["action"] == "created"

    resp2 = client.post("/api/nudges/proactive_xyz999_deadline/stop")
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["preference"]["action"] == "updated"
    assert body2["preference"]["confidence_label"] in ("moderate", "strong")


def test_get_nudges_returns_list(client: TestClient) -> None:
    """GET /api/nudges returns an empty list when there are no matching things."""
    resp = client.get("/api/nudges")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_conf_label_boundaries() -> None:
    """_conf_label maps float confidence values to correct display labels at all boundaries."""
    from backend.routers.nudges import _conf_label

    assert _conf_label(0.95) == "strong"   # capped max
    assert _conf_label(0.7) == "strong"    # exact strong boundary
    assert _conf_label(0.69) == "moderate"
    assert _conf_label(0.5) == "moderate"  # exact moderate boundary
    assert _conf_label(0.49) == "emerging"
    assert _conf_label(0.0) == "emerging"  # floor
