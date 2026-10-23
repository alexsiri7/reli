"""The semantics of the write path, beyond the journalling that test_journal.py covers."""

import threading
import time
import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlmodel import Session

from backend import service
from backend.db_models import (
    INTERNAL_TAGS,
    NEW_TAG,
    OBSERVATION_TAG,
    SCHEDULED_TASK_TAG,
    USER_ANCHOR_ID,
    Actor,
    RelationshipType,
    ThingRecord,
)
from backend.queries import tree_level
from backend.service import (
    DuplicateRelationship,
    FieldTooLarge,
    ThingNotFound,
    create_thing,
    relate,
    update_thing,
)


def _journal_count(session):
    return session.execute(text("SELECT count(*) FROM journal")).scalar_one()


def test_create_thing_defaults(session):
    """The capture defaults — tomorrow and ``#New`` — are test_capture_defaults.py's; the rest are here."""
    thing = create_thing(session, actor=Actor.USER, title="bare")

    assert thing.description is None
    assert thing.notes == {}
    assert thing.tags == [NEW_TAG]
    assert thing.urls == {}
    assert thing.checkin_date is not None
    assert thing.priority == 0.0
    assert thing.active is True
    assert thing.created_at == thing.updated_at


def test_update_thing_replaces_rather_than_merges(session):
    thing = create_thing(
        session,
        actor=Actor.USER,
        title="notes",
        notes={"keep": "a", "drop": "b"},
        tags=["one", "two"],
        urls={"home": "https://example.test"},
    )

    updated = update_thing(
        session,
        actor=Actor.USER,
        thing_id=thing.id,
        notes={"keep": "z"},
        tags=["three"],
        urls={"docs": "https://docs.test"},
    )

    assert updated.notes == {"keep": "z"}
    assert updated.tags == ["three"]
    assert updated.urls == {"docs": "https://docs.test"}


def test_update_thing_leaves_untouched_fields_alone(session):
    thing = create_thing(session, actor=Actor.USER, title="title", description="description", priority=3.0)

    updated = update_thing(session, actor=Actor.USER, thing_id=thing.id, title="new title")

    assert updated.title == "new title"
    assert updated.description == "description"
    assert updated.priority == 3.0


def test_update_thing_advances_updated_at(session):
    thing = create_thing(session, actor=Actor.USER, title="stamped")
    original = thing.updated_at

    updated = update_thing(session, actor=Actor.USER, thing_id=thing.id, title="restamped")

    assert updated.updated_at > original
    assert updated.created_at == thing.created_at


def test_update_thing_rejects_an_unknown_id(session):
    with pytest.raises(ThingNotFound):
        update_thing(session, actor=Actor.USER, thing_id=uuid.uuid4(), title="nobody")


def test_relate_rejects_a_type_outside_the_five(session):
    """The column type rejects it before the database CHECK has to; test_schema.py covers the CHECK."""
    source = create_thing(session, actor=Actor.USER, title="source")
    target = create_thing(session, actor=Actor.USER, title="target")

    with pytest.raises(ValueError, match="Supersedes"):
        relate(
            session,
            actor=Actor.USER,
            source_thing_id=source.id,
            target_thing_id=target.id,
            relationship_type="Supersedes",
        )
    session.rollback()


def test_a_failed_mutation_leaves_no_journal_entry(session):
    """The row and its journal entry share one transaction, so neither survives a failure."""
    before_count = _journal_count(session)

    with pytest.raises(DatabaseError):
        relate(
            session,
            actor=Actor.USER,
            source_thing_id=uuid.uuid4(),
            target_thing_id=uuid.uuid4(),
            relationship_type=RelationshipType.BLOCKS,
        )
    session.rollback()

    assert _journal_count(session) == before_count


def test_relate_refuses_a_second_evidence_for_edge_and_names_the_existing_one(session):
    """Strength is the count of ``EvidenceFor`` edges, so the database keeps a pair from carrying two."""
    evidence = create_thing(session, actor=Actor.USER, title="evidence")
    supported = create_thing(session, actor=Actor.USER, title="supported")
    first = relate(
        session,
        actor=Actor.USER,
        source_thing_id=evidence.id,
        target_thing_id=supported.id,
        relationship_type=RelationshipType.EVIDENCE_FOR,
    )
    before_count = _journal_count(session)

    with pytest.raises(DuplicateRelationship, match=str(first.id)) as raised:
        relate(
            session,
            actor=Actor.USER,
            source_thing_id=evidence.id,
            target_thing_id=supported.id,
            relationship_type=RelationshipType.EVIDENCE_FOR,
            context="asserted again",
        )

    assert raised.value.existing.id == first.id
    assert "add_preference_evidence" in str(raised.value)
    assert _journal_count(session) == before_count


