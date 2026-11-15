"""The write rules on their own, with no database (#1796).

``test_service.py`` and ``test_user_model.py`` prove the service applies these rules and writes
nothing when one refuses; these tests prove what each rule decides.
"""

import re
import uuid
from datetime import UTC, date, datetime

import pytest

from backend.db_models import (
    INTERNAL_TAGS,
    NEW_TAG,
    OBSERVATION_TAG,
    SCHEDULED_TASK_TAG,
    RelationshipType,
)
from backend.tests.test_architecture import BACKEND
from backend.thing_rules import (
    BACKFILL_PER_DAY,
    MAX_MAPPING_BYTES,
    MAX_SCOPE_CHARS,
    FieldTooLarge,
    backfill_defaults,
    capture_defaults,
    check_edge_shape,
    check_evidence_source,
    check_heartbeat_kept,
    check_thing_fields,
    default_checkin_date,
    has_recordable_scope,
    is_internal,
    normalise_preference,
)

# 10:00 London on 10 September 2026; tomorrow is the 11th.
NOW = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
TOMORROW = date(2026, 9, 11)
THING = uuid.UUID(int=1)
OTHER = uuid.UUID(int=2)


def test_the_rules_never_touch_the_database():
    source = (BACKEND / "thing_rules.py").read_text()

    assert not re.search(r"^\s*(from|import) (sqlalchemy|sqlmodel|\.db_engine|backend\.db_engine)\b", source, re.M)


# --- Field bounds ----------------------------------------------------------


def test_mapping_size_counts_bytes_not_characters():
    """A note of multi-byte characters is measured by what it costs to store, not by its length."""
    with pytest.raises(FieldTooLarge, match="bytes"):
        check_thing_fields(notes={"k": "é" * (MAX_MAPPING_BYTES // 2)})


@pytest.mark.parametrize("priority", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_priority_is_refused(priority):
    with pytest.raises(ValueError, match="finite"):
        check_thing_fields(priority=priority)


# --- Captures --------------------------------------------------------------


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
    assert default_checkin_date(now) == tomorrow


@pytest.mark.parametrize("tag", INTERNAL_TAGS)
def test_any_internal_tag_makes_a_record_internal(tag):
    assert is_internal(["#Project", tag])


def test_a_capture_is_not_internal():
    assert not is_internal(["#Project", NEW_TAG])
    assert not is_internal([])


def test_a_bare_capture_is_marked_new_and_due_tomorrow():
    assert capture_defaults(None, None, NOW) == ([NEW_TAG], TOMORROW)


def test_a_capture_keeps_its_tags_its_date_and_a_single_mark():
    given = date(2026, 12, 1)

    assert capture_defaults(["#Project"], given, NOW) == (["#Project", NEW_TAG], given)
    assert capture_defaults([NEW_TAG], None, NOW) == ([NEW_TAG], TOMORROW)


def test_capture_defaults_does_not_mutate_the_callers_tags():
    tags = ["#Project"]

    capture_defaults(tags, None, NOW)

    assert tags == ["#Project"]


@pytest.mark.parametrize("tag", INTERNAL_TAGS)
def test_an_internal_record_gets_neither_the_mark_nor_the_date(tag):
    assert capture_defaults([tag], None, NOW) == ([tag], None)


def test_the_backfill_spreads_captures_a_morning_at_a_time():
    dates = [
        backfill_defaults(tags=[], description="filled in", position=position, now=NOW)[1]
        for position in range(BACKFILL_PER_DAY + 1)
    ]

    assert dates == [TOMORROW] * BACKFILL_PER_DAY + [date(2026, 9, 12)]


def test_the_backfill_marks_only_a_bare_capture_new_and_only_once():
    assert backfill_defaults(tags=["#Project"], description=None, position=0, now=NOW)[0] == ["#Project", NEW_TAG]
    assert backfill_defaults(tags=["#Project"], description="", position=0, now=NOW)[0] == ["#Project", NEW_TAG]
    assert backfill_defaults(tags=[NEW_TAG], description=None, position=0, now=NOW)[0] == [NEW_TAG]
    assert backfill_defaults(tags=["#Project"], description="notes", position=0, now=NOW)[0] == ["#Project"]


# --- Heartbeats ------------------------------------------------------------


@pytest.mark.parametrize(
    ("new_tags", "active", "refusal"),
    [(None, False, "archived"), (["#Other"], None, "keep that tag"), ([], True, "keep that tag")],
)
def test_a_heartbeat_cannot_be_archived_or_lose_its_tag(new_tags, active, refusal):
    with pytest.raises(ValueError, match=refusal):
        check_heartbeat_kept(THING, [SCHEDULED_TASK_TAG], new_tags, active)


def test_a_heartbeat_takes_its_routine_writes():
    check_heartbeat_kept(THING, [SCHEDULED_TASK_TAG], [SCHEDULED_TASK_TAG, "#Kept"], True)
    check_heartbeat_kept(THING, [SCHEDULED_TASK_TAG], None, None)


def test_a_thing_that_is_not_a_heartbeat_may_be_archived_and_retagged():
    check_heartbeat_kept(THING, ["#Project"], [], False)


# --- Edges -----------------------------------------------------------------


@pytest.mark.parametrize("relationship_type", list(RelationshipType))
def test_an_edge_cannot_run_from_a_thing_to_itself(relationship_type):
    with pytest.raises(ValueError, match="itself"):
        check_edge_shape(THING, THING, relationship_type)

    check_edge_shape(THING, OTHER, relationship_type)


@pytest.mark.parametrize("tag", [tag for tag in INTERNAL_TAGS if tag != OBSERVATION_TAG])
def test_relis_own_records_cannot_stand_as_evidence(tag):
    with pytest.raises(ValueError, match=re.escape(tag)):
        check_evidence_source(THING, ["#Meeting", tag])


def test_an_observation_or_a_capture_stands_as_evidence():
    check_evidence_source(THING, [OBSERVATION_TAG])
    check_evidence_source(THING, ["#Meeting", NEW_TAG])


# --- Preferences -----------------------------------------------------------


def test_a_preference_keeps_its_scopes_case_and_its_evidence_in_order_once():
    assert normalise_preference("  Scheduling\t", [OTHER, THING, OTHER]) == ("Scheduling", [OTHER, THING])


@pytest.mark.parametrize("scope", ["", "   ", "\t\n"])
def test_a_preference_must_declare_a_scope(scope):
    with pytest.raises(ValueError, match="scope"):
        normalise_preference(scope, [THING])


def test_a_preference_scope_is_bounded():
    with pytest.raises(FieldTooLarge, match="scope"):
        normalise_preference("s" * (MAX_SCOPE_CHARS + 1), [THING])


def test_a_preference_with_no_evidence_is_not_recordable():
    with pytest.raises(ValueError, match="no evidence"):
        normalise_preference("scheduling", [])


@pytest.mark.parametrize(
    ("notes", "recordable"), [({"scope": "planning"}, True), ({"scope": " \t"}, False), ({}, False)]
)
def test_a_stored_preference_needs_a_non_blank_scope(notes, recordable):
    assert has_recordable_scope(notes) is recordable


def test_the_read_and_the_write_floor_agree_on_a_blank_scope():
    for scope in ["", " ", "\t", "planning", " planning "]:
        try:
            normalise_preference(scope, [THING])
            written = True
        except ValueError:
            written = False
        assert written is has_recordable_scope({"scope": scope}), repr(scope)
