"""Tests for the sweep reasoning agent."""

import json
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from backend.database import db
from backend.sweep_agent import (
    _load_full_graph,
    _make_sweep_tools,
    run_sweep_agent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_thing(conn, thing_id: str, title: str, **kwargs) -> None:
    now = kwargs.pop("updated_at", date.today().isoformat())
    conn.execute(
        """INSERT INTO things
           (id, title, type_hint, parent_id, checkin_date, active, surface,
            data, open_questions, created_at, updated_at, user_id)
           VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
        (
            thing_id,
            title,
            kwargs.get("type_hint"),
            kwargs.get("parent_id"),
            kwargs.get("checkin_date"),
            int(kwargs.get("active", True)),
            json.dumps(kwargs.get("data")) if kwargs.get("data") else None,
            json.dumps(kwargs.get("open_questions")) if kwargs.get("open_questions") else None,
            now,
            now,
            kwargs.get("user_id"),
        ),
    )


def _insert_relationship(conn, rel_id, from_id, to_id, rel_type="related-to"):
    conn.execute(
        """INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type)
           VALUES (?, ?, ?, ?)""",
        (rel_id, from_id, to_id, rel_type),
    )


def _insert_user(conn, user_id: str, email: str = "test@example.com"):
    conn.execute(
        """INSERT INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)""",
        (user_id, email, f"google-{user_id}", "Test User"),
    )


# ---------------------------------------------------------------------------
# Tool tests
# ---------------------------------------------------------------------------


class TestSweepTools:
    def test_create_thing(self, patched_db):
        with patch("backend.sweep_agent.upsert_thing"):
            tools, applied = _make_sweep_tools("user1")
            create_fn = tools[0]  # create_thing

            result = create_fn(title="New Task", type_hint="task", priority=2)

        assert "id" in result
        assert result["title"] == "New Task"
        assert len(applied["created"]) == 1

    def test_create_thing_dedup_returns_existing(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "Existing Task", user_id="user1")

        with patch("backend.sweep_agent.upsert_thing"):
            tools, applied = _make_sweep_tools("user1")
            create_fn = tools[0]

            result = create_fn(title="Existing Task")

        assert result["status"] == "already_exists"
        assert result["id"] == "t1"
        assert len(applied["created"]) == 0

    def test_update_thing(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "Old Title", user_id="user1")

        with patch("backend.sweep_agent.upsert_thing"):
            tools, applied = _make_sweep_tools("user1")
            update_fn = tools[1]  # update_thing

            result = update_fn(thing_id="t1", title="New Title")

        assert result["title"] == "New Title"
        assert len(applied["updated"]) == 1

    def test_create_relationship(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "Thing A", user_id="user1")
            _insert_thing(conn, "t2", "Thing B", user_id="user1")

        tools, applied = _make_sweep_tools("user1")
        rel_fn = tools[2]  # create_relationship

        result = rel_fn(from_thing_id="t1", to_thing_id="t2", relationship_type="related-to")

        assert "id" in result
        assert result["relationship_type"] == "related-to"
        assert len(applied["relationships_created"]) == 1

    def test_create_finding(self, patched_db):
        tools, applied = _make_sweep_tools("user1")
        finding_fn = tools[3]  # create_finding

        result = finding_fn(
            message="You might want to review your stale tasks.",
            priority=2,
            expires_in_days=7,
        )

        assert "id" in result
        assert result["finding_type"] == "llm_insight"
        assert result["message"] == "You might want to review your stale tasks."
        assert len(applied["findings_created"]) == 1

        # Verify persisted
        with db() as conn:
            rows = conn.execute("SELECT * FROM sweep_findings").fetchall()
        assert len(rows) == 1
        assert rows[0]["message"] == "You might want to review your stale tasks."

    def test_create_finding_validates_thing_id(self, patched_db):
        tools, applied = _make_sweep_tools("user1")
        finding_fn = tools[3]

        result = finding_fn(
            message="About a nonexistent thing",
            thing_id="nonexistent-id",
        )

        assert result["thing_id"] is None  # invalid ID nulled

    def test_no_delete_tool(self, patched_db):
        """Verify sweep tools do NOT include delete_thing."""
        tools, _ = _make_sweep_tools("user1")
        tool_names = [t.__name__ for t in tools]
        assert "delete_thing" not in tool_names

    def test_no_merge_tool(self, patched_db):
        """Verify sweep tools do NOT include merge_things."""
        tools, _ = _make_sweep_tools("user1")
        tool_names = [t.__name__ for t in tools]
        assert "merge_things" not in tool_names

    def test_has_expected_tools(self, patched_db):
        tools, _ = _make_sweep_tools("user1")
        tool_names = [t.__name__ for t in tools]
        assert tool_names == ["create_thing", "update_thing", "create_relationship", "create_finding"]


# ---------------------------------------------------------------------------
# Graph loading
# ---------------------------------------------------------------------------


class TestLoadFullGraph:
    def test_loads_active_things(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "Active", user_id="u1")
            _insert_thing(conn, "t2", "Inactive", active=False, user_id="u1")

        things, rels = _load_full_graph("u1")

        assert len(things) == 1
        assert things[0]["id"] == "t1"
        assert len(rels) == 0

    def test_loads_relationships(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "A", user_id="u1")
            _insert_thing(conn, "t2", "B", user_id="u1")
            _insert_relationship(conn, "r1", "t1", "t2", "related-to")

        things, rels = _load_full_graph("u1")

        assert len(things) == 2
        assert len(rels) == 1
        assert rels[0]["relationship_type"] == "related-to"

    def test_empty_graph(self, patched_db):
        things, rels = _load_full_graph("u1")
        assert things == []
        assert rels == []


# ---------------------------------------------------------------------------
# Full agent run
# ---------------------------------------------------------------------------


class TestRunSweepAgent:
    @pytest.mark.asyncio
    async def test_empty_graph_skips_agent(self, patched_db):
        result = await run_sweep_agent(user_id="u1")

        assert result["thing_count"] == 0
        assert result["reasoning_summary"] == "No active Things to analyze."
        assert result["applied_changes"]["created"] == []

    @pytest.mark.asyncio
    async def test_runs_agent_with_things(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "t1", "Buy groceries", type_hint="task", user_id="u1")
            _insert_thing(conn, "t2", "Plan vacation", type_hint="project", user_id="u1")

        agent_response = json.dumps({
            "reasoning_summary": "Analyzed 2 Things. Added open questions to vacation project.",
            "findings_count": 0,
            "changes_count": 1,
        })

        with patch(
            "backend.sweep_agent._run_agent_for_text",
            new_callable=AsyncMock,
            return_value=agent_response,
        ):
            result = await run_sweep_agent(user_id="u1")

        assert result["thing_count"] == 2
        assert result["relationship_count"] == 0
        assert result["reasoning_summary"] == "Analyzed 2 Things. Added open questions to vacation project."


# ---------------------------------------------------------------------------
# Sweep runs logging
# ---------------------------------------------------------------------------


class TestSweepRunsLogging:
    def test_sweep_runs_table_exists(self, patched_db):
        with db() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sweep_runs'").fetchall()
        assert len(rows) == 1

    def test_log_sweep_start_and_complete(self, patched_db):
        from backend.sweep_scheduler import _log_sweep_complete, _log_sweep_start

        run_id = _log_sweep_start("u1")

        with db() as conn:
            row = conn.execute("SELECT * FROM sweep_runs WHERE id = ?", (run_id,)).fetchone()
        assert row is not None
        assert row["status"] == "running"
        assert row["user_id"] == "u1"

        _log_sweep_complete(
            run_id,
            candidates_found=5,
            findings_created=2,
            things_created=1,
            things_updated=3,
        )

        with db() as conn:
            row = conn.execute("SELECT * FROM sweep_runs WHERE id = ?", (run_id,)).fetchone()
        assert row["status"] == "completed"
        assert row["candidates_found"] == 5
        assert row["findings_created"] == 2
        assert row["things_created"] == 1
        assert row["things_updated"] == 3
        assert row["completed_at"] is not None

    def test_log_sweep_failed(self, patched_db):
        from backend.sweep_scheduler import _log_sweep_complete, _log_sweep_start

        run_id = _log_sweep_start("u1")
        _log_sweep_complete(run_id, status="failed", error="test error")

        with db() as conn:
            row = conn.execute("SELECT * FROM sweep_runs WHERE id = ?", (run_id,)).fetchone()
        assert row["status"] == "failed"
        assert row["error"] == "test error"
