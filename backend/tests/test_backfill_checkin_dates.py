"""The one-off backfill that dates every active capture created before #1516's default (#1517).

The rule is ``service.backfill_checkin_dates`` and the tests here drive it directly on the fixture
session; the last test walks a fresh database through the ``v4_backfill_checkin_dates`` revision
itself, since ``migrated_db`` only ever runs it over an empty graph. The journal is append-only,
so every journal assertion is a delta.
"""

import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlmodel import Session

from backend.db_models import INTERNAL_TAGS, NEW_TAG, Actor, Operation, ThingRecord
from backend.service import BACKFILL_PER_DAY, backfill_checkin_dates, create_thing

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
TOMORROW = NOW.date() + timedelta(days=1)


def _legacy_thing(session, title, *, description=None, tags=(), active=True, age_days=0):
    """A Thing as the pre-#1516 create path left it: no check-in date and no ``#New``."""
    thing = create_thing(
        session, actor=Actor.CLAUDE_INTERACTIVE, title=title, description=description, tags=list(tags), active=active
    )
    session.execute(
        text("UPDATE things SET checkin_date = NULL, tags = CAST(:tags AS jsonb), created_at = :at WHERE id = :id"),
        {"tags": json.dumps(list(tags)), "at": NOW - timedelta(days=age_days), "id": thing.id},
    )
    session.commit()
    session.expire_all()
    return thing.id


def _reload(session, thing_id):
    session.expire_all()
    return session.get(ThingRecord, thing_id)


def _journal_count(session):
    return session.execute(text("SELECT count(*) FROM journal")).scalar_one()


def _entries_since(session, count_before):
    return session.execute(
        text("SELECT actor, operation, entity_id, before, after FROM journal ORDER BY id OFFSET :n"),
        {"n": count_before},
    ).all()


# --- Which Things it touches -----------------------------------------------


def test_an_active_thing_with_no_date_gets_one(session):
    undated = _legacy_thing(session, "undated")

    assert backfill_checkin_dates(session, now=NOW) == 1
    assert _reload(session, undated).checkin_date == TOMORROW


def test_a_thing_with_a_date_is_untouched(session):
    dated = create_thing(session, actor=Actor.CLAUDE_INTERACTIVE, title="dated", checkin_date=NOW.date())
    count_before = _journal_count(session)

    assert backfill_checkin_dates(session, now=NOW) == 0
    assert _reload(session, dated.id).checkin_date == NOW.date()
    assert _entries_since(session, count_before) == []


def test_a_thing_with_no_description_is_marked_new(session):
    bare = _legacy_thing(session, "bare", tags=["#Project"])

    backfill_checkin_dates(session, now=NOW)

    assert _reload(session, bare).tags == ["#Project", NEW_TAG]


def test_an_empty_description_counts_as_none(session):
    blank = _legacy_thing(session, "blank", description="")

    backfill_checkin_dates(session, now=NOW)

    assert NEW_TAG in _reload(session, blank).tags


def test_a_thing_with_a_description_gets_a_date_but_not_new(session):
    filled = _legacy_thing(session, "filled", description="already written up")

    backfill_checkin_dates(session, now=NOW)

    thing = _reload(session, filled)
    assert thing.checkin_date == TOMORROW
    assert NEW_TAG not in thing.tags


def test_a_thing_already_marked_new_is_not_marked_twice(session):
    marked = _legacy_thing(session, "marked", tags=[NEW_TAG])

    backfill_checkin_dates(session, now=NOW)

    assert _reload(session, marked).tags == [NEW_TAG]


def test_an_archived_thing_is_untouched(session):
    archived = _legacy_thing(session, "archived", active=False)
    count_before = _journal_count(session)

    assert backfill_checkin_dates(session, now=NOW) == 0

    thing = _reload(session, archived)
    assert thing.checkin_date is None
    assert thing.tags == []
    assert _entries_since(session, count_before) == []


@pytest.mark.parametrize("tag", INTERNAL_TAGS)
def test_an_internal_thing_is_untouched(session, tag):
    internal = _legacy_thing(session, "bookkeeping", tags=[tag])
    count_before = _journal_count(session)

    assert backfill_checkin_dates(session, now=NOW) == 0

    thing = _reload(session, internal)
    assert thing.checkin_date is None
    assert thing.tags == [tag]
    assert _entries_since(session, count_before) == []


# --- The spread ------------------------------------------------------------


