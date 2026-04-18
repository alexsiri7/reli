"""Tests for tools.calendar_create_event and calendar_update_event."""

import json
from unittest.mock import patch

from backend.tools import calendar_create_event, calendar_update_event, create_thing


class TestCalendarCreateEvent:
    def test_returns_error_when_not_connected(self, patched_db):
        with patch("backend.google_calendar.is_connected", return_value=False):
            result = calendar_create_event(
                thing_id="some-id",
                summary="Test Event",
                start="2026-04-22T18:00:00Z",
                end="2026-04-22T19:00:00Z",
            )
        assert "error" in result

    def test_creates_event_and_stores_id_on_thing(self, patched_db):
        thing = create_thing(title="Rehearsal", type_hint="event")
        thing_id = thing["id"]

        mock_event = {
            "id": "cal_event_abc",
            "summary": "Rehearsal",
            "start": "2026-04-22T18:00:00Z",
            "end": "2026-04-22T19:00:00Z",
            "html_link": "https://calendar.google.com/event?eid=abc",
        }

        with (
            patch("backend.google_calendar.is_connected", return_value=True),
            patch("backend.google_calendar.create_event", return_value=mock_event),
        ):
            result = calendar_create_event(
                thing_id=thing_id,
                summary="Rehearsal",
                start="2026-04-22T18:00:00Z",
                end="2026-04-22T19:00:00Z",
            )

        assert result["id"] == "cal_event_abc"

        # Verify calendar_event_id stored on Thing
        from backend.tools import get_thing

        updated = get_thing(thing_id)
        assert updated["data"]["calendar_event_id"] == "cal_event_abc"

    def test_returns_error_when_calendar_create_fails(self, patched_db):
        thing = create_thing(title="Test Event", type_hint="event")
        with (
            patch("backend.google_calendar.is_connected", return_value=True),
            patch("backend.google_calendar.create_event", return_value={}),
        ):
            result = calendar_create_event(
                thing_id=thing["id"],
                summary="Test Event",
                start="2026-04-22T18:00:00Z",
                end="2026-04-22T19:00:00Z",
            )
        assert "error" in result

    def test_logs_warning_when_link_store_fails(self, patched_db):
        """Event created successfully but update_thing fails — tool returns event, not error."""
        mock_event = {
            "id": "cal_event_abc",
            "summary": "Rehearsal",
            "start": "2026-04-22T18:00:00Z",
            "end": "2026-04-22T19:00:00Z",
            "html_link": "https://calendar.google.com/event?eid=abc",
        }
        with (
            patch("backend.google_calendar.is_connected", return_value=True),
            patch("backend.google_calendar.create_event", return_value=mock_event),
            patch("backend.tools.update_thing", return_value={"error": "Thing not found"}),
        ):
            result = calendar_create_event(
                thing_id="nonexistent-id",
                summary="Rehearsal",
                start="2026-04-22T18:00:00Z",
                end="2026-04-22T19:00:00Z",
            )
        # Event was created; tool returns it despite linkage failure
        assert result["id"] == "cal_event_abc"
        assert "error" not in result


class TestCalendarUpdateEvent:
    def test_returns_error_when_not_connected(self, patched_db):
        with patch("backend.google_calendar.is_connected", return_value=False):
            result = calendar_update_event(thing_id="some-id", summary="New Title")
        assert "error" in result

    def test_returns_error_when_no_calendar_event_id(self, patched_db):
        thing = create_thing(title="Event Without Calendar ID", type_hint="event")
        with patch("backend.google_calendar.is_connected", return_value=True):
            result = calendar_update_event(thing_id=thing["id"], summary="New Title")
        assert "error" in result
        assert "calendar_event_id" in result["error"]

    def test_returns_error_when_thing_not_found(self, patched_db):
        with patch("backend.google_calendar.is_connected", return_value=True):
            result = calendar_update_event(thing_id="nonexistent-id", summary="New Title")
        assert "error" in result

    def test_updates_event_when_id_present(self, patched_db):
        thing = create_thing(
            title="Team Meeting",
            type_hint="event",
            data_json=json.dumps({"calendar_event_id": "cal_evt_xyz"}),
        )
        mock_event = {
            "id": "cal_evt_xyz",
            "summary": "Team Meeting Updated",
            "start": "2026-04-22T18:00:00Z",
            "end": "2026-04-22T19:00:00Z",
            "html_link": "https://calendar.google.com/event?eid=xyz",
        }
        with (
            patch("backend.google_calendar.is_connected", return_value=True),
            patch("backend.google_calendar.update_event", return_value=mock_event),
        ):
            result = calendar_update_event(thing_id=thing["id"], summary="Team Meeting Updated")
        assert result["id"] == "cal_evt_xyz"

    def test_returns_error_when_update_fails(self, patched_db):
        """gc.update_event returns {} (API failure) → tools layer returns error dict."""
        thing = create_thing(
            title="Event",
            type_hint="event",
            data_json=json.dumps({"calendar_event_id": "cal_evt_xyz"}),
        )
        with (
            patch("backend.google_calendar.is_connected", return_value=True),
            patch("backend.google_calendar.update_event", return_value={}),
        ):
            result = calendar_update_event(thing_id=thing["id"], summary="Updated")
        assert "error" in result
