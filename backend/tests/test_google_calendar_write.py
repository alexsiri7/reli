"""Tests for google_calendar.create_event and update_event."""

from unittest.mock import MagicMock, patch

import pytest


class TestCreateEvent:
    def test_returns_empty_when_not_connected(self):
        with patch("backend.google_calendar.get_credentials", return_value=None):
            from backend.google_calendar import create_event
            result = create_event("Test Event", "2026-04-22T18:00:00Z", "2026-04-22T19:00:00Z")
        assert result == {}

    def test_creates_event_and_returns_dict(self):
        mock_event = {
            "id": "cal_event_123",
            "summary": "Test Event",
            "start": {"dateTime": "2026-04-22T18:00:00Z"},
            "end": {"dateTime": "2026-04-22T19:00:00Z"},
            "htmlLink": "https://calendar.google.com/event?eid=abc",
        }
        mock_service = MagicMock()
        mock_service.events().insert().execute.return_value = mock_event

        with (
            patch("backend.google_calendar.get_credentials", return_value=MagicMock()),
            patch("backend.google_calendar.build", return_value=mock_service),
            patch("backend.google_calendar.AuthorizedHttp", return_value=MagicMock()),
        ):
            from backend.google_calendar import create_event
            result = create_event(
                summary="Test Event",
                start="2026-04-22T18:00:00Z",
                end="2026-04-22T19:00:00Z",
                location="Conference Room",
                description="Team meeting",
            )

        assert result["id"] == "cal_event_123"
        assert result["summary"] == "Test Event"
        assert "html_link" in result

    def test_includes_location_in_body(self):
        """Verify location is included in the API call body."""
        mock_service = MagicMock()
        mock_service.events().insert().execute.return_value = {
            "id": "evt1", "summary": "Test", "start": {}, "end": {}, "htmlLink": ""
        }
        captured_body = {}

        def capture_insert(**kwargs):
            captured_body.update(kwargs.get("body", {}))
            return mock_service.events().insert()

        mock_service.events().insert = capture_insert

        with (
            patch("backend.google_calendar.get_credentials", return_value=MagicMock()),
            patch("backend.google_calendar.build", return_value=mock_service),
            patch("backend.google_calendar.AuthorizedHttp", return_value=MagicMock()),
        ):
            from backend.google_calendar import create_event
            create_event("Test", "2026-04-22T18:00:00Z", "2026-04-22T19:00:00Z", location="Room 1")

        assert captured_body.get("location") == "Room 1"


class TestUpdateEvent:
    def test_returns_empty_when_not_connected(self):
        with patch("backend.google_calendar.get_credentials", return_value=None):
            from backend.google_calendar import update_event
            result = update_event("evt_123", summary="New Title")
        assert result == {}

    def test_patches_only_provided_fields(self):
        existing_event = {
            "id": "evt_123",
            "summary": "Old Title",
            "start": {"dateTime": "2026-04-22T18:00:00Z", "timeZone": "UTC"},
            "end": {"dateTime": "2026-04-22T19:00:00Z", "timeZone": "UTC"},
        }
        updated_event = {**existing_event, "summary": "New Title",
                         "htmlLink": "https://calendar.google.com/event?eid=abc"}

        mock_service = MagicMock()
        mock_service.events().get().execute.return_value = existing_event
        mock_service.events().update().execute.return_value = updated_event

        with (
            patch("backend.google_calendar.get_credentials", return_value=MagicMock()),
            patch("backend.google_calendar.build", return_value=mock_service),
            patch("backend.google_calendar.AuthorizedHttp", return_value=MagicMock()),
        ):
            from backend.google_calendar import update_event
            result = update_event("evt_123", summary="New Title")

        assert result["id"] == "evt_123"
        assert result["summary"] == "New Title"
