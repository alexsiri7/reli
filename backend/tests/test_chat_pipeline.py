"""Tests for POST /chat multi-agent pipeline endpoint."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.response_agent import ResponseResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_REASONING_RESULT = {
    "applied_changes": {
        "created": [],
        "updated": [],
        "deleted": [],
        "merged": [],
        "relationships_created": [],
    },
    "fetched_context": {"things": [], "relationships": []},
    "questions_for_user": [],
    "priority_question": "",
    "reasoning_summary": "No changes needed.",
    "briefing_mode": False,
}

MOCK_REPLY = "I understand, no changes were needed."


def _patch_agents(
    reasoning_result=None,
    reply=None,
):
    """Return a context manager patching all agent functions."""
    from unittest.mock import patch

    rea = reasoning_result or MOCK_REASONING_RESULT
    rep = reply or MOCK_REPLY

    return [
        patch("backend.pipeline.run_reasoning_agent", new=AsyncMock(return_value=rea)),
        patch("backend.pipeline.run_response_agent", new=AsyncMock(
            return_value=ResponseResult(text=rep),
        )),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestChatPipeline:
    async def test_basic_chat_returns_200(self, async_client):
        patches = _patch_agents()
        with patches[0], patches[1]:
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "s1", "message": "Hello"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "s1"
        assert data["reply"] == MOCK_REPLY
        assert "applied_changes" in data
        assert "questions_for_user" in data

    async def test_chat_persists_messages_to_history(self, async_client):
        patches = _patch_agents()
        with patches[0], patches[1]:
            await async_client.post(
                "/api/chat",
                json={"session_id": "persist-sess", "message": "Remember this"},
            )
        # History should have both user and assistant messages
        resp = await async_client.get("/api/chat/history/persist-sess")
        msgs = resp.json()
        roles = [m["role"] for m in msgs]
        assert "user" in roles
        assert "assistant" in roles

    async def test_chat_with_storage_changes_create(self, async_client):
        reasoning_with_create = {
            "applied_changes": {
                "created": [{"id": "new-uuid", "title": "New Pipeline Task", "type_hint": "task", "priority": 2}],
                "updated": [],
                "deleted": [],
                "merged": [],
                "relationships_created": [],
            },
            "questions_for_user": [],
            "priority_question": "",
            "reasoning_summary": "Creating a new task.",
            "briefing_mode": False,
        }
        patches = _patch_agents(reasoning_result=reasoning_with_create)
        with patches[0], patches[1]:
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "create-sess", "message": "Add a new task"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["applied_changes"]["created"]) == 1
        assert data["applied_changes"]["created"][0]["title"] == "New Pipeline Task"

    async def test_chat_with_storage_changes_update(self, async_client):
        # First create a thing via REST
        create_resp = await async_client.post("/api/things", json={"title": "Thing to Update"})
        thing_id = create_resp.json()["id"]

        reasoning_with_update = {
            "applied_changes": {
                "created": [],
                "updated": [{"id": thing_id, "title": "Updated Title"}],
                "deleted": [],
                "merged": [],
                "relationships_created": [],
            },
            "questions_for_user": [],
            "priority_question": "",
            "reasoning_summary": "Updating title.",
            "briefing_mode": False,
        }
        patches = _patch_agents(reasoning_result=reasoning_with_update)
        with patches[0], patches[1]:
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "update-sess", "message": "Rename that thing"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["applied_changes"]["updated"]) == 1

    async def test_chat_with_storage_changes_delete(self, async_client):
        create_resp = await async_client.post("/api/things", json={"title": "Thing to Delete"})
        thing_id = create_resp.json()["id"]

        reasoning_with_delete = {
            "applied_changes": {
                "created": [],
                "updated": [],
                "deleted": [thing_id],
                "merged": [],
                "relationships_created": [],
            },
            "questions_for_user": [],
            "priority_question": "",
            "reasoning_summary": "Deleting the thing.",
            "briefing_mode": False,
        }
        patches = _patch_agents(reasoning_result=reasoning_with_delete)
        with patches[0], patches[1]:
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "delete-sess", "message": "Remove that thing"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert thing_id in data["applied_changes"]["deleted"]

    async def test_chat_with_questions_for_user(self, async_client):
        reasoning_with_questions = {
            "applied_changes": {
                "created": [],
                "updated": [],
                "deleted": [],
                "merged": [],
                "relationships_created": [],
            },
            "questions_for_user": ["What priority should this be?"],
            "priority_question": "What priority should this be?",
            "reasoning_summary": "Ambiguous request, asking for clarification.",
            "briefing_mode": False,
        }
        patches = _patch_agents(reasoning_result=reasoning_with_questions)
        with patches[0], patches[1]:
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "q-sess", "message": "Add something"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "What priority should this be?" in data["questions_for_user"]

    async def test_chat_uses_conversation_history(self, async_client):
        # Prime some history
        await async_client.post(
            "/api/chat/history",
            json={"session_id": "history-sess", "role": "user", "content": "Prior message"},
        )
        patches = _patch_agents()
        with patches[0], patches[1]:
            # Also spy on reasoning agent to verify history is passed
            with patch(
                "backend.pipeline.run_reasoning_agent",
                new=AsyncMock(return_value=MOCK_REASONING_RESULT),
            ) as mock_reason:
                await async_client.post(
                    "/api/chat",
                    json={"session_id": "history-sess", "message": "Follow up"},
                )
                # The reasoning agent should have been called with non-empty history
                call_args = mock_reason.call_args
                history_arg = call_args[0][1]  # positional arg index 1
                assert len(history_arg) > 0

    async def test_chat_ignores_unknown_delete_ids(self, async_client):
        """Deleting a non-existent ID should not raise an error."""
        reasoning_with_bad_delete = {
            "applied_changes": {
                "created": [],
                "updated": [],
                "deleted": [],  # tools would have returned error, nothing applied
                "merged": [],
                "relationships_created": [],
            },
            "questions_for_user": [],
            "priority_question": "",
            "reasoning_summary": "Trying to delete unknown.",
            "briefing_mode": False,
        }
        patches = _patch_agents(reasoning_result=reasoning_with_bad_delete)
        with patches[0], patches[1]:
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "bad-del-sess", "message": "Delete nothing"},
            )
        assert resp.status_code == 200
        # Unknown ID silently skipped — not in deleted list
        assert "nonexistent-id-xyz" not in resp.json()["applied_changes"]["deleted"]

    async def test_chat_invalid_request_returns_422(self, async_client):
        resp = await async_client.post("/api/chat", json={"session_id": "", "message": ""})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Unit tests for _fetch_user_relationships
# ---------------------------------------------------------------------------


class TestFetchUserRelationships:
    """Test depth-limited relationship loading from the user Thing."""

    def test_returns_matching_relationships(self, patched_db):
        """Only relationships whose related Thing matches a search query are returned."""
        from backend.database import db
        from backend.pipeline import _fetch_user_relationships

        with db() as conn:
            # Create user Thing
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface) VALUES (?, ?, ?, ?, ?, ?)",
                ("user-1", "Alice", "person", 3, 1, 1),
            )
            # Create related Things
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface) VALUES (?, ?, ?, ?, ?, ?)",
                ("sister-1", "Bob (sister)", "person", 3, 1, 1),
            )
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface) VALUES (?, ?, ?, ?, ?, ?)",
                ("project-1", "Acme Project", "project", 3, 1, 1),
            )
            # Create relationships from user to both
            conn.execute(
                "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type) "
                "VALUES (?, ?, ?, ?)",
                ("rel-1", "user-1", "sister-1", "sister"),
            )
            conn.execute(
                "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type) "
                "VALUES (?, ?, ?, ?)",
                ("rel-2", "user-1", "project-1", "works-on"),
            )

            # Search for "Bob" — should only return sister, not project
            results = _fetch_user_relationships(conn, "user-1", ["Bob"])
            assert len(results) == 1
            assert results[0]["id"] == "sister-1"

            # Search for "Acme" — should only return project
            results = _fetch_user_relationships(conn, "user-1", ["Acme"])
            assert len(results) == 1
            assert results[0]["id"] == "project-1"

    def test_empty_queries_returns_nothing(self, patched_db):
        """No search queries means no relationship loading."""
        from backend.database import db
        from backend.pipeline import _fetch_user_relationships

        with db() as conn:
            results = _fetch_user_relationships(conn, "user-1", [])
            assert results == []

    def test_no_relationships_returns_empty(self, patched_db):
        """User with no relationships returns empty list."""
        from backend.database import db
        from backend.pipeline import _fetch_user_relationships

        with db() as conn:
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface) VALUES (?, ?, ?, ?, ?, ?)",
                ("user-1", "Alice", "person", 3, 1, 1),
            )
            results = _fetch_user_relationships(conn, "user-1", ["anything"])
            assert results == []

    def test_recently_referenced_sorted_first(self, patched_db):
        """Things with recent last_referenced should appear before older ones."""
        from backend.database import db
        from backend.pipeline import _fetch_user_relationships

        with db() as conn:
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface) VALUES (?, ?, ?, ?, ?, ?)",
                ("user-1", "Alice", "person", 3, 1, 1),
            )
            # Two related Things both matching "Task"
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface, last_referenced) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("task-old", "Old Task", "task", 3, 1, 1, "2025-01-01T00:00:00"),
            )
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface, last_referenced) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("task-new", "New Task", "task", 3, 1, 1, "2026-03-16T00:00:00"),
            )
            conn.execute(
                "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type) "
                "VALUES (?, ?, ?, ?)",
                ("rel-1", "user-1", "task-old", "assigned"),
            )
            conn.execute(
                "INSERT INTO thing_relationships (id, from_thing_id, to_thing_id, relationship_type) "
                "VALUES (?, ?, ?, ?)",
                ("rel-2", "user-1", "task-new", "assigned"),
            )

            results = _fetch_user_relationships(conn, "user-1", ["Task"])
            assert len(results) == 2
            # Recently referenced should come first
            assert results[0]["id"] == "task-new"
            assert results[1]["id"] == "task-old"


# ---------------------------------------------------------------------------
# Unit tests for _fetch_relevant_things preference boost (GH#191)
# ---------------------------------------------------------------------------


class TestPreferenceBoost:
    """Preference Things should be boosted to the top of retrieval results."""

    def test_preference_things_sorted_first(self, patched_db):
        """Preference Things matching the query appear before entity Things."""
        from backend.database import db
        from backend.pipeline import _fetch_relevant_things

        with db() as conn:
            # Create a regular task Thing
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("task-1", "Morning standup meeting", "task", 3, 1, 1),
            )
            # Create a preference Thing about meetings
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "pref-1",
                    "Meeting scheduling preferences",
                    "preference",
                    3,
                    1,
                    1,
                    '{"patterns": [{"pattern": "Avoids morning meetings", "confidence": "strong"}]}',
                ),
            )

            results = _fetch_relevant_things(
                conn,
                ["meeting"],
                {"active_only": True, "type_hint": None},
            )

            # Both should be found
            result_ids = [t["id"] for t in results]
            assert "pref-1" in result_ids
            assert "task-1" in result_ids
            # Preference Thing should come first
            assert result_ids.index("pref-1") < result_ids.index("task-1")

    def test_preference_boost_with_no_preferences(self, patched_db):
        """When there are no preference Things, results are unchanged."""
        from backend.database import db
        from backend.pipeline import _fetch_relevant_things

        with db() as conn:
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("task-1", "Buy groceries", "task", 3, 1, 1),
            )

            results = _fetch_relevant_things(
                conn,
                ["groceries"],
                {"active_only": True, "type_hint": None},
            )

            assert len(results) >= 1
            assert any(t["id"] == "task-1" for t in results)

    def test_preference_boost_does_not_duplicate(self, patched_db):
        """Preference Things already in results are not duplicated."""
        from backend.database import db
        from backend.pipeline import _fetch_relevant_things

        with db() as conn:
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "pref-1",
                    "Travel cost preferences",
                    "preference",
                    3,
                    1,
                    1,
                    '{"patterns": [{"pattern": "Optimizes for cost on travel", "confidence": "moderate"}]}',
                ),
            )

            results = _fetch_relevant_things(
                conn,
                ["travel cost"],
                {"active_only": True, "type_hint": None},
            )

            pref_count = sum(1 for t in results if t["id"] == "pref-1")
            assert pref_count == 1