def test_relate_allows_a_second_references_edge_between_the_same_pair(session):
    """Only ``EvidenceFor`` is counted; the other four types may carry a second, differently-reasoned edge."""
    source = create_thing(session, actor=Actor.USER, title="source")
    target = create_thing(session, actor=Actor.USER, title="target")

    edges = [
        relate(
            session,
            actor=Actor.USER,
            source_thing_id=source.id,
            target_thing_id=target.id,
            relationship_type=RelationshipType.REFERENCES,
            context=context,
        )
        for context in ("cites the figures", "quotes the conclusion")
    ]

    stored = (
        session.execute(
            text("SELECT context FROM relationships WHERE source_thing_id = :src AND target_thing_id = :tgt"),
            {"src": source.id, "tgt": target.id},
        )
        .scalars()
        .all()
    )
    assert len({edge.id for edge in edges}) == 2
    assert sorted(stored) == ["cites the figures", "quotes the conclusion"]


def test_a_failed_evidence_for_mutation_still_raises_the_database_error(session):
    """A foreign-key failure on an ``EvidenceFor`` edge is not a duplicate, and comes back as itself."""
    before_count = _journal_count(session)

    with pytest.raises(DatabaseError) as raised:
        relate(
            session,
            actor=Actor.USER,
            source_thing_id=uuid.uuid4(),
            target_thing_id=uuid.uuid4(),
            relationship_type=RelationshipType.EVIDENCE_FOR,
        )
    session.rollback()

    assert not isinstance(raised.value, DuplicateRelationship)
    assert _journal_count(session) == before_count


# --- Edges the read path would misread (#1696) ------------------------------------------------------


def _relate(session, source, target, relationship_type):
    return relate(
        session,
        actor=Actor.CLAUDE_INTERACTIVE,
        source_thing_id=source.id,
        target_thing_id=target.id,
        relationship_type=relationship_type,
    )


@pytest.mark.parametrize("relationship_type", list(RelationshipType))
def test_relate_refuses_a_self_loop_of_every_type(session, relationship_type):
    thing = create_thing(session, actor=Actor.USER, title="alone")
    before_count = _journal_count(session)

    with pytest.raises(ValueError, match="itself"):
        _relate(session, thing, thing, relationship_type)

    assert _journal_count(session) == before_count


def test_relate_refuses_a_child_of_cycle_and_the_tree_keeps_both_things(session):
    """A two-cycle would drop both Things from the top level: neither would be unclaimed."""
    a = create_thing(session, actor=Actor.USER, title="a")
    b = create_thing(session, actor=Actor.USER, title="b")
    _relate(session, a, b, RelationshipType.CHILD_OF)
    before_count = _journal_count(session)

    with pytest.raises(ValueError, match="cycle"):
        _relate(session, b, a, RelationshipType.CHILD_OF)

    assert _journal_count(session) == before_count
    assert a.id in {node.thing.id for node in tree_level(session)}
    assert [node.thing.id for node in tree_level(session, parent_id=a.id)] == [b.id]


def test_relate_refuses_a_child_of_edge_closing_a_longer_cycle(session):
    top, middle, bottom = (create_thing(session, actor=Actor.USER, title=title) for title in ("top", "mid", "low"))
    _relate(session, top, middle, RelationshipType.CHILD_OF)
    _relate(session, middle, bottom, RelationshipType.CHILD_OF)

    with pytest.raises(ValueError, match="cycle"):
        _relate(session, bottom, top, RelationshipType.CHILD_OF)


@pytest.mark.parametrize(
    ("held", "racing"),
    [
        pytest.param([("a", "b")], ("b", "a"), id="same-pair"),
        # A lock keyed on the edge's pair would let this one through: no held edge shares its pair.
        pytest.param([("a", "b"), ("b", "c")], ("c", "a"), id="across-pairs"),
    ],
)
def test_concurrent_child_of_edges_cannot_close_a_cycle_between_them(session, held, racing):
    """Each transaction's check misses the other's uncommitted edges unless the second one waits."""
    from backend.db_engine import get_engine

    things = {name: create_thing(session, actor=Actor.USER, title=name) for name in "abc"}
    session.commit()
    for source, target in held:
        service._insert_relationship(
            session,
            actor=Actor.CLAUDE_INTERACTIVE,
            source_thing_id=things[source].id,
            target_thing_id=things[target].id,
            relationship_type=RelationshipType.CHILD_OF,
        )
    outcome: list[BaseException] = []

    def close_the_cycle() -> None:
        with Session(get_engine()) as racer:
            try:
                _relate(racer, things[racing[0]], things[racing[1]], RelationshipType.CHILD_OF)
                racer.commit()
            except ValueError as exc:
                outcome.append(exc)

    racer = threading.Thread(target=close_the_cycle)
    racer.start()
    deadline = time.monotonic() + 5
    while not _waiting_on_an_advisory_lock(session) and racer.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    session.commit()
    racer.join()

    assert len(outcome) == 1 and "cycle" in str(outcome[0])
    edges = session.execute(text("SELECT count(*) FROM relationships WHERE relationship_type = 'ChildOf'")).scalar_one()
    assert edges == len(held)


