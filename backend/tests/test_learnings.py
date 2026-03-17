"""Tests for FR-102: Learnings as Things — sweep generation and API endpoints."""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.database import db
from backend.sweep import (
    _fetch_existing_learnings,
    _fetch_recent_conversations,
    _format_learning_prompt,
    generate_learnings,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_thing(
    conn,
    thing_id: str,
    title: str,
    *,
    type_hint: str | None = None,
    surface: bool = True,
    active: bool = True,
    data: dict | None = None,
    user_id: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO things
           (id, title, type_hint, active, surface, data, created_at, updated_at, user_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            thing_id,
            title,
            type_hint,
            int(active),
            int(surface),
            json.dumps(data) if data else None,
            now,
            now,
            user_id,
        ),
    )


def _insert_chat_message(conn, content: str, role: str = "user", user_id: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO chat_history (session_id, role, content, timestamp, user_id)
           VALUES (?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), role, content, now, user_id),
    )


def _insert_relationship(conn, from_id: str, to_id: str, rel_type: str) -> None:
    conn.execute(
        """INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type)
           VALUES (?, ?, ?, ?)""",
        (str(uuid.uuid4()), from_id, to_id, rel_type),
    )


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestFetchRecentConversations:
    def test_returns_user_messages(self, patched_db):
        with db() as conn:
            _insert_chat_message(conn, "Hello, what's on my plate?")
            _insert_chat_message(conn, "I prefer morning meetings")
            _insert_chat_message(conn, "Agent response", role="assistant")
        with db() as conn:
            results = _fetch_recent_conversations(conn, days=7)
        assert len(results) == 2
        assert all(r["role"] == "user" for r in results)

    def test_empty_history(self, patched_db):
        with db() as conn:
            results = _fetch_recent_conversations(conn, days=7)
        assert results == []


class TestFetchExistingLearnings:
    def test_returns_learning_things(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "l1", "User prefers mornings", type_hint="learning")
            _insert_thing(conn, "t1", "Some task", type_hint="task")
        with db() as conn:
            results = _fetch_existing_learnings(conn)
        assert len(results) == 1
        assert results[0]["title"] == "User prefers mornings"

    def test_excludes_inactive(self, patched_db):
        with db() as conn:
            _insert_thing(conn, "l1", "Old learning", type_hint="learning", active=False)
        with db() as conn:
            results = _fetch_existing_learnings(conn)
        assert results == []


class TestFormatLearningPrompt:
    def test_includes_conversations(self):
        convos = [{"content": "I like mornings", "timestamp": "2026-03-17"}]
        result = _format_learning_prompt(convos, [], [])
        assert "I like mornings" in result

    def test_includes_existing_learnings(self):
        learnings = [{"title": "User prefers mornings"}]
        result = _format_learning_prompt([], learnings, [])
        assert "User prefers mornings" in result

    def test_includes_things(self):
        things = [{"title": "Budget project", "type_hint": "project"}]
        result = _format_learning_prompt([], [], things)
        assert "Budget project" in result


# ---------------------------------------------------------------------------
# generate_learnings integration test
# ---------------------------------------------------------------------------


