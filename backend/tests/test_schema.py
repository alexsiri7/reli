"""What the baseline migration actually built, read back from Postgres itself."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from backend.db_models import Actor
from backend.service import create_thing

LEGACY_TABLES = (
    "thing_relationships",
    "chat_sessions",
    "chat_history",
    "users",
    "sweep_findings",
    "sweep_runs",
    "thing_embeddings",
    "connection_suggestions",
    "thing_types",
    "mcp_mutations",
)


def _columns_named(session, column_name):
    return (
        session.execute(
            text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = :name"
            ),
            {"name": column_name},
        )
        .scalars()
        .all()
    )


def _tables(session):
    return set(
        session.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
        .scalars()
        .all()
    )


def test_no_parent_id_column_exists_anywhere(session):
    """#1408 acceptance criterion: hierarchy is a ChildOf relationship, never a column."""
    assert _columns_named(session, "parent_id") == []


def test_no_confidence_column_exists_anywhere(session):
    """The vision forbids confidence floats; the baseline drops the pre-v4 columns that held them."""
    assert _columns_named(session, "confidence") == []


def test_only_the_three_v4_tables_exist(session):
    tables = _tables(session)
    assert {"things", "relationships", "journal"} <= tables
    assert not tables & set(LEGACY_TABLES)


def test_things_tags_has_a_gin_index(session):
    """by_tag depends on it, and jsonb_ops rather than jsonb_path_ops so that ?| is indexed."""
    indexdef = session.execute(
        text("SELECT indexdef FROM pg_indexes WHERE tablename = 'things' AND indexname = 'ix_things_tags'")
    ).scalar_one()
    assert "USING gin" in indexdef
    assert "jsonb_path_ops" not in indexdef


@pytest.mark.parametrize("column", ["title", "checkin_date", "active", "updated_at"])
def test_things_columns_the_queries_filter_on_are_indexed(session, column):
    indexed = session.execute(text("SELECT indexdef FROM pg_indexes WHERE tablename = 'things'")).scalars().all()
    assert any(f"({column})" in definition for definition in indexed), f"{column} is not indexed"


def test_relationship_type_check_rejects_an_unknown_value(session):
    thing = create_thing(session, actor=Actor.USER, title="anchor")
    with pytest.raises(DatabaseError):
        session.execute(
            text(
                "INSERT INTO relationships "
                "(id, source_thing_id, target_thing_id, relationship_type, created_at) "
                "VALUES (:id, :src, :tgt, 'Supersedes', now())"
            ),
            {"id": uuid.uuid4(), "src": thing.id, "tgt": thing.id},
        )
    session.rollback()


def test_journal_rejects_update(session):
    create_thing(session, actor=Actor.USER, title="journalled")
    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(text("UPDATE journal SET actor = 'user'"))
    session.rollback()


def test_journal_rejects_delete(session):
    create_thing(session, actor=Actor.USER, title="journalled")
    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(text("DELETE FROM journal"))
    session.rollback()


def test_journal_rejects_truncate(session):
    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(text("TRUNCATE journal"))
    session.rollback()
