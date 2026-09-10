"""The user model: the #User anchor, preferences as Things, and the evidence behind each one.

It spans the write path and the read path, so it gets one file rather than being split between
test_service.py and test_queries.py. The MCP surface over it stays in test_mcp_tools.py.
"""

import json
import uuid

import pytest
from sqlalchemy import text

from backend.db_models import (
    OBSERVATION_TAG,
    PREFERENCE_TAG,
    REJECTED_TAG,
    USER_ANCHOR_ID,
    USER_TAG,
    Actor,
    RelationshipType,
)
from backend.queries import evidence_for, user_model
from backend.service import (
    ThingNotFound,
    add_preference_evidence,
    create_thing,
    get_or_create_user_anchor,
    record_preference,
    reject_preference,
    relate,
)


def _journal_count(session):
    return session.execute(text("SELECT count(*) FROM journal")).scalar_one()


def _thing(session, title, **fields):
    return create_thing(session, actor=Actor.CLAUDE_INTERACTIVE, title=title, **fields)


def _edges(session, thing_id, relationship_type):
    return session.execute(
        text(
            "SELECT source_thing_id, target_thing_id FROM relationships "
            "WHERE target_thing_id = :id AND relationship_type = :type"
        ),
        {"id": thing_id, "type": relationship_type.value},
    ).all()


#: Every scope ``str.strip()`` treats as blank. SQL's single-argument ``btrim`` trims only the ASCII
#: space, so the read path has to judge blankness the way the write path does.
blank_scopes = pytest.mark.parametrize(
    "scope",
    [" ", "\t", "\n", "\r", "\v", "\f", "\u00a0", " \t\n"],
    ids=["space", "tab", "newline", "return", "vtab", "formfeed", "nbsp", "mixed"],
)


def _preference(session, title="Prefers deep work 9-11am", scope="scheduling", evidence=1):
    evidence_ids = [_thing(session, f"{title} evidence {n}").id for n in range(evidence)]
    return record_preference(
        session,
        actor=Actor.CLAUDE_INTERACTIVE,
        title=title,
        scope=scope,
        evidence_ids=evidence_ids,
    )


# --- The anchor ------------------------------------------------------------


def test_the_anchor_is_created_once_and_reused(session):
    first = get_or_create_user_anchor(session, actor=Actor.CLAUDE_INTERACTIVE)
    before = _journal_count(session)
    second = get_or_create_user_anchor(session, actor=Actor.CLAUDE_SCHEDULED)

    assert first.id == USER_ANCHOR_ID
    assert second.id == first.id
    assert USER_TAG in first.tags
    assert _journal_count(session) == before


# --- record_preference -----------------------------------------------------


def test_record_preference_anchors_the_preference_and_links_every_piece_of_evidence(session):
    one = _thing(session, "declined a 9am meeting")
    two = _thing(session, "moved standup to noon")

    preference = record_preference(
        session,
        actor=Actor.CLAUDE_INTERACTIVE,
        title="Prefers deep work 9-11am",
        scope="scheduling",
        evidence_ids=[one.id, two.id],
    )

    assert preference.tags == [PREFERENCE_TAG]
    assert preference.notes == {"scope": "scheduling"}
    assert _edges(session, preference.id, RelationshipType.RELATED_TO) == [(USER_ANCHOR_ID, preference.id)]
    assert {source for source, _ in _edges(session, preference.id, RelationshipType.EVIDENCE_FOR)} == {one.id, two.id}


def test_record_preference_preserves_the_scopes_case_and_strips_only_whitespace(session):
    evidence = _thing(session, "declined a 9am meeting")
    preference = record_preference(
        session,
        actor=Actor.CLAUDE_INTERACTIVE,
        title="Prefers deep work 9-11am",
        scope="  Scheduling  ",
        evidence_ids=[evidence.id],
    )

    assert preference.notes["scope"] == "Scheduling"
    assert [found.scope for found in user_model(session, scope="scheduling")] == ["Scheduling"]


def test_record_preference_refuses_an_empty_evidence_list(session):
    before = _journal_count(session)

    with pytest.raises(ValueError):
        record_preference(
            session,
            actor=Actor.CLAUDE_INTERACTIVE,
            title="Prefers deep work",
            scope="scheduling",
            evidence_ids=[],
        )

    assert user_model(session) == []
    assert _journal_count(session) == before


def test_record_preference_refuses_unknown_evidence(session):
    known = _thing(session, "declined a 9am meeting")

    with pytest.raises(ThingNotFound):
        record_preference(
            session,
            actor=Actor.CLAUDE_INTERACTIVE,
            title="Prefers deep work",
            scope="scheduling",
            evidence_ids=[known.id, uuid.uuid4()],
        )

    assert user_model(session) == []


@blank_scopes
def test_record_preference_refuses_a_blank_scope(session, scope):
    evidence = _thing(session, "declined a 9am meeting")

    with pytest.raises(ValueError):
        record_preference(
            session,
            actor=Actor.CLAUDE_INTERACTIVE,
            title="Prefers deep work",
            scope=scope,
            evidence_ids=[evidence.id],
        )


