"""Calendar and Gmail, shaped around the question a check-in asks rather than around the APIs.

Three readers, all read-only, all returning summaries: a fixed set of scalar fields per item and
never the API's own response object. A Gmail message is fetched with ``format=metadata``, so the
body is never even retrieved.

None of these decides anything. :func:`check_occurred` returns the evidence it found and the counts
of it; whether that means the thing happened is the calling session's judgement, made outside this
service. Nothing here mutates a Thing, so nothing here journals.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from .google_client import get_json

_GMAIL_LIST = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
_GMAIL_MESSAGE = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
_CALENDAR_EVENTS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

_HEADERS = ("From", "To", "Subject", "Date")

# Gmail is an N+1: messages.list returns only ids, so each result costs another GET. The cap is
# the reason a broad query cannot turn one tool call into a hundred requests.
MAX_RESULTS = 25

_DESCRIPTION_LIMIT = 500


def find_correspondence(
    query: str,
    since: date | None = None,
    until: date | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Gmail messages matching ``query``, newest first, summarised.

    ``since`` and ``until`` are both inclusive dates.
    """
    terms = [query]
    if since is not None:
        terms.append(f"after:{since:%Y/%m/%d}")
    if until is not None:
        # Gmail's before: is exclusive, so an inclusive `until` is the day after it.
        terms.append(f"before:{until + timedelta(days=1):%Y/%m/%d}")

    capped = min(limit, MAX_RESULTS)
    listing = get_json(_GMAIL_LIST, {"q": " ".join(terms), "maxResults": capped})
    stubs: list[dict[str, Any]] = listing.get("messages") or []

    return [_message_summary(stub["id"]) for stub in stubs[:capped]]


def find_events(
    since: date,
    until: date,
    query: str | None = None,
    limit: int = MAX_RESULTS,
) -> list[dict[str, Any]]:
    """Calendar events between ``since`` and ``until`` inclusive, earliest first, summarised.

    All-day events come back as a bare date in the calendar's own timezone, which Reli does not
    store, so a UTC-midnight window can miss one sitting on either boundary. The request is
    therefore made a day wider on each side and the results filtered back by their local date.
    """
    params: dict[str, Any] = {
        "timeMin": _utc_midnight(since - timedelta(days=1)),
        # timeMax is exclusive, so covering `until + 1 day` takes a bound of `until + 2 days`.
        "timeMax": _utc_midnight(until + timedelta(days=2)),
        "singleEvents": "true",
        # orderBy=startTime requires singleEvents, which also expands a recurrence into the
        # occurrences a resolution question is actually about.
        "orderBy": "startTime",
        "maxResults": min(limit, MAX_RESULTS),
    }
    if query:
        params["q"] = query

    payload = get_json(_CALENDAR_EVENTS, params)
    items: list[dict[str, Any]] = payload.get("items") or []

    return [_event_summary(item) for item in items if _within(item, since, until)]


def check_occurred(description: str, since: date, until: date, limit: int = 10) -> dict[str, Any]:
    """Everything Calendar and Gmail hold about ``description`` in the window, and nothing more.

    Returns evidence and counts. There is no verdict here by design: judging whether the thing
    happened is the caller's job, and a truth-value with no link to what produced it is what Reli
    exists to stop.
    """
    events = find_events(since=since, until=until, query=description, limit=limit)
    messages = find_correspondence(query=description, since=since, until=until, limit=limit)
    return {
        "description": description,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "events": events,
        "messages": messages,
        "event_count": len(events),
        "message_count": len(messages),
    }


def _utc_midnight(day: date) -> str:
    return f"{day.isoformat()}T00:00:00Z"


def _message_summary(message_id: str) -> dict[str, Any]:
    message = get_json(
        _GMAIL_MESSAGE.format(message_id=message_id),
        {"format": "metadata", "metadataHeaders": list(_HEADERS)},
    )
    headers = _header_values(message)
    return {
        "id": message.get("id", message_id),
        "thread_id": message.get("threadId"),
        "from": headers.get("from"),
        "to": headers.get("to"),
        "subject": headers.get("subject"),
        "date": _received_at(message.get("internalDate")),
        "snippet": message.get("snippet"),
        "labels": message.get("labelIds") or [],
    }


def _header_values(message: dict[str, Any]) -> dict[str, str | None]:
    payload: dict[str, Any] = message.get("payload") or {}
    headers: list[dict[str, Any]] = payload.get("headers") or []
    return {header["name"].lower(): header.get("value") for header in headers if header.get("name")}


def _received_at(internal_date: str | int | None) -> str | None:
    if internal_date is None:
        return None
    return datetime.fromtimestamp(int(internal_date) // 1000, UTC).isoformat()


def _event_summary(event: dict[str, Any]) -> dict[str, Any]:
    start: dict[str, Any] = event.get("start") or {}
    end: dict[str, Any] = event.get("end") or {}
    attendees: list[dict[str, Any]] = event.get("attendees") or []
    self_attendee = next((attendee for attendee in attendees if attendee.get("self")), None)

    return {
        "id": event.get("id"),
        "summary": event.get("summary"),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "all_day": "date" in start,
        "status": event.get("status"),
        "location": event.get("location"),
        "attendee_count": len(attendees),
        "self_response": self_attendee.get("responseStatus") if self_attendee else None,
        "description": _truncated(event.get("description")),
        "html_link": event.get("htmlLink"),
    }


def _within(event: dict[str, Any], since: date, until: date) -> bool:
    local_date = _local_date(event.get("start") or {})
    return local_date is not None and since <= local_date <= until


def _local_date(start: dict[str, Any]) -> date | None:
    stamp = start.get("date") or start.get("dateTime")
    if not stamp:
        return None
    return date.fromisoformat(stamp[:10])


def _truncated(description: str | None) -> str | None:
    if description is None or len(description) <= _DESCRIPTION_LIMIT:
        return description
    return description[:_DESCRIPTION_LIMIT] + "…"