def test_dates_are_spread_over_more_than_one_day_oldest_first(session):
    ids = [_legacy_thing(session, f"capture {n}", age_days=30 - n) for n in range(BACKFILL_PER_DAY * 2 + 1)]

    backfill_checkin_dates(session, now=NOW)

    dates = [_reload(session, thing_id).checkin_date for thing_id in ids]
    assert dates == sorted(dates)
    assert dates[0] == TOMORROW
    assert dates[BACKFILL_PER_DAY - 1] == TOMORROW
    assert dates[BACKFILL_PER_DAY] == TOMORROW + timedelta(days=1)
    assert dates[-1] == TOMORROW + timedelta(days=2)
    assert len(set(dates)) == 3


def test_no_assigned_date_is_in_the_past(session):
    for n in range(BACKFILL_PER_DAY * 3):
        _legacy_thing(session, f"old capture {n}", age_days=400 + n)

    backfill_checkin_dates(session, now=NOW)

    dates = session.execute(text("SELECT checkin_date FROM things")).scalars().all()
    assert min(dates) == TOMORROW


# --- Journalling -----------------------------------------------------------


def test_every_mutated_thing_is_journalled_as_claude_scheduled(session):
    bare = _legacy_thing(session, "bare")
    filled = _legacy_thing(session, "filled", description="written up")
    count_before = _journal_count(session)

    backfill_checkin_dates(session, now=NOW)

    entries = _entries_since(session, count_before)
    assert {entry.entity_id for entry in entries} == {bare, filled}
    assert {entry.actor for entry in entries} == {Actor.CLAUDE_SCHEDULED.value}
    assert {entry.operation for entry in entries} == {Operation.UPDATE.value}
    for entry in entries:
        assert entry.before["checkin_date"] is None
        assert entry.after["checkin_date"] == TOMORROW.isoformat()
    by_id = {entry.entity_id: entry for entry in entries}
    assert NEW_TAG not in by_id[bare].before["tags"]
    assert NEW_TAG in by_id[bare].after["tags"]
    assert NEW_TAG not in by_id[filled].after["tags"]


def test_nothing_is_committed_by_the_backfill_itself(session):
    undated = _legacy_thing(session, "undated")

    backfill_checkin_dates(session, now=NOW)
    session.rollback()

    assert _reload(session, undated).checkin_date is None


# --- Acceptance ------------------------------------------------------------


def test_afterwards_no_active_capture_is_undated_and_a_second_run_is_a_no_op(session):
    for n in range(BACKFILL_PER_DAY + 2):
        _legacy_thing(session, f"capture {n}", age_days=n)
    _legacy_thing(session, "archived", active=False)
    _legacy_thing(session, "heartbeat", tags=[INTERNAL_TAGS[0]])
    create_thing(session, actor=Actor.CLAUDE_INTERACTIVE, title="dated", checkin_date=NOW.date())

    assert backfill_checkin_dates(session, now=NOW) == BACKFILL_PER_DAY + 2
    session.commit()
    count_before = _journal_count(session)

    undated_captures = session.execute(
        text("SELECT title FROM things WHERE active AND checkin_date IS NULL AND NOT (tags ?| :internal)"),
        {"internal": list(INTERNAL_TAGS)},
    ).all()
    assert undated_captures == []

    assert backfill_checkin_dates(session, now=NOW + timedelta(days=1)) == 0
    assert _entries_since(session, count_before) == []


def test_the_revision_backfills_a_database_that_already_holds_captures(fresh_database):
    """The migration itself, over rows: the session it opens must land its writes in Alembic's
    transaction rather than roll them back when it closes."""
    from backend.db_engine import get_engine

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config = AlembicConfig(os.path.join(repo_root, "alembic.ini"))
    alembic_command.upgrade(config, "v4_refresh_token_families")

    with Session(get_engine()) as session:
        bare = _legacy_thing(session, "bare")
        filled = _legacy_thing(session, "filled", description="written up")
        heartbeat = _legacy_thing(session, "heartbeat", tags=[INTERNAL_TAGS[0]])
        count_before = _journal_count(session)

    alembic_command.upgrade(config, "head")

    with Session(get_engine()) as session:
        assert _reload(session, bare).checkin_date is not None
        assert NEW_TAG in _reload(session, bare).tags
        assert _reload(session, filled).checkin_date is not None
        assert NEW_TAG not in _reload(session, filled).tags
        assert _reload(session, heartbeat).checkin_date is None
        entries = _entries_since(session, count_before)
        assert {entry.entity_id for entry in entries} == {bare, filled}
        assert {entry.actor for entry in entries} == {Actor.CLAUDE_SCHEDULED.value}