def test_record_preference_counts_repeated_evidence_once(session):
    evidence = _thing(session, "declined a 9am meeting")

    preference = record_preference(
        session,
        actor=Actor.CLAUDE_INTERACTIVE,
        title="Prefers deep work",
        scope="scheduling",
        evidence_ids=[evidence.id, evidence.id],
    )

    assert len(evidence_for(session, preference.id)) == 1


# --- add_preference_evidence -----------------------------------------------


def test_add_preference_evidence_raises_the_strength_by_one(session):
    preference = _preference(session)
    more = _thing(session, "blocked out Tuesday morning")

    add_preference_evidence(
        session,
        actor=Actor.CLAUDE_SCHEDULED,
        preference_id=preference.id,
        evidence_id=more.id,
    )

    assert len(evidence_for(session, preference.id)) == 2


def test_add_preference_evidence_is_idempotent(session):
    preference = _preference(session)
    more = _thing(session, "blocked out Tuesday morning")
    add_preference_evidence(session, actor=Actor.CLAUDE_SCHEDULED, preference_id=preference.id, evidence_id=more.id)
    before = _journal_count(session)

    again = add_preference_evidence(
        session, actor=Actor.CLAUDE_SCHEDULED, preference_id=preference.id, evidence_id=more.id
    )

    assert again.id == preference.id
    assert len(evidence_for(session, preference.id)) == 2
    assert _journal_count(session) == before


def test_add_preference_evidence_refuses_a_thing_that_is_not_a_preference(session):
    ordinary = _thing(session, "an ordinary Thing")
    evidence = _thing(session, "some evidence")

    with pytest.raises(ValueError):
        add_preference_evidence(
            session, actor=Actor.CLAUDE_SCHEDULED, preference_id=ordinary.id, evidence_id=evidence.id
        )


def test_add_preference_evidence_refuses_the_preference_as_its_own_evidence(session):
    preference = _preference(session)

    with pytest.raises(ValueError):
        add_preference_evidence(
            session, actor=Actor.CLAUDE_SCHEDULED, preference_id=preference.id, evidence_id=preference.id
        )


# --- reject_preference -----------------------------------------------------


def test_reject_preference_tags_it_without_archiving_it(session):
    preference = _preference(session)
    before = _journal_count(session)

    rejected = reject_preference(session, actor=Actor.CLAUDE_INTERACTIVE, preference_id=preference.id)

    assert rejected.tags == [PREFERENCE_TAG, REJECTED_TAG]
    assert rejected.active is True
    assert _journal_count(session) == before + 1


def test_reject_preference_is_idempotent(session):
    preference = _preference(session)
    reject_preference(session, actor=Actor.CLAUDE_INTERACTIVE, preference_id=preference.id)
    before = _journal_count(session)

    reject_preference(session, actor=Actor.CLAUDE_INTERACTIVE, preference_id=preference.id)

    assert _journal_count(session) == before


def test_reject_preference_refuses_a_thing_that_is_not_a_preference(session):
    ordinary = _thing(session, "an ordinary Thing")

    with pytest.raises(ValueError):
        reject_preference(session, actor=Actor.CLAUDE_INTERACTIVE, preference_id=ordinary.id)


# --- user_model ------------------------------------------------------------


def test_user_model_filters_by_scope(session):
    _preference(session, title="Prefers deep work 9-11am", scope="scheduling")
    _preference(session, title="Names projects after their outcome", scope="naming")

    assert [p.thing.title for p in user_model(session, scope="scheduling")] == ["Prefers deep work 9-11am"]


def test_user_model_matches_a_scope_whatever_its_case(session):
    _preference(session, title="Prefers deep work 9-11am", scope="Scheduling")

    assert [p.thing.title for p in user_model(session, scope="scheduling")] == ["Prefers deep work 9-11am"]


def test_user_model_excludes_a_rejected_preference_by_default_and_returns_it_when_asked(session):
    kept = _preference(session, title="Prefers deep work 9-11am", scope="scheduling")
    dropped = _preference(session, title="Prefers 7am starts", scope="scheduling")
    reject_preference(session, actor=Actor.USER, preference_id=dropped.id)

    assert [p.thing.id for p in user_model(session)] == [kept.id]
    with_rejected = user_model(session, include_rejected=True)
    assert {p.thing.id for p in with_rejected} == {kept.id, dropped.id}
    assert [p.rejected for p in with_rejected if p.thing.id == dropped.id] == [True]


def test_user_model_returns_each_preference_with_its_evidence_in_the_order_it_was_attached(session):
    first = _thing(session, "declined a 9am meeting")
    second = _thing(session, "moved standup to noon")
    preference = record_preference(
        session,
        actor=Actor.CLAUDE_INTERACTIVE,
        title="Prefers deep work 9-11am",
        scope="scheduling",
        evidence_ids=[first.id, second.id],
    )
    third = _thing(session, "blocked out Tuesday morning")
    add_preference_evidence(session, actor=Actor.CLAUDE_SCHEDULED, preference_id=preference.id, evidence_id=third.id)

    (found,) = user_model(session, scope="scheduling")

    assert found.evidence_count == 3
    assert [thing.id for thing in found.evidence] == [first.id, second.id, third.id]
    assert found.scope == "scheduling"


