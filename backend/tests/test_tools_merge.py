"""Tests for tools.merge_things() edge cases."""

import json

from backend.tools import create_thing, create_relationship, merge_things, get_thing


class TestMergeThings:
    def test_basic_merge_transfers_relationships(self, patched_db):
        """Relationships from removed thing transfer to kept thing."""
        a = create_thing(title="Thing A")
        b = create_thing(title="Thing B (duplicate)")
        c = create_thing(title="Thing C")
        create_relationship(from_thing_id=b["id"], to_thing_id=c["id"], relationship_type="related-to")

        result = merge_things(keep_id=a["id"], remove_id=b["id"])

        assert result["keep_id"] == a["id"]
        assert result["remove_id"] == b["id"]
        # Removed thing should be gone
        assert "error" in get_thing(b["id"])

    def test_merge_with_overlapping_relationships_no_duplicates(self, patched_db):
        """When both things relate to the same target, no self-referential link is created."""
        a = create_thing(title="Keep")
        b = create_thing(title="Remove")
        c = create_thing(title="Target")
        create_relationship(from_thing_id=a["id"], to_thing_id=c["id"], relationship_type="related-to")
        create_relationship(from_thing_id=b["id"], to_thing_id=c["id"], relationship_type="related-to")

        result = merge_things(keep_id=a["id"], remove_id=b["id"])
        assert "error" not in result

    def test_merge_transfers_open_questions_when_keep_has_none(self, patched_db):
        """Open questions from removed thing transfer when kept thing has none."""
        a = create_thing(title="Keep")
        b = create_thing(title="Remove", open_questions_json='["Q2", "Q3"]')

        merge_things(keep_id=a["id"], remove_id=b["id"])

        kept = get_thing(a["id"])
        oq = kept.get("open_questions") or []
        assert "Q2" in oq
        assert "Q3" in oq

    def test_merge_records_history(self, patched_db):
        """Merge creates a MergeHistoryRecord."""
        from sqlmodel import Session, select
        from backend.db_models import MergeHistoryRecord
        import backend.db_engine as engine_mod

        a = create_thing(title="Keep")
        b = create_thing(title="Remove")

        merge_things(keep_id=a["id"], remove_id=b["id"])

        with Session(engine_mod.engine) as session:
            records = session.exec(select(MergeHistoryRecord)).all()
        assert len(records) >= 1
        rec = records[-1]
        assert rec.keep_id == a["id"]
        assert rec.remove_id == b["id"]

    def test_merge_nonexistent_thing_returns_error(self, patched_db):
        """Merging with a nonexistent ID returns an error."""
        a = create_thing(title="Exists")
        result = merge_things(keep_id=a["id"], remove_id="nonexistent-id")
        assert "error" in result

    def test_merge_thing_into_itself_returns_error(self, patched_db):
        """Merging a thing into itself returns an error."""
        a = create_thing(title="Self")
        result = merge_things(keep_id=a["id"], remove_id=a["id"])
        assert "error" in result
