"""The rules a write to the graph must satisfy, as pure functions of the values written (#1796).

Nothing here touches a session: :mod:`backend.service` reads what a rule needs, calls it, and
keeps the lock, the cycle walk, the journal entry and the commit. A rule that needs the database
to decide — a ``ChildOf`` edge closing a cycle — stays in the service.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit

from .db_models import (
    INTERNAL_TAGS,
    NEW_TAG,
    OBSERVATION_TAG,
    OWNER_TIMEZONE,
    REJECTED_TAG,
    SCHEDULED_TASK_TAG,
    RelationshipType,
)

# --- Write bounds (#1478) ------------------------------------------------------
#
# Every field a caller can write has a ceiling, checked by the service before any statement is
# issued, so a single request cannot fill a row — and the journal's before/after copy of it — with
# megabytes. They are enforced on the write path rather than at the MCP boundary because the
# service is the one write path: whatever reaches the graph, by any route, passes through these
# checks. The numbers are generous on purpose. An update replaces a whole field, so a session
# adding one note resends every note the Thing already has; a ceiling a well-used Thing could
# reach would turn ordinary updates into refusals. Only the fields a call actually passes are
# checked, so a Thing written before the bounds existed stays updatable through the fields that
# are within them.
MAX_TITLE_CHARS = 500
MAX_DESCRIPTION_CHARS = 100_000
#: ``notes`` and ``urls`` each, measured as the UTF-8 JSON the column stores.
MAX_MAPPING_BYTES = 100_000
MAX_TAGS = 100
MAX_TAG_CHARS = 100
MAX_CONTEXT_CHARS = 2_000
MAX_SCOPE_CHARS = 100


class FieldTooLarge(ValueError):
    """Raised when a write exceeds one of the bounds above. The message names the field and the bound."""


def check_text(name: str, value: str | None, limit: int) -> None:
    if value is not None and len(value) > limit:
        raise FieldTooLarge(f"{name} is {len(value)} characters; the most a {name} may hold is {limit}")


def _check_mapping(name: str, value: Mapping[str, str] | None) -> None:
    if value is None:
        return
    size = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    if size > MAX_MAPPING_BYTES:
        raise FieldTooLarge(
            f"{name} serialises to {size} bytes; the most {name} may hold is {MAX_MAPPING_BYTES} bytes — "
            "keep long material outside Reli and link to it"
        )


def _check_urls(urls: Mapping[str, str] | None) -> None:
    """Refuse a ``urls`` value that is not an absolute http(s) URL (#1822).

    The web view already renders only http(s) values as links; refusing the rest here means no other
    reader of the graph has to repeat that check. ``urlsplit`` lowercases the scheme and strips the
    leading whitespace a prefix match would miss.

    On the scheme this agrees with the view's ``isLinkable``; on the rest of the shape it is
    deliberately stricter. It also demands ``//`` and a host, so it refuses ``https:no-host``, which
    the browser's parser would repair into ``https://no-host/`` and link. A value stored before this
    check, or one ``urlsplit`` accepts and the browser cannot parse, is still shown as text there.
    """
    for name, url in (urls or {}).items():
        try:
            parts = urlsplit(url)
        except ValueError:
            parts = None
        if parts is None or parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(f"urls[{name!r}] must be an absolute http or https URL with a host, not {url!r}")


def check_thing_fields(
    *,
    title: str | None = None,
    description: str | None = None,
    notes: Mapping[str, str] | None = None,
    tags: Sequence[str] | None = None,
    urls: Mapping[str, str] | None = None,
    priority: float | None = None,
) -> None:
    """Refuse a Thing write whose given fields exceed the bounds. ``None`` means not given."""
    check_text("title", title, MAX_TITLE_CHARS)
    check_text("description", description, MAX_DESCRIPTION_CHARS)
    _check_mapping("notes", notes)
    _check_mapping("urls", urls)
    _check_urls(urls)
    if tags is not None:
        if len(tags) > MAX_TAGS:
            raise FieldTooLarge(f"{len(tags)} tags given; a Thing may carry at most {MAX_TAGS}")
        for tag in tags:
            check_text("tag", tag, MAX_TAG_CHARS)
    # NaN and infinity sort unpredictably in every priority-ordered listing, and Postgres stores both.
    if priority is not None and not math.isfinite(priority):
        raise ValueError(f"priority must be a finite number, not {priority}")


# --- Captures (#1516) ------------------------------------------------------------


def is_internal(tags: Iterable[str]) -> bool:
    """Whether *tags* mark one of Reli's own records, which is never a capture."""
    return any(tag in INTERNAL_TAGS for tag in tags)


def default_checkin_date(now: datetime) -> date:
    """Tomorrow as the owner would say it — the next ``OWNER_TIMEZONE`` day, not the next UTC day."""
    return now.astimezone(OWNER_TIMEZONE).date() + timedelta(days=1)


def _marked_new(tags: Sequence[str]) -> list[str]:
    return [*tags] if NEW_TAG in tags else [*tags, NEW_TAG]


def capture_defaults(
    tags: Sequence[str] | None, checkin_date: date | None, now: datetime
) -> tuple[list[str], date | None]:
    """The tags and check-in date a new Thing is created with.

    A capture is what the owner has not yet been asked about: unless *tags* is internal, it is
    tagged ``NEW_TAG``, and a missing *checkin_date* becomes :func:`default_checkin_date` so it
    comes up in the morning rather than never. A date given explicitly is kept as given, and
    Reli's own records get neither the tag nor the date.
    """
    tags = list(tags) if tags is not None else []
    if is_internal(tags):
        return tags, checkin_date
    return _marked_new(tags), checkin_date if checkin_date is not None else default_checkin_date(now)


#: How many backfilled Things fall due on one day. The morning conversation asks about three to
#: five ``NEW_TAG`` Things a morning, so a day of the backfill is the size of one morning's batch.
BACKFILL_PER_DAY = 5


def backfill_defaults(
    *, tags: Sequence[str], description: str | None, position: int, now: datetime
) -> tuple[list[str], date]:
    """The tags and check-in date the #1517 backfill gives the undated capture at *position*.

    Captures fall due ``BACKFILL_PER_DAY`` to a day from :func:`default_checkin_date`, so the
    backlog does not all fall due on one morning. One with no description is a bare capture that
    was never filled in, so it is marked ``NEW_TAG`` as well.
    """
    checkin_date = default_checkin_date(now) + timedelta(days=position // BACKFILL_PER_DAY)
    return (list(tags) if description else _marked_new(tags)), checkin_date


# --- Heartbeats (#1704) ----------------------------------------------------------

#: How far ahead a heartbeat's check-in date may be set: each run sets tomorrow, so anything later
#: would keep a missed run from falling due (#1806).
HEARTBEAT_MAX_DAYS_AHEAD = 2


def check_heartbeat_kept(
    thing_id: uuid.UUID,
    current_tags: Sequence[str],
    new_tags: Sequence[str] | None,
    active: bool | None,
    checkin_date: date | None = None,
    *,
    now: datetime | None = None,
) -> None:
    """Refuse archiving a heartbeat, dropping its tag, or dating it far ahead (#1806).

    A missed scheduled run is reported only as its ``SCHEDULED_TASK_TAG`` Thing left due, found by
    that tag among active Things; any of these writes would hide the miss instead of reporting it.
    """
    if SCHEDULED_TASK_TAG not in current_tags:
        return
    if active is False:
        raise ValueError(f"Thing {thing_id} is a {SCHEDULED_TASK_TAG} heartbeat and cannot be archived")
    if new_tags is not None and SCHEDULED_TASK_TAG not in new_tags:
        raise ValueError(f"Thing {thing_id} is a {SCHEDULED_TASK_TAG} heartbeat and must keep that tag")
    if checkin_date is not None:
        today = (now if now is not None else datetime.now(UTC)).astimezone(OWNER_TIMEZONE).date()
        latest = today + timedelta(days=HEARTBEAT_MAX_DAYS_AHEAD)
        if checkin_date > latest:
            raise ValueError(
                f"Thing {thing_id} is a {SCHEDULED_TASK_TAG} heartbeat and its checkin_date cannot be later "
                f"than {latest.isoformat()}"
            )


def check_rejection_kept(thing_id: uuid.UUID, current_tags: Sequence[str], new_tags: Sequence[str] | None) -> None:
    """Refuse a tags write that drops ``REJECTED_TAG`` (#1807).

    A rejection is the owner's correction and nothing undoes it: dropping the tag would put the
    preference back in the model, journalled under whoever wrote the list.
    """
    if REJECTED_TAG in current_tags and new_tags is not None and REJECTED_TAG not in new_tags:
        raise ValueError(f"Thing {thing_id} is a rejected preference and must keep {REJECTED_TAG}")


# --- Edges (#1696) ---------------------------------------------------------------


def check_edge_shape(source_id: uuid.UUID, target_id: uuid.UUID, relationship_type: RelationshipType) -> None:
    """Refuse a self-loop of any type: it drops the Thing from the tree, or blocks it forever."""
    if source_id == target_id:
        raise ValueError(f"a {relationship_type.value} edge cannot run from Thing {source_id} to itself")


#: The internal tags an ``EvidenceFor`` source may not carry. ``#Observation`` is absent because an
#: observation is what evidence is meant to be; the rest are Reli's own records, and one of them
#: standing as evidence would add strength no observed moment supports.
_NOT_EVIDENCE_TAGS = tuple(tag for tag in INTERNAL_TAGS if tag != OBSERVATION_TAG)


def check_evidence_source(thing_id: uuid.UUID, tags: Iterable[str]) -> None:
    internal = [tag for tag in tags if tag in _NOT_EVIDENCE_TAGS]
    if internal:
        raise ValueError(f"Thing {thing_id} is tagged {', '.join(internal)} and cannot stand as evidence")


# --- Preferences (#1410) ---------------------------------------------------------


def _stripped_scope(scope: str | None) -> str:
    return (scope or "").strip()


def has_recordable_scope(notes: Mapping[str, str]) -> bool:
    """Whether a preference's notes declare the scope it applies to."""
    return bool(_stripped_scope(notes.get("scope")))


def normalise_preference(scope: str, evidence_ids: Iterable[uuid.UUID]) -> tuple[str, list[uuid.UUID]]:
    """The scope and evidence a preference is recorded with, or ``ValueError`` if it is not recordable.

    Evidence is required: a preference nobody can trace back to specific moments is the confidence
    float this design exists to avoid. The same evidence given twice counts once, because strength
    is the count of evidence edges.
    """
    scope = _stripped_scope(scope)
    if not scope:
        raise ValueError("a preference must declare the scope it applies to")
    check_text("scope", scope, MAX_SCOPE_CHARS)
    wanted = list(dict.fromkeys(evidence_ids))
    if not wanted:
        raise ValueError("a preference with no evidence is not recordable")
    return scope, wanted