class TestGenerateLearnings:
    @pytest.mark.asyncio
    async def test_creates_learning_things(self, patched_db):
        """Learning generation creates Things with correct type, tags, and relationships."""
        with db() as conn:
            _insert_thing(conn, "user-1", "Alex", type_hint="person", surface=False)
            _insert_thing(conn, "proj-1", "Budget project", type_hint="project")
            _insert_chat_message(conn, "I always break down projects before starting")
            _insert_chat_message(conn, "Morning meetings work best for me")

        llm_response = json.dumps({
            "learnings": [
                {
                    "title": "Alex breaks down projects before starting",
                    "notes": "Observed from conversation about project approach",
                    "tags": ["learning", "user-pattern"],
                    "related_thing_titles": ["Budget project"],
                },
            ]
        })

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await generate_learnings()

        assert result.learnings_created == 1
        assert result.learnings[0]["title"] == "Alex breaks down projects before starting"
        assert "learning" in result.learnings[0]["tags"]

        # Verify the Thing was created in the database
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM things WHERE type_hint = 'learning'"
            ).fetchone()
            assert row is not None
            assert row["title"] == "Alex breaks down projects before starting"
            assert row["surface"] == 0  # learnings are not surfaced
            data = json.loads(row["data"])
            assert "learning" in data["tags"]

            # Verify LearnedAbout relationship to user Thing
            rels = conn.execute(
                "SELECT * FROM thing_relationships WHERE relationship_type = 'LearnedAbout'"
            ).fetchall()
            assert len(rels) == 1
            assert rels[0]["from_thing_id"] == "user-1"
            assert rels[0]["to_thing_id"] == row["id"]

            # Verify related-to relationship to domain Thing
            domain_rels = conn.execute(
                "SELECT * FROM thing_relationships WHERE from_thing_id = ? AND relationship_type = 'related-to'",
                (row["id"],),
            ).fetchall()
            assert len(domain_rels) == 1
            assert domain_rels[0]["to_thing_id"] == "proj-1"

    @pytest.mark.asyncio
    async def test_no_conversations_returns_empty(self, patched_db):
        """No recent conversations means no learnings generated."""
        result = await generate_learnings()
        assert result.learnings_created == 0
        assert result.learnings == []

    @pytest.mark.asyncio
    async def test_skips_duplicate_learnings(self, patched_db):
        """Learnings with same title as existing ones are skipped."""
        with db() as conn:
            _insert_thing(conn, "l1", "Alex prefers mornings", type_hint="learning")
            _insert_chat_message(conn, "I like mornings")

        llm_response = json.dumps({
            "learnings": [
                {
                    "title": "Alex prefers mornings",
                    "notes": "Duplicate",
                    "tags": ["learning"],
                    "related_thing_titles": [],
                },
            ]
        })

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await generate_learnings()

        assert result.learnings_created == 0

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty(self, patched_db):
        """Invalid LLM response returns empty result."""
        with db() as conn:
            _insert_chat_message(conn, "Something")

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value="not json"):
            result = await generate_learnings()

        assert result.learnings_created == 0

    @pytest.mark.asyncio
    async def test_ensures_learning_tag(self, patched_db):
        """The 'learning' tag is always present even if LLM doesn't include it."""
        with db() as conn:
            _insert_thing(conn, "user-1", "Alex", type_hint="person", surface=False)
            _insert_chat_message(conn, "I delegate well")

        llm_response = json.dumps({
            "learnings": [
                {
                    "title": "Alex delegates effectively",
                    "notes": "Good at delegation",
                    "tags": ["user-pattern"],
                    "related_thing_titles": [],
                },
            ]
        })

        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            result = await generate_learnings()

        assert result.learnings_created == 1
        assert "learning" in result.learnings[0]["tags"]

        with db() as conn:
            row = conn.execute("SELECT data FROM things WHERE type_hint = 'learning'").fetchone()
            data = json.loads(row["data"])
            assert "learning" in data["tags"]


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestLearningsEndpoint:
    def test_list_learnings_empty(self, client):
        resp = client.get("/api/things/learnings")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_learnings_returns_only_learnings(self, client):
        with db() as conn:
            _insert_thing(conn, "l1", "User prefers mornings", type_hint="learning", surface=False)
            _insert_thing(conn, "t1", "Some task", type_hint="task")
        resp = client.get("/api/things/learnings")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "User prefers mornings"
        assert data[0]["type_hint"] == "learning"

    def test_list_learnings_excludes_inactive(self, client):
        with db() as conn:
            _insert_thing(conn, "l1", "Active learning", type_hint="learning")
            _insert_thing(conn, "l2", "Inactive learning", type_hint="learning", active=False)
        resp = client.get("/api/things/learnings")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_list_learnings_includes_inactive_when_requested(self, client):
        with db() as conn:
            _insert_thing(conn, "l1", "Active", type_hint="learning")
            _insert_thing(conn, "l2", "Inactive", type_hint="learning", active=False)
        resp = client.get("/api/things/learnings?active_only=false")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestSweepLearningsEndpoint:
    @pytest.mark.asyncio
    async def test_learning_generation_endpoint(self, async_client, patched_db):
        with db() as conn:
            _insert_chat_message(conn, "I prefer detailed plans")

        llm_response = json.dumps({"learnings": []})
        with patch("backend.agents._chat", new_callable=AsyncMock, return_value=llm_response):
            resp = await async_client.post("/api/sweep/learnings")

        assert resp.status_code == 200
        data = resp.json()
        assert "learnings_created" in data
        assert "learnings" in data


# ---------------------------------------------------------------------------
# Learning type in thing types
# ---------------------------------------------------------------------------


class TestLearningThingType:
    def test_learning_type_seeded(self, patched_db):
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM thing_types WHERE name = 'learning'"
            ).fetchone()
        assert row is not None
        assert row["icon"] == "🔍"
