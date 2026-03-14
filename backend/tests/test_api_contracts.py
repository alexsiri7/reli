"""API contract tests: validate response shapes match frontend TypeScript types.

These tests call each API endpoint and verify the response JSON has the exact
field names, types, and nullability that the frontend expects (as defined in
frontend/src/store.ts).

This is the cheapest test that catches the most common AI-generated bugs:
type mismatches between backend responses and frontend expectations.
"""

import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers — shape validators matching frontend TypeScript interfaces
# ---------------------------------------------------------------------------

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?")


def assert_thing_shape(obj: dict) -> None:
    """Validate obj matches frontend Thing interface."""
    assert isinstance(obj["id"], str)
    assert isinstance(obj["title"], str)
    assert obj["type_hint"] is None or isinstance(obj["type_hint"], str)
    assert obj["parent_id"] is None or isinstance(obj["parent_id"], str)
    assert obj["checkin_date"] is None or isinstance(obj["checkin_date"], str)
    assert isinstance(obj["priority"], int)
    assert isinstance(obj["active"], bool)
    assert obj["data"] is None or isinstance(obj["data"], dict)
    assert isinstance(obj["created_at"], str)
    assert isinstance(obj["updated_at"], str)
    # Dates must be ISO strings (frontend parses them as strings, not Date objects)
    assert ISO_DATE_RE.match(obj["created_at"]), f"created_at not ISO: {obj['created_at']}"
    assert ISO_DATE_RE.match(obj["updated_at"]), f"updated_at not ISO: {obj['updated_at']}"


def assert_chat_message_shape(obj: dict) -> None:
    """Validate obj matches frontend ChatMessage interface."""
    assert isinstance(obj["id"], (int, str))
    assert isinstance(obj["session_id"], str)
    assert obj["role"] in ("user", "assistant")
    assert isinstance(obj["content"], str)
    assert obj["applied_changes"] is None or isinstance(obj["applied_changes"], dict)
    assert isinstance(obj["timestamp"], str)
    assert ISO_DATE_RE.match(obj["timestamp"]), f"timestamp not ISO: {obj['timestamp']}"


def assert_chat_response_shape(obj: dict) -> None:
    """Validate obj matches ChatResponse / frontend sendMessage expectations."""
    assert isinstance(obj["session_id"], str)
    assert isinstance(obj["reply"], str)
    assert isinstance(obj["applied_changes"], dict)
    assert isinstance(obj["questions_for_user"], list)
    for q in obj["questions_for_user"]:
        assert isinstance(q, str)


def assert_briefing_response_shape(obj: dict) -> None:
    """Validate obj matches BriefingResponse / frontend fetchBriefing expectations."""
    assert isinstance(obj["date"], str)
    assert isinstance(obj["things"], list)
    assert isinstance(obj["total"], int)
    for thing in obj["things"]:
        assert_thing_shape(thing)


def assert_calendar_status_shape(obj: dict) -> None:
    """Validate obj matches frontend CalendarStatus interface."""
    assert isinstance(obj["configured"], bool)
    assert isinstance(obj["connected"], bool)


def assert_calendar_events_response_shape(obj: dict) -> None:
    """Validate obj matches frontend fetchCalendarEvents expectations."""
    assert isinstance(obj["events"], list)
    assert isinstance(obj["count"], int)
    for event in obj["events"]:
        assert isinstance(event["id"], str)
        assert isinstance(event["summary"], str)
        assert isinstance(event["start"], str)
        assert isinstance(event["end"], str)
        assert isinstance(event["all_day"], bool)
        assert event["location"] is None or isinstance(event["location"], str)
        assert isinstance(event["status"], str)


# ---------------------------------------------------------------------------
# Fixtures — helpers for seeding data
# ---------------------------------------------------------------------------

def _create_thing(client, **overrides) -> dict:
    """Create a Thing and return the JSON response."""
    payload = {"title": "Test Thing", "priority": 3, **overrides}
    resp = client.post("/api/things", json=payload)
    assert resp.status_code == 201
    return resp.json()


def _create_chat_message(client, session_id: str, role: str = "user", content: str = "hello") -> dict:
    """Post a chat history message and return the JSON response."""
    resp = client.post("/api/chat/history", json={
        "session_id": session_id,
        "role": role,
        "content": content,
    })
    assert resp.status_code == 201
    return resp.json()


# ===========================================================================
# Contract tests — Things endpoints
# ===========================================================================

