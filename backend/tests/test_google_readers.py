"""The three resolution-shaped readers, against recorded fixtures and never against Google.

Every request goes through ``httpx.MockTransport``, so no test here opens a socket. The handler
refuses any verb but ``GET`` outside the token endpoint, which is the executable form of the
issue's "both integrations are read-only".
"""

from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from backend import google_client
from backend.google_client import TOKEN_URL
from backend.google_readers import (
    _CALENDAR_PAGE_LIMIT,
    _CALENDAR_PAGE_SIZE,
    MAX_RESULTS,
    check_occurred,
    find_correspondence,
    find_events,
)

SINCE = date(2026, 9, 7)
UNTIL = date(2026, 9, 9)


@pytest.fixture(autouse=True)
def _configured(configured):
    """Every reader test runs with a credential set; ``configured`` itself lives in conftest."""


@pytest.fixture()
def paging_calendar(monkeypatch):
    """A Calendar that truncates at ``maxResults`` and pages, the way Google's own does.

    The shared ``google`` fixture returns a whole fixture file in one page regardless of the cap,
    which is exactly the behaviour that hid the starvation this fixture exists to reproduce.
    """
    seen: list[httpx.Request] = []

    def install(events):
        def handler(request):
            if str(request.url) == TOKEN_URL:
                return httpx.Response(200, json={"access_token": "access-token", "expires_in": 3600})

            seen.append(request)
            if request.url.path.startswith("/gmail/"):
                return httpx.Response(200, json={"resultSizeEstimate": 0})

            query = _query(request)
            start = int(query.get("pageToken", 0))
            page = events[start : start + int(query["maxResults"])]
            body = {"items": page}
            if start + len(page) < len(events):
                body["nextPageToken"] = str(start + len(page))
            return httpx.Response(200, json=body)

        monkeypatch.setattr(google_client, "_http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
        return seen

    return install


def _all_day(event_id, day):
    """An all-day event as Calendar returns one: bare dates, and an exclusive end."""
    ends = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    return {"id": event_id, "summary": event_id, "start": {"date": day}, "end": {"date": ends}}


def _api_requests(google, prefix):
    return [request for request in google.seen if request.url.path.startswith(prefix)]


def _query(request):
    return {key: values[0] for key, values in parse_qs(urlparse(str(request.url)).query).items()}


# --- Read-only ------------------------------------------------------------


def test_no_google_request_uses_a_write_verb(google):
    """The issue's first acceptance criterion, as an assertion rather than a promise."""
    find_correspondence("dentist", since=SINCE, until=UNTIL)
    find_events(since=SINCE, until=UNTIL)
    check_occurred("dentist", since=SINCE, until=UNTIL)

    assert google.seen
    assert {request.method for request in google.seen} == {"GET"}


# --- Gmail ----------------------------------------------------------------


def test_find_correspondence_summarises_and_never_returns_a_payload(google):
    messages = find_correspondence("dentist", since=SINCE, until=UNTIL)

    assert [message["id"] for message in messages] == ["19a1b2c3d4e5f601", "19a1b2c3d4e5f602"]
    assert set(messages[0]) == {"id", "thread_id", "from", "to", "subject", "date", "snippet", "labels"}
    assert messages[0]["from"] == "Reception <reception@example.test>"
    assert messages[0]["subject"] == "Appointment confirmed"
    assert messages[0]["labels"] == ["INBOX", "CATEGORY_PERSONAL"]
    assert "payload" not in messages[0]


def test_a_missing_header_becomes_none(google):
    """The second fixture message carries no Subject, and a reader must not raise over it."""
    messages = find_correspondence("dentist")

    assert messages[1]["subject"] is None


def test_internal_date_becomes_an_iso_utc_string(google):
    messages = find_correspondence("dentist")

    assert messages[0]["date"] == "2026-09-08T08:00:00+00:00"
    assert messages[1]["date"] == "2026-09-09T16:32:11+00:00"


def test_message_bodies_are_never_fetched(google):
    find_correspondence("dentist")

    details = _api_requests(google, "/gmail/v1/users/me/messages/")
    assert details
    assert all(_query(request)["format"] == "metadata" for request in details)


def test_until_is_inclusive_in_the_gmail_query(google):
    find_correspondence("dentist", since=SINCE, until=UNTIL)

    query = _query(_api_requests(google, "/gmail/v1/users/me/messages")[0])["q"]
    assert query == "dentist after:2026/09/07 before:2026/09/10"


def test_an_unbounded_query_carries_no_date_terms(google):
    find_correspondence("dentist")

    assert _query(_api_requests(google, "/gmail/v1/users/me/messages")[0])["q"] == "dentist"


def test_the_gmail_n_plus_one_is_capped(google):
    google.responses["messages"] = {"messages": [{"id": f"id-{n}", "threadId": "t"} for n in range(40)]}

    messages = find_correspondence("dentist", limit=100)

    assert len(messages) == MAX_RESULTS
    assert len(_api_requests(google, "/gmail/v1/users/me/messages/")) == MAX_RESULTS


def test_no_results_cost_no_detail_requests(google):
    google.responses["messages"] = {"resultSizeEstimate": 0}

    assert find_correspondence("dentist") == []
    assert _api_requests(google, "/gmail/v1/users/me/messages/") == []


# --- Calendar -------------------------------------------------------------


def test_find_events_expands_recurrences_and_orders_by_start(google):
    find_events(since=SINCE, until=UNTIL)

    query = _query(_api_requests(google, "/calendar/v3/calendars/primary/events")[0])
    assert query["singleEvents"] == "true"
    assert query["orderBy"] == "startTime"


def test_find_events_requests_a_window_wider_than_it_was_asked_for(google):
    """timeMax is exclusive, so covering `until` itself takes a bound two days past it."""
    find_events(since=SINCE, until=UNTIL)

    query = _query(_api_requests(google, "/calendar/v3/calendars/primary/events")[0])
    assert query["timeMin"] == "2026-09-06T00:00:00Z"
    assert query["timeMax"] == "2026-09-11T00:00:00Z"


def test_find_events_filters_the_widened_window_back_by_local_date(google):
    google.responses["events"] = google.fixture("events_boundary")

    events = find_events(since=SINCE, until=UNTIL)

    assert [event["id"] for event in events] == ["on-the-until-boundary"]
    assert events[0]["all_day"] is True


def test_find_events_summarises_a_timed_event(google):
    events = find_events(since=SINCE, until=UNTIL)

    assert set(events[0]) == {
        "id",
        "summary",
        "start",
        "end",
        "all_day",
        "status",
        "location",
        "attendee_count",
        "self_response",
        "description",
        "html_link",
    }
    assert events[0]["all_day"] is False
    assert events[0]["start"] == "2026-09-08T09:30:00+02:00"
    assert events[0]["attendee_count"] == 2
    assert events[0]["self_response"] == "tentative"


def test_a_long_description_is_truncated(google):
    events = find_events(since=SINCE, until=UNTIL)

    assert len(events[0]["description"]) == 501
    assert events[0]["description"].endswith("…")


def test_an_event_without_attendees_reports_nobody(google):
    google.responses["events"] = {
        "items": [{"id": "solo", "start": {"date": "2026-09-08"}, "end": {"date": "2026-09-09"}}]
    }

    events = find_events(since=SINCE, until=UNTIL)

    assert events[0]["attendee_count"] == 0
    assert events[0]["self_response"] is None
    assert events[0]["location"] is None


# --- Calendar paging ------------------------------------------------------


def test_a_busy_padding_day_does_not_starve_the_window(paging_calendar):
    """The window is widened by a day on each side, and Google truncates before Reli filters.

    A day of events just outside the window must not consume the whole answer: what the caller
    asked about is inside it.
    """
    padding = [_all_day(f"padding-{n}", "2026-09-06") for n in range(_CALENDAR_PAGE_SIZE + 5)]
    seen = paging_calendar([*padding, _all_day("real-event-in-window", "2026-09-08")])

    events = find_events(since=SINCE, until=UNTIL)

    assert [event["id"] for event in events] == ["real-event-in-window"]
    assert len(seen) == 2


def test_check_occurred_sees_an_event_a_busy_padding_day_would_have_hidden(paging_calendar):
    """check_occurred composes find_events, so the starvation would silently zero event_count."""
    padding = [_all_day(f"padding-{n}", "2026-09-06") for n in range(_CALENDAR_PAGE_SIZE + 5)]
    paging_calendar([*padding, _all_day("real-event-in-window", "2026-09-08")])

    result = check_occurred("quarterly review", since=SINCE, until=UNTIL)

    assert result["event_count"] == 1
    assert [event["id"] for event in result["events"]] == ["real-event-in-window"]


def test_paging_stops_as_soon_as_the_window_is_filled(paging_calendar):
    in_window = [_all_day(f"in-window-{n}", "2026-09-08") for n in range(10)]
    seen = paging_calendar([*in_window, _all_day("unreached", "2026-09-08")])

    events = find_events(since=SINCE, until=UNTIL, limit=3)

    assert [event["id"] for event in events] == ["in-window-0", "in-window-1", "in-window-2"]
    assert len(seen) == 1


def test_paging_gives_up_at_the_page_ceiling(paging_calendar):
    """A calendar dense enough to page forever costs a bounded number of requests, not all of them."""
    padding = [_all_day(f"padding-{n}", "2026-09-06") for n in range(_CALENDAR_PAGE_SIZE * (_CALENDAR_PAGE_LIMIT + 2))]
    seen = paging_calendar(padding)

    assert find_events(since=SINCE, until=UNTIL) == []
    assert len(seen) == _CALENDAR_PAGE_LIMIT


# --- check_occurred -------------------------------------------------------


def test_check_occurred_returns_both_kinds_of_evidence_with_their_counts(google):
    result = check_occurred("quarterly review", since=SINCE, until=UNTIL)

    assert result["description"] == "quarterly review"
    assert result["since"] == "2026-09-07"
    assert result["until"] == "2026-09-09"
    assert result["event_count"] == len(result["events"]) == 1
    assert result["message_count"] == len(result["messages"]) == 2


def test_check_occurred_returns_no_verdict(google):
    """Deciding is the caller's job: no boolean, no score, nothing derived from the evidence.

    Deliberately not recursive — an event summary legitimately carries ``all_day``, which is a
    bool, and what this guards is the top-level answer Reli would be putting words in Claude's
    mouth with.
    """
    result = check_occurred("quarterly review", since=SINCE, until=UNTIL)

    assert not {"found", "occurred", "confidence", "score"} & set(result)
    assert not [key for key, value in result.items() if isinstance(value, bool)]


def test_check_occurred_caps_each_source_separately(google):
    """The cap the tool docstring promises is per source, and the composed call is what a
    resolution pass actually makes."""
    google.responses["messages"] = {"messages": [{"id": f"id-{n}", "threadId": "t"} for n in range(40)]}
    google.responses["events"] = {"items": [_all_day(f"event-{n}", "2026-09-08") for n in range(40)]}

    result = check_occurred("quarterly review", since=SINCE, until=UNTIL, limit=100)

    assert result["message_count"] == MAX_RESULTS
    assert result["event_count"] == MAX_RESULTS
    assert len(_api_requests(google, "/gmail/v1/users/me/messages/")) == MAX_RESULTS


def test_check_occurred_reads_both_sources_over_the_same_window(google):
    check_occurred("quarterly review", since=SINCE, until=UNTIL)

    assert _api_requests(google, "/calendar/v3/calendars/primary/events")
    assert _query(_api_requests(google, "/gmail/v1/users/me/messages")[0])["q"] == (
        "quarterly review after:2026/09/07 before:2026/09/10"
    )
