"""The one-off collapse that ``v4_unique_evidence_for`` runs before it builds the index (#1536).

The migrated database already carries ``EVIDENCE_FOR_UNIQUE_INDEX``, so a duplicate pair cannot be
built on the fixture session — which is the point. The collapse is therefore proven by walking a
fresh database through the revision itself, with the no-op case on the migrated database beside it.
The journal is append-only, so every journal assertion is a delta.
"""

import os

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlmodel import Session

from backend.db_models import EVIDENCE_FOR_UNIQUE_INDEX, Actor, Operation, RelationshipType
from backend.service import collapse_duplicate_evidence, create_thing, relate


def _journal_count(session):
    return session.execute(text("SELECT count(*) FROM journal")).scalar_one()


def _entries_since(session, count_before):
    return session.execute(
        text("SELECT actor, operation, entity_id, before, after FROM journal ORDER BY id OFFSET :n"),
        {"n": count_before},
    ).all()


def _edge_ids(session, source_id, target_id, relationship_type):
    return (
        session.execute(
            text(
                "SELECT id FROM relationships WHERE source_thing_id = :src AND target_thing_id = :tgt "
                "AND relationship_type = :type ORDER BY created_at, id"
            ),
            {"src": source_id, "tgt": target_id, "type": relationship_type.value},
        )
        .scalars()
        .all()
    )


def _relate(session, source, target, relationship_type, context=None):
    return relate(
        session,
        actor=Actor.CLAUDE_INTERACTIVE,
        source_thing_id=source.id,
        target_thing_id=target.id,
        relationship_type=relationship_type,
        context=context,
    ).id


def test_it_is_a_no_op_on_a_graph_with_no_duplicates(session):
    preference = create_thing(session, actor=Actor.CLAUDE_INTERACTIVE, title="preference")
    for title in ("one", "two"):
        evidence = create_thing(session, actor=Actor.CLAUDE_INTERACTIVE, title=title)
        _relate(session, evidence, preference, RelationshipType.EVIDENCE_FOR)
    count_before = _journal_count(session)

    assert collapse_duplicate_evidence(session) == 0
    assert _entries_since(session, count_before) == []


def test_the_revision_collapses_duplicates_already_in_the_table(fresh_database):
    """Before the index, ``relate`` lands a second ``EvidenceFor`` edge for a pair — which also shows
    the refusal is the database's and not a lookup's. The revision keeps the earliest and journals the rest."""
    from backend.db_engine import get_engine

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config = AlembicConfig(os.path.join(repo_root, "alembic.ini"))
    alembic_command.upgrade(config, "v4_hashed_credential_keys")

    with Session(get_engine()) as session:
        preference = create_thing(session, actor=Actor.CLAUDE_INTERACTIVE, title="preference")
        doubled = create_thing(session, actor=Actor.CLAUDE_INTERACTIVE, title="doubled evidence")
        single = create_thing(session, actor=Actor.CLAUDE_INTERACTIVE, title="single evidence")
        cited = create_thing(session, actor=Actor.CLAUDE_INTERACTIVE, title="cited")
        kept = _relate(session, doubled, preference, RelationshipType.EVIDENCE_FOR, context="first")
        dropped = _relate(session, doubled, preference, RelationshipType.EVIDENCE_FOR, context="again")
        lone = _relate(session, single, preference, RelationshipType.EVIDENCE_FOR)
        references = {
            _relate(session, cited, preference, RelationshipType.REFERENCES, context=context)
            for context in ("cites the figures", "quotes the conclusion")
        }
        preference_id, doubled_id, single_id, cited_id = preference.id, doubled.id, single.id, cited.id
        count_before = _journal_count(session)

    alembic_command.upgrade(config, "head")

    with Session(get_engine()) as session:
        assert _edge_ids(session, doubled_id, preference_id, RelationshipType.EVIDENCE_FOR) == [kept]
        assert _edge_ids(session, single_id, preference_id, RelationshipType.EVIDENCE_FOR) == [lone]
        assert set(_edge_ids(session, cited_id, preference_id, RelationshipType.REFERENCES)) == references

        entries = _entries_since(session, count_before)
        assert [(entry.actor, entry.operation, entry.entity_id) for entry in entries] == [
            (Actor.CLAUDE_SCHEDULED.value, Operation.UNRELATE.value, dropped)
        ]
        assert entries[0].before["id"] == str(dropped)
        assert entries[0].before["context"] == "again"
        assert entries[0].after is None

        indexed = (
            session.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'relationships'")).scalars().all()
        )
        assert EVIDENCE_FOR_UNIQUE_INDEX in indexed