class TestThingsContract:
    """GET/POST/PATCH /api/things — response shapes match frontend Thing type."""

    def test_list_things_returns_array_of_things(self, client):
        _create_thing(client, title="Contract Thing A")
        _create_thing(client, title="Contract Thing B")
        resp = client.get("/api/things")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) >= 2
        for item in body:
            assert_thing_shape(item)

    def test_create_thing_returns_thing(self, client):
        resp = client.post("/api/things", json={
            "title": "New Contract Thing",
            "type_hint": "task",
            "priority": 2,
            "data": {"key": "value"},
        })
        assert resp.status_code == 201
        assert_thing_shape(resp.json())

    def test_get_thing_returns_thing(self, client):
        created = _create_thing(client, title="Get Me")
        resp = client.get(f"/api/things/{created['id']}")
        assert resp.status_code == 200
        assert_thing_shape(resp.json())

    def test_update_thing_returns_thing(self, client):
        created = _create_thing(client, title="Update Me")
        resp = client.patch(f"/api/things/{created['id']}", json={"title": "Updated"})
        assert resp.status_code == 200
        assert_thing_shape(resp.json())

    def test_thing_data_is_dict_not_string(self, client):
        """Regression: data must be a dict (object), never a JSON string."""
        created = _create_thing(client, data={"nested": {"a": 1}})
        resp = client.get(f"/api/things/{created['id']}")
        body = resp.json()
        assert isinstance(body["data"], dict), (
            f"data should be dict, got {type(body['data']).__name__}: {body['data']!r}"
        )

    def test_thing_dates_are_iso_strings(self, client):
        """Dates must arrive as ISO 8601 strings, not epoch ints or other formats."""
        now = datetime.now(timezone.utc).isoformat()
        created = _create_thing(client, checkin_date=now)
        resp = client.get(f"/api/things/{created['id']}")
        body = resp.json()
        assert isinstance(body["checkin_date"], str)
        assert ISO_DATE_RE.match(body["checkin_date"])

    def test_thing_nullable_fields_are_null_not_missing(self, client):
        """Frontend expects null (not undefined/missing) for optional fields."""
        created = _create_thing(client, title="Nullables")
        body = client.get(f"/api/things/{created['id']}").json()
        # These fields should exist and be null, not absent
        for field in ("type_hint", "parent_id", "checkin_date", "data"):
            assert field in body, f"field '{field}' missing from response"


# ===========================================================================
# Contract tests — Chat History endpoints
# ===========================================================================

class TestChatHistoryContract:
    """GET/POST /api/chat/history — response shapes match frontend ChatMessage type."""

    def test_append_message_returns_chat_message(self, client):
        resp = client.post("/api/chat/history", json={
            "session_id": "contract-sess",
            "role": "user",
            "content": "hello",
        })
        assert resp.status_code == 201
        assert_chat_message_shape(resp.json())

    def test_get_history_returns_array_of_chat_messages(self, client):
        _create_chat_message(client, "contract-hist", "user", "first")
        _create_chat_message(client, "contract-hist", "assistant", "reply")
        resp = client.get("/api/chat/history/contract-hist")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) >= 2
        for msg in body:
            assert_chat_message_shape(msg)

    def test_chat_message_id_is_integer(self, client):
        """Frontend uses typeof id === 'number' for pagination."""
        msg = _create_chat_message(client, "contract-id", "user", "test")
        assert isinstance(msg["id"], int), f"id should be int, got {type(msg['id']).__name__}"

    def test_chat_message_timestamp_is_iso(self, client):
        msg = _create_chat_message(client, "contract-ts", "user", "test")
        assert isinstance(msg["timestamp"], str)
        assert ISO_DATE_RE.match(msg["timestamp"])


# ===========================================================================
# Contract tests — Chat Pipeline endpoint
# ===========================================================================

MOCK_CONTEXT = {
    "search_queries": ["test"],
    "filter_params": {"active_only": True, "type_hint": None},
}

MOCK_REASONING = {
    "storage_changes": {"create": [], "update": [], "delete": []},
    "questions_for_user": [],
    "reasoning_summary": "No changes needed.",
}


def _agent_patches(context=None, reasoning=None, reply="OK"):
    """Return a list of patch context managers for all chat pipeline agents."""
    return [
        patch("backend.routers.chat.run_context_agent",
              new=AsyncMock(return_value=context or MOCK_CONTEXT)),
        patch("backend.routers.chat.run_reasoning_agent",
              new=AsyncMock(return_value=reasoning or MOCK_REASONING)),
        patch("backend.routers.chat.run_response_agent",
              new=AsyncMock(return_value=reply)),
    ]