def _waiting_on_an_advisory_lock(session):
    return (
        session.execute(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")).scalar_one()
        > 0
    )


def test_relate_allows_a_second_parent_and_a_reverse_edge_of_another_type(session):
    """Only a ``ChildOf`` path back to the source is a cycle; a diamond and a ``Blocks`` edge are not."""
    left, right, child = (create_thing(session, actor=Actor.USER, title=title) for title in ("l", "r", "c"))
    _relate(session, left, child, RelationshipType.CHILD_OF)
    _relate(session, right, child, RelationshipType.CHILD_OF)
    _relate(session, left, right, RelationshipType.CHILD_OF)

    _relate(session, child, left, RelationshipType.BLOCKS)


def test_the_cycle_check_ends_on_a_cycle_already_in_the_graph(session):
    """A cycle written before #1696 must not hang the walk that looks for a new one."""
    a, b, outside = (create_thing(session, actor=Actor.USER, title=title) for title in ("a", "b", "outside"))
    session.execute(
        text(
            "INSERT INTO relationships (id, source_thing_id, target_thing_id, relationship_type, created_at) "
            "VALUES (:one, :a, :b, 'ChildOf', now()), (:two, :b, :a, 'ChildOf', now())"
        ),
        {"one": uuid.uuid4(), "two": uuid.uuid4(), "a": a.id, "b": b.id},
    )
    session.commit()

    _relate(session, outside, a, RelationshipType.CHILD_OF)


@pytest.mark.parametrize("tag", [tag for tag in INTERNAL_TAGS if tag != OBSERVATION_TAG])
def test_relate_refuses_evidence_from_one_of_relis_own_records(session, tag):
    """A preference, the anchor, a heartbeat or a briefing as evidence is strength with no observation."""
    record = create_thing(session, actor=Actor.CLAUDE_SCHEDULED, title="internal", tags=[tag])
    supported = create_thing(session, actor=Actor.USER, title="supported")
    before_count = _journal_count(session)

    with pytest.raises(ValueError, match="evidence"):
        _relate(session, record, supported, RelationshipType.EVIDENCE_FOR)

    assert _journal_count(session) == before_count


def test_relate_accepts_an_observation_as_evidence(session):
    observation = create_thing(session, actor=Actor.CLAUDE_SCHEDULED, title="seen", tags=[OBSERVATION_TAG])
    supported = create_thing(session, actor=Actor.USER, title="supported")

    _relate(session, observation, supported, RelationshipType.EVIDENCE_FOR)


# --- Write bounds (#1478) --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "t" * (service.MAX_TITLE_CHARS + 1)),
        ("description", "d" * (service.MAX_DESCRIPTION_CHARS + 1)),
        ("notes", {"long": "n" * service.MAX_MAPPING_BYTES}),
        ("urls", {"long": "https://example.test/" + "u" * service.MAX_MAPPING_BYTES}),
        ("tags", [f"#t{i}" for i in range(service.MAX_TAGS + 1)]),
        ("tags", ["#" + "x" * service.MAX_TAG_CHARS]),
    ],
)
def test_an_oversized_create_is_refused_before_anything_is_written(session, field, value):
    before = _journal_count(session)
    things = session.execute(text("SELECT count(*) FROM things")).scalar_one()

    with pytest.raises(FieldTooLarge, match=field.rstrip("s")):
        create_thing(session, actor=Actor.USER, **{"title": "ok", field: value})

    assert _journal_count(session) == before
    assert session.execute(text("SELECT count(*) FROM things")).scalar_one() == things


def test_a_value_at_every_bound_is_accepted(session):
    """The bounds are inclusive, and a mapping is measured as the UTF-8 JSON the column stores."""
    padding = service.MAX_MAPPING_BYTES - len('{"k": ""}')
    thing = create_thing(
        session,
        actor=Actor.USER,
        title="t" * service.MAX_TITLE_CHARS,
        description="d" * service.MAX_DESCRIPTION_CHARS,
        notes={"k": "n" * padding},
        tags=[f"#t{i}" for i in range(service.MAX_TAGS - 1)],
        urls={"k": "u" * padding},
    )

    assert len(thing.title) == service.MAX_TITLE_CHARS
    assert len(thing.tags) == service.MAX_TAGS  # the 99 given and #New


