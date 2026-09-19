"""What a capture gets on create, and what Reli's own records do not (#1516).

A Thing with no check-in date never surfaces again, so ``create_thing`` dates a capture tomorrow and
marks it ``#New``; the five internal tags in ``INTERNAL_TAGS`` opt a Thing out of both, and out of
``due_for_checkin`` even when it carries a date. The set is written once, in ``db_models``, and the
last test here is what keeps it that way.
"""

import re
from datetime import UTC, date, datetime, timedelta

import pytest

from backend.db_models import (
    BRIEFING_TAG,
    INTERNAL_TAGS,
    NEW_TAG,
    OBSERVATION_TAG,
    PREFERENCE_TAG,
    SCHEDULED_TASK_TAG,
    USER_TAG,
    Actor,
)
from backend.queries import due_for_checkin
from backend.service import _default_checkin_date, create_thing
from backend.tests.test_architecture import BACKEND, _backend_sources

TODAY = date(2026, 9, 10)


def _thing(session, title, **fields):
    return create_thing(session, actor=Actor.CLAUDE_INTERACTIVE, title=title, **fields)


# --- The default check-in date ---------------------------------------------


def test_a_capture_with_no_date_is_due_tomorrow_in_london(session):
    before = datetime.now(UTC)
    thing = _thing(session, "bare")
    after = datetime.now(UTC)

    assert thing.checkin_date in {_default_checkin_date(before), _default_checkin_date(after)}


@pytest.mark.parametrize(
    ("now", "tomorrow"),
    [
        # 23:30 London in summer is 22:30 UTC; tomorrow is the next London day either way.
        (datetime(2026, 6, 15, 22, 30, tzinfo=UTC), date(2026, 6, 16)),
        # 23:30 UTC is already 00:30 on the 16th in London: tomorrow is the 17th, not the 16th.
        (datetime(2026, 6, 15, 23, 30, tzinfo=UTC), date(2026, 6, 17)),
        # In winter London is UTC, so 23:30 UTC is still the 15th and tomorrow is the 16th.
        (datetime(2026, 1, 15, 23, 30, tzinfo=UTC), date(2026, 1, 16)),
    ],
)
def test_tomorrow_is_the_next_london_day_including_near_midnight(now, tomorrow):
    assert _default_checkin_date(now) == tomorrow


def test_an_explicit_date_is_kept(session):
    thing = _thing(session, "dated", checkin_date=TODAY)

    assert thing.checkin_date == TODAY


# --- The #New mark ---------------------------------------------------------


def test_a_capture_is_marked_new_beside_its_own_tags(session):
    thing = _thing(session, "tagged", tags=["#Project"])

    assert thing.tags == ["#Project", NEW_TAG]


def test_a_capture_with_an_explicit_date_is_still_marked_new(session):
    thing = _thing(session, "dated", checkin_date=TODAY)

    assert NEW_TAG in thing.tags


def test_a_capture_already_marked_new_is_not_marked_twice(session):
    thing = _thing(session, "already", tags=[NEW_TAG])

    assert thing.tags == [NEW_TAG]


def test_the_callers_tag_list_is_not_mutated(session):
    tags = ["#Project"]

    _thing(session, "tagged", tags=tags)

    assert tags == ["#Project"]


# --- Reli's own records ----------------------------------------------------


@pytest.mark.parametrize("tag", INTERNAL_TAGS)
def test_an_internal_record_gets_neither_the_date_nor_the_mark(session, tag):
    thing = _thing(session, "bookkeeping", tags=[tag])

    assert thing.checkin_date is None
    assert thing.tags == [tag]


@pytest.mark.parametrize("tag", INTERNAL_TAGS)
def test_an_internal_record_is_never_due_even_with_a_date(session, tag):
    _thing(session, "heartbeat", tags=[tag], checkin_date=TODAY)
    _thing(session, "overdue heartbeat", tags=[tag, "#Other"], checkin_date=TODAY - timedelta(days=3))
    _thing(session, "capture", checkin_date=TODAY)

    assert [thing.title for thing in due_for_checkin(session, TODAY)] == ["capture"]


# --- One definition --------------------------------------------------------


def test_the_internal_tags_are_the_five_the_requirement_names():
    assert set(INTERNAL_TAGS) == {USER_TAG, PREFERENCE_TAG, OBSERVATION_TAG, SCHEDULED_TASK_TAG, BRIEFING_TAG}
    assert len(INTERNAL_TAGS) == len(set(INTERNAL_TAGS))


@pytest.mark.parametrize("tag", [*INTERNAL_TAGS, NEW_TAG])
def test_each_tag_literal_is_written_once_in_the_backend(tag):
    """A sixth internal tag must be a one-line change to ``INTERNAL_TAGS``.

    That holds only while every other module reaches the tags through the constants, so the
    literal itself may appear in ``db_models.py`` and nowhere else under ``backend/``.
    """
    pattern = re.compile(rf"[\"']{re.escape(tag)}[\"']")
    offenders = [
        path.relative_to(BACKEND).as_posix()
        for path in _backend_sources()
        if path.name != "db_models.py" and pattern.search(path.read_text())
    ]

    assert offenders == [], f"{tag} is spelled out in {offenders}"
    assert len(pattern.findall((BACKEND / "db_models.py").read_text())) == 1


def test_both_sides_read_the_one_constant():
    """The create-side skip and the read-side exclusion cannot drift if both import the tuple."""
    for module in ("service.py", "queries.py"):
        assert re.search(r"^\s+INTERNAL_TAGS,$", (BACKEND / module).read_text(), re.MULTILINE), module