class TestChatPipelineContract:
    """POST /api/chat — response shape matches frontend sendMessage expectations."""

    @pytest.mark.anyio
    async def test_chat_response_shape(self, async_client):
        patches = _agent_patches(reply="Hello back!")
        with patches[0], patches[1], patches[2]:
            resp = await async_client.post("/api/chat", json={
                "session_id": "contract-pipeline",
                "message": "hi",
            })
        assert resp.status_code == 200
        assert_chat_response_shape(resp.json())

    @pytest.mark.anyio
    async def test_chat_response_with_applied_changes(self, async_client):
        """applied_changes must be a dict (object), not string or null."""
        reasoning = {
            "storage_changes": {
                "create": [{"title": "New Task", "type_hint": "task"}],
                "update": [],
                "delete": [],
            },
            "questions_for_user": ["Anything else?"],
            "reasoning_summary": "Created a task.",
        }
        patches = _agent_patches(reasoning=reasoning, reply="Created a task")
        with patches[0], patches[1], patches[2]:
            resp = await async_client.post("/api/chat", json={
                "session_id": "contract-changes",
                "message": "create a task",
            })
        body = resp.json()
        assert resp.status_code == 200
        assert_chat_response_shape(body)
        assert isinstance(body["applied_changes"], dict)
        assert isinstance(body["questions_for_user"], list)
        assert all(isinstance(q, str) for q in body["questions_for_user"])


# ===========================================================================
# Contract tests — Briefing endpoint
# ===========================================================================

class TestBriefingContract:
    """GET /api/briefing — response shape matches BriefingResponse."""

    def test_empty_briefing_shape(self, client):
        resp = client.get("/api/briefing")
        assert resp.status_code == 200
        assert_briefing_response_shape(resp.json())

    def test_briefing_with_things(self, client):
        # Create a thing with checkin_date in the past so it appears in briefing
        _create_thing(client, title="Due Thing", checkin_date="2020-01-01T00:00:00")
        resp = client.get("/api/briefing?as_of=2020-01-01")
        assert resp.status_code == 200
        body = resp.json()
        assert_briefing_response_shape(body)
        assert body["total"] >= 1
        assert len(body["things"]) == body["total"]

    def test_briefing_things_have_thing_shape(self, client):
        _create_thing(client, title="Briefing Thing", checkin_date="2020-06-15T12:00:00")
        resp = client.get("/api/briefing?as_of=2020-06-15")
        body = resp.json()
        for thing in body["things"]:
            assert_thing_shape(thing)


# ===========================================================================
# Contract tests — Calendar endpoints
# ===========================================================================

class TestCalendarContract:
    """GET /api/calendar/* — response shapes match frontend CalendarStatus/Event types."""

    def test_calendar_status_shape(self, client):
        with patch("backend.routers.calendar.is_configured", return_value=False), \
             patch("backend.routers.calendar.is_connected", return_value=False):
            resp = client.get("/api/calendar/status")
        assert resp.status_code == 200
        assert_calendar_status_shape(resp.json())

    def test_calendar_events_shape(self, client):
        mock_events = [
            {
                "id": "evt1",
                "summary": "Team standup",
                "start": "2025-01-15T09:00:00Z",
                "end": "2025-01-15T09:30:00Z",
                "all_day": False,
                "location": None,
                "status": "confirmed",
            },
            {
                "id": "evt2",
                "summary": "Company holiday",
                "start": "2025-01-20",
                "end": "2025-01-21",
                "all_day": True,
                "location": "Office",
                "status": "confirmed",
            },
        ]
        with patch("backend.routers.calendar.is_connected", return_value=True), \
             patch("backend.routers.calendar.fetch_upcoming_events", return_value=mock_events):
            resp = client.get("/api/calendar/events")
        assert resp.status_code == 200
        body = resp.json()
        assert_calendar_events_response_shape(body)
        assert body["count"] == 2

    def test_calendar_disconnect_shape(self, client):
        with patch("backend.routers.calendar.disconnect"):
            resp = client.delete("/api/calendar/disconnect")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "disconnected"


# ===========================================================================
# Contract tests — Health endpoint
# ===========================================================================

class TestHealthContract:
    """GET /healthz — response shape."""

    def test_health_shape(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert isinstance(body["service"], str)
