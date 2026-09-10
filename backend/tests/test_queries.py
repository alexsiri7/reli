"""One focused test per indexed query, including the two whose edge direction is easy to invert."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from backend.db_models import Actor, RelationshipType
from backend.queries import blocked, by_tag, children, due_for_checkin, related, stale
from backend.service import create_thing, relate, update_thing

TODAY = date(2026, 9, 10)


def _thing(session, title, **fields):
    return create_thing(session, actor=Actor.USER, title=title, **fields)


def _titles(things):
    return [t.title for t in things]


# --- due_for_checkin -------------------------------------------------------


def test_due_for_checkin_includes_today_and_past_ordered_by_priority(session):
    _thing(session, "yesterday", checkin_date=TODAY - timedelta(days=1), priority=1.0)
    _thing(session, "today", checkin_date=TODAY, priority=5.0)
    _thing(session, "tomorrow", checkin_date=TODAY + timedelta(days=1), priority=9.0)
    _thing(session, "undated", priority=9.0)

    assert _titles(due_for_checkin(session, TODAY)) == ["today", "yesterday"]


def test_due_for_checkin_excludes_inactive(session):
    thing = _thing(session, "archived", checkin_date=TODAY)
    update_thing(session, actor=Actor.USER, thing_id=thing.id, active=False)

    assert due_for_checkin(session, TODAY) == []


# --- stale -----------------------------------------------------------------


def test_stale_returns_oldest_first_and_excludes_recent(session):
    now = datetime.now(UTC)
    old = _thing(session, "old")
    older = _thing(session, "older")
    _thing(session, "fresh")

    # updated_at is set by the service; move these two back behind the threshold.
    session.execute(
        text("UPDATE things SET updated_at = :ts WHERE id = :id"),
        {"ts": now - timedelta(days=30), "id": old.id},
    )
    session.execute(
        text("UPDATE things SET updated_at = :ts WHERE id = :id"),
        {"ts": now - timedelta(days=60), "id": older.id},
    )
    session.commit()

    assert _titles(stale(session, now - timedelta(days=7))) == ["older", "old"]


def test_stale_excludes_inactive(session):
    now = datetime.now(UTC)
    thing = _thing(session, "archived")
    update_thing(session, actor=Actor.USER, thing_id=thing.id, active=False)
    session.execute(
        text("UPDATE things SET updated_at = :ts WHERE id = :id"),
        {"ts": now - timedelta(days=30), "id": thing.id},
    )
    session.commit()

    assert stale(session, now - timedelta(days=7)) == []


# --- by_tag ----------------------------------------------------------------


def test_by_tag_any_matches_either_tag(session):
    _thing(session, "work", tags=["work"])
    _thing(session, "home", tags=["home"])
    _thing(session, "neither", tags=["other"])

    assert sorted(_titles(by_tag(session, ["work", "home"]))) == ["home", "work"]


def test_by_tag_all_requires_every_tag(session):
    _thing(session, "both", tags=["work", "urgent"])
    _thing(session, "one", tags=["work"])

    assert _titles(by_tag(session, ["work", "urgent"], match="all")) == ["both"]


def test_by_tag_with_no_tags_returns_nothing(session):
    _thing(session, "tagged", tags=["work"])

    assert by_tag(session, []) == []
    assert by_tag(session, [], match="all") == []


# --- blocked ---------------------------------------------------------------


def test_blocked_returns_the_source_of_a_blocks_edge(session):
    waiting = _thing(session, "waiting")
    blocker = _thing(session, "blocker")
    relate(
        session,
        actor=Actor.USER,
        source_thing_id=waiting.id,
        target_thing_id=blocker.id,
        relationship_type=RelationshipType.BLOCKS,
    )

    assert _titles(blocked(session)) == ["waiting"]


def test_blocked_drops_the_thing_once_its_blocker_is_archived(session):
    waiting = _thing(session, "waiting")
    blocker = _thing(session, "blocker")
    relate(
        session,
        actor=Actor.USER,
        source_thing_id=waiting.id,
        target_thing_id=blocker.id,
        relationship_type=RelationshipType.BLOCKS,
    )

    update_thing(session, actor=Actor.USER, thing_id=blocker.id, active=False)

    assert blocked(session) == []


# --- related ---------------------------------------------------------------


def test_related_at_depth_one_finds_both_incoming_and_outgoing_edges(session):
    origin = _thing(session, "origin")
    outgoing = _thing(session, "outgoing")
    incoming = _thing(session, "incoming")
    _thing(session, "unconnected")
    relate(
        session,
        actor=Actor.USER,
        source_thing_id=origin.id,
        target_thing_id=outgoing.id,
        relationship_type=RelationshipType.RELATED_TO,
    )
    relate(
        session,
        actor=Actor.USER,
        source_thing_id=incoming.id,
        target_thing_id=origin.id,
        relationship_type=RelationshipType.EVIDENCE_FOR,
    )

    found = related(session, origin.id)

    assert sorted(r.thing.title for r in found) == ["incoming", "outgoing"]
    assert {r.depth for r in found} == {1}


def test_related_at_depth_two_reaches_the_far_side_and_reports_its_depth(session):
    origin = _thing(session, "origin")
    middle = _thing(session, "middle")
    far = _thing(session, "far")
    relate(
        session,
        actor=Actor.USER,
        source_thing_id=origin.id,
        target_thing_id=middle.id,
        relationship_type=RelationshipType.CHILD_OF,
    )
    relate(
        session,
        actor=Actor.USER,
        source_thing_id=middle.id,
        target_thing_id=far.id,
        relationship_type=RelationshipType.CHILD_OF,
    )

    assert _titles([r.thing for r in related(session, origin.id, depth=1)]) == ["middle"]

    by_title = {r.thing.title: r.depth for r in related(session, origin.id, depth=2)}
    assert by_title == {"middle": 1, "far": 2}


def test_related_filters_by_type(session):
    origin = _thing(session, "origin")
    child = _thing(session, "child")
    reference = _thing(session, "reference")
    relate(
        session,
        actor=Actor.USER,
        source_thing_id=origin.id,
        target_thing_id=child.id,
        relationship_type=RelationshipType.CHILD_OF,
    )
    relate(
        session,
        actor=Actor.USER,
        source_thing_id=origin.id,
        target_thing_id=reference.id,
        relationship_type=RelationshipType.REFERENCES,
    )

    found = related(session, origin.id, types=[RelationshipType.CHILD_OF])

    assert _titles([r.thing for r in found]) == ["child"]
    assert found[0].relationship_type == RelationshipType.CHILD_OF


def test_related_terminates_on_a_cycle(session):
    first = _thing(session, "first")
    second = _thing(session, "second")
    relate(
        session,
        actor=Actor.USER,
        source_thing_id=first.id,
        target_thing_id=second.id,
        relationship_type=RelationshipType.RELATED_TO,
    )
    relate(
        session,
        actor=Actor.USER,
        source_thing_id=second.id,
        target_thing_id=first.id,
        relationship_type=RelationshipType.RELATED_TO,
    )

    found = related(session, first.id, depth=5)

    assert _titles([r.thing for r in found]) == ["second"]


def test_related_excludes_the_origin(session):
    origin = _thing(session, "origin")
    other = _thing(session, "other")
    relate(
        session,
        actor=Actor.USER,
        source_thing_id=origin.id,
        target_thing_id=other.id,
        relationship_type=RelationshipType.RELATED_TO,
    )

    assert origin.id not in {r.thing.id for r in related(session, origin.id, depth=3)}


# --- children --------------------------------------------------------------


def test_children_returns_targets_of_child_of_edges(session):
    parent = _thing(session, "parent")
    child = _thing(session, "child")
    relate(
        session,
        actor=Actor.USER,
        source_thing_id=parent.id,
        target_thing_id=child.id,
        relationship_type=RelationshipType.CHILD_OF,
    )

    assert _titles(children(session, parent.id)) == ["child"]
    assert children(session, child.id) == []


def test_children_ignores_other_relationship_types(session):
    parent = _thing(session, "parent")
    other = _thing(session, "other")
    relate(
        session,
        actor=Actor.USER,
        source_thing_id=parent.id,
        target_thing_id=other.id,
        relationship_type=RelationshipType.RELATED_TO,
    )

    assert children(session, parent.id) == []