def test_user_model_is_empty_before_any_preference_is_recorded(session):
    assert user_model(session) == []
    assert session.execute(text("SELECT count(*) FROM things")).scalar_one() == 0


def test_user_model_ignores_a_preference_thing_not_linked_to_the_anchor(session):
    _thing(session, "not anchored", tags=[PREFERENCE_TAG], notes={"scope": "scheduling"})

    assert user_model(session) == []


def test_user_model_ignores_an_anchored_preference_thing_with_no_evidence(session):
    """``create_thing`` and ``relate`` are public, so the shape is expressible without the evidence."""
    get_or_create_user_anchor(session, actor=Actor.CLAUDE_SCHEDULED)
    unbacked = _thing(session, "invented out of nowhere", tags=[PREFERENCE_TAG], notes={"scope": "scheduling"})
    relate(
        session,
        actor=Actor.CLAUDE_SCHEDULED,
        source_thing_id=USER_ANCHOR_ID,
        target_thing_id=unbacked.id,
        relationship_type=RelationshipType.RELATED_TO,
    )

    assert user_model(session) == []
    assert user_model(session, include_rejected=True) == []


def test_user_model_ignores_an_anchored_preference_thing_with_no_scope(session):
    """The same door: a preference nobody can scope is not loadable, so the read leaves it out."""
    get_or_create_user_anchor(session, actor=Actor.CLAUDE_SCHEDULED)
    scopeless = _thing(session, "applies to nothing in particular", tags=[PREFERENCE_TAG])
    observation = _thing(session, "declined a 9am meeting")
    relate(
        session,
        actor=Actor.CLAUDE_SCHEDULED,
        source_thing_id=USER_ANCHOR_ID,
        target_thing_id=scopeless.id,
        relationship_type=RelationshipType.RELATED_TO,
    )
    relate(
        session,
        actor=Actor.CLAUDE_SCHEDULED,
        source_thing_id=observation.id,
        target_thing_id=scopeless.id,
        relationship_type=RelationshipType.EVIDENCE_FOR,
    )

    assert user_model(session) == []


@blank_scopes
def test_user_model_ignores_an_anchored_preference_thing_whose_scope_is_only_whitespace(session, scope):
    """The read rejects every blank the write path rejects, not only the ones ``btrim`` would catch."""
    get_or_create_user_anchor(session, actor=Actor.CLAUDE_SCHEDULED)
    scopeless = _thing(session, "scoped to whitespace", tags=[PREFERENCE_TAG], notes={"scope": scope})
    observation = _thing(session, "declined a 9am meeting")
    relate(
        session,
        actor=Actor.CLAUDE_SCHEDULED,
        source_thing_id=USER_ANCHOR_ID,
        target_thing_id=scopeless.id,
        relationship_type=RelationshipType.RELATED_TO,
    )
    relate(
        session,
        actor=Actor.CLAUDE_SCHEDULED,
        source_thing_id=observation.id,
        target_thing_id=scopeless.id,
        relationship_type=RelationshipType.EVIDENCE_FOR,
    )

    assert user_model(session) == []
    assert user_model(session, include_rejected=True) == []


def test_user_model_returns_a_preference_once_however_many_anchor_edges_it_has(session):
    """``relate`` is public, so a second anchor edge is expressible; it must not double the model."""
    preference = _preference(session)
    relate(
        session,
        actor=Actor.CLAUDE_SCHEDULED,
        source_thing_id=USER_ANCHOR_ID,
        target_thing_id=preference.id,
        relationship_type=RelationshipType.RELATED_TO,
    )

    assert [found.thing.id for found in user_model(session)] == [preference.id]


def test_a_preference_holds_its_evidence_and_no_confidence(session):
    preference = _preference(session, evidence=2)

    (found,) = user_model(session)

    assert set(preference.notes) == {"scope"}
    assert found.evidence_count == 2
    assert "confidence" not in json.dumps(found.thing.model_dump(mode="json"))


def test_a_journal_entry_is_evidence_once_wrapped_in_an_observation_thing(session):
    subject = _thing(session, "standup")
    entry_id = session.execute(
        text("SELECT id FROM journal WHERE entity_id = :id ORDER BY id DESC LIMIT 1"),
        {"id": subject.id},
    ).scalar_one()
    observation = _thing(
        session,
        "moved standup to noon",
        tags=[OBSERVATION_TAG],
        notes={"journal_entry_id": str(entry_id)},
    )

    preference = record_preference(
        session,
        actor=Actor.CLAUDE_SCHEDULED,
        title="Prefers deep work 9-11am",
        scope="scheduling",
        evidence_ids=[observation.id],
    )

    assert [thing.id for thing in evidence_for(session, preference.id)] == [observation.id]
