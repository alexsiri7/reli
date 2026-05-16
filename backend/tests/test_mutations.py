"""Tests for MCP mutation journal logging, querying, and suspicious pattern detection."""

from datetime import datetime, timezone

from sqlmodel import Session, select

import backend.db_engine as engine_mod
from backend.db_models import McpMutationRecord
from backend.tools import (
    create_relationship,
    create_thing,
    delete_relationship,
    delete_thing,
    get_mutations,
    merge_things,
    update_thing,
)

# ---------------------------------------------------------------------------
# _log_mutation (via write operations)
# ---------------------------------------------------------------------------


class TestMutationLogging:
    def test_create_thing_logs_mutation(self, patched_db):
        result = create_thing(title="Test")
        with Session(engine_mod.engine) as session:
            records = session.exec(
                select(McpMutationRecord).where(McpMutationRecord.operation == "create_thing")
            ).all()
        assert len(records) == 1
        assert records[0].thing_id == result["id"]
        assert records[0].before_snapshot is None
        assert records[0].after_snapshot is not None
        assert records[0].after_snapshot["title"] == "Test"

    def test_update_thing_logs_before_and_after(self, patched_db):
        thing = create_thing(title="Original")
        update_thing(thing_id=thing["id"], title="Updated")
        with Session(engine_mod.engine) as session:
            records = session.exec(
                select(McpMutationRecord).where(McpMutationRecord.operation == "update_thing")
            ).all()
        assert len(records) == 1
        assert records[0].before_snapshot["title"] == "Original"
        assert records[0].after_snapshot["title"] == "Updated"

    def test_delete_thing_logs_before_snapshot(self, patched_db):
        thing = create_thing(title="Doomed")
        delete_thing(thing["id"])
        with Session(engine_mod.engine) as session:
            records = session.exec(
                select(McpMutationRecord).where(McpMutationRecord.operation == "delete_thing")
            ).all()
        assert len(records) == 1
        assert records[0].before_snapshot["title"] == "Doomed"
        assert records[0].after_snapshot is None

    def test_merge_logs_two_mutations(self, patched_db):
        a = create_thing(title="Keep")
        b = create_thing(title="Remove")
        merge_things(keep_id=a["id"], remove_id=b["id"])
        with Session(engine_mod.engine) as session:
            records = session.exec(
                select(McpMutationRecord).where(
                    McpMutationRecord.operation.in_(["merge_things_delete", "merge_things_update"])  # type: ignore[union-attr]
                )
            ).all()
        assert len(records) == 2
        ops = {r.operation for r in records}
        assert ops == {"merge_things_delete", "merge_things_update"}

    def test_create_relationship_logs_mutation(self, patched_db):
        a = create_thing(title="From")
        b = create_thing(title="To")
        create_relationship(from_thing_id=a["id"], to_thing_id=b["id"], relationship_type="related-to")
        with Session(engine_mod.engine) as session:
            records = session.exec(
                select(McpMutationRecord).where(McpMutationRecord.operation == "create_relationship")
            ).all()
        assert len(records) == 1
        assert records[0].after_snapshot["from_thing_id"] == a["id"]

    def test_delete_relationship_logs_mutation(self, patched_db):
        a = create_thing(title="From")
        b = create_thing(title="To")
        rel = create_relationship(from_thing_id=a["id"], to_thing_id=b["id"], relationship_type="related-to")
        delete_relationship(rel["id"])
        with Session(engine_mod.engine) as session:
            records = session.exec(
                select(McpMutationRecord).where(McpMutationRecord.operation == "delete_relationship")
            ).all()
        assert len(records) == 1
        assert records[0].thing_id == a["id"]
        assert records[0].before_snapshot is not None
        assert records[0].after_snapshot is None


# ---------------------------------------------------------------------------
# get_mutations
# ---------------------------------------------------------------------------


class TestGetMutations:
    def test_returns_mutations_newest_first(self, patched_db):
        create_thing(title="First")
        create_thing(title="Second")
        results = get_mutations()
        assert len(results) >= 2
        # Newest first — Second was created after First
        titles = [r["after_snapshot"]["title"] for r in results if r.get("after_snapshot")]
        assert titles[0] == "Second"

    def test_filters_by_thing_id(self, patched_db):
        a = create_thing(title="Target")
        create_thing(title="Other")
        results = get_mutations(thing_id=a["id"])
        assert all(r["thing_id"] == a["id"] for r in results)

    def test_respects_limit(self, patched_db):
        for i in range(5):
            create_thing(title=f"Thing {i}")
        results = get_mutations(limit=2)
        assert len(results) == 2

    def test_empty_journal_returns_empty_list(self, patched_db):
        results = get_mutations()
        assert results == []


# ---------------------------------------------------------------------------
# find_suspicious_mutations
# ---------------------------------------------------------------------------


class TestFindSuspiciousMutations:
    def test_bulk_delete_detected(self, patched_db):
        from backend.sweep import find_suspicious_mutations

        with Session(engine_mod.engine) as session:
            for i in range(5):
                session.add(
                    McpMutationRecord(
                        operation="delete_thing",
                        thing_id=f"t-{i}",
                        occurred_at=datetime.now(timezone.utc),
                    )
                )
            session.commit()
            candidates = find_suspicious_mutations(session)
        assert len(candidates) == 1
        assert candidates[0].finding_type == "suspicious_bulk_delete"

    def test_below_threshold_no_alert(self, patched_db):
        from backend.sweep import find_suspicious_mutations

        with Session(engine_mod.engine) as session:
            for i in range(4):
                session.add(
                    McpMutationRecord(
                        operation="delete_thing",
                        thing_id=f"t-{i}",
                        occurred_at=datetime.now(timezone.utc),
                    )
                )
            session.commit()
            candidates = find_suspicious_mutations(session)
        assert len(candidates) == 0

    def test_mass_field_removal_detected(self, patched_db):
        from backend.sweep import find_suspicious_mutations

        before = {f"field_{i}": f"value_{i}" for i in range(15)}
        after = {f"field_{i}": f"value_{i}" for i in range(3)}
        with Session(engine_mod.engine) as session:
            session.add(
                McpMutationRecord(
                    operation="update_thing",
                    thing_id="t-1",
                    before_snapshot=before,
                    after_snapshot=after,
                    occurred_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            candidates = find_suspicious_mutations(session)
        assert len(candidates) == 1
        assert candidates[0].finding_type == "suspicious_mass_field_removal"

    def test_field_removal_below_threshold(self, patched_db):
        from backend.sweep import find_suspicious_mutations

        before = {f"field_{i}": f"value_{i}" for i in range(12)}
        after = {f"field_{i}": f"value_{i}" for i in range(3)}  # 9 removed, below 10
        with Session(engine_mod.engine) as session:
            session.add(
                McpMutationRecord(
                    operation="update_thing",
                    thing_id="t-1",
                    before_snapshot=before,
                    after_snapshot=after,
                    occurred_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            candidates = find_suspicious_mutations(session)
        assert len(candidates) == 0