def test_mapping_size_counts_bytes_not_characters(session):
    """A note of multi-byte characters is measured by what it costs to store, not by its length."""
    with pytest.raises(FieldTooLarge, match="bytes"):
        create_thing(session, actor=Actor.USER, title="ok", notes={"k": "é" * (service.MAX_MAPPING_BYTES // 2)})


def test_an_oversized_update_is_refused_and_the_thing_is_untouched(session):
    thing = create_thing(session, actor=Actor.USER, title="before")
    before = _journal_count(session)

    with pytest.raises(FieldTooLarge, match="title"):
        update_thing(session, actor=Actor.USER, thing_id=thing.id, title="t" * (service.MAX_TITLE_CHARS + 1))

    session.refresh(thing)
    assert thing.title == "before"
    assert _journal_count(session) == before


def test_an_update_checks_only_the_fields_it_passes(session):
    """A Thing stored before the bounds existed stays updatable through the fields within them."""
    thing = create_thing(session, actor=Actor.USER, title="legacy")
    session.execute(text("UPDATE things SET title = :t WHERE id = :id"), {"t": "x" * 2000, "id": thing.id})
    session.commit()

    updated = update_thing(session, actor=Actor.USER, thing_id=thing.id, tags=["#Kept"])

    assert updated.tags == ["#Kept"]


@pytest.mark.parametrize(
    ("change", "refusal"),
    [({"active": False}, "archived"), ({"tags": ["#Other"]}, "keep that tag"), ({"tags": []}, "keep that tag")],
)
def test_a_heartbeat_cannot_be_archived_or_lose_its_tag(session, change, refusal):
    """#1704: either write would hide a missed scheduled run instead of reporting it."""
    heartbeat = create_thing(session, actor=Actor.CLAUDE_SCHEDULED, title="Resolution pass", tags=[SCHEDULED_TASK_TAG])
    before = _journal_count(session)

    with pytest.raises(ValueError, match=refusal):
        update_thing(session, actor=Actor.CLAUDE_INTERACTIVE, thing_id=heartbeat.id, **change)

    session.refresh(heartbeat)
    assert heartbeat.active is True
    assert heartbeat.tags == [SCHEDULED_TASK_TAG]
    assert _journal_count(session) == before


def test_a_heartbeat_still_takes_its_routine_writes(session):
    heartbeat = create_thing(session, actor=Actor.CLAUDE_SCHEDULED, title="Learning pass", tags=[SCHEDULED_TASK_TAG])
    tomorrow = date(2026, 10, 23)

    updated = update_thing(
        session,
        actor=Actor.CLAUDE_SCHEDULED,
        thing_id=heartbeat.id,
        checkin_date=tomorrow,
        tags=[SCHEDULED_TASK_TAG, "#Kept"],
        active=True,
    )

    assert updated.checkin_date == tomorrow
    assert updated.tags == [SCHEDULED_TASK_TAG, "#Kept"]


@pytest.mark.parametrize("priority", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_priority_is_refused(session, priority):
    with pytest.raises(ValueError, match="finite"):
        create_thing(session, actor=Actor.USER, title="ok", priority=priority)


def test_an_oversized_relationship_context_is_refused(session):
    a = create_thing(session, actor=Actor.USER, title="a")
    b = create_thing(session, actor=Actor.USER, title="b")
    before = _journal_count(session)

    with pytest.raises(FieldTooLarge, match="context"):
        relate(
            session,
            actor=Actor.USER,
            source_thing_id=a.id,
            target_thing_id=b.id,
            relationship_type=RelationshipType.RELATED_TO,
            context="c" * (service.MAX_CONTEXT_CHARS + 1),
        )

    assert _journal_count(session) == before


@pytest.mark.parametrize(
    ("title", "scope", "field"),
    [("t" * (service.MAX_TITLE_CHARS + 1), "planning", "title"), ("ok", "s" * (service.MAX_SCOPE_CHARS + 1), "scope")],
)
def test_an_oversized_preference_leaves_nothing_behind(session, title, scope, field):
    """Refused before the ``#User`` anchor is created, so the refusal writes nothing at all."""
    evidence = create_thing(session, actor=Actor.USER, title="evidence")
    before = _journal_count(session)

    with pytest.raises(FieldTooLarge, match=field):
        service.record_preference(session, actor=Actor.USER, title=title, scope=scope, evidence_ids=[evidence.id])

    assert _journal_count(session) == before
    assert session.get(ThingRecord, USER_ANCHOR_ID) is None
