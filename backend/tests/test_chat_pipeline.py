"""Tests for POST /chat multi-agent pipeline endpoint."""

from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_CONTEXT_RESULT = {
    "search_queries": ["test query"],
    "filter_params": {"active_only": True, "type_hint": None},
}

MOCK_REASONING_RESULT = {
    "storage_changes": {"create": [], "update": [], "delete": []},
    "questions_for_user": [],
    "reasoning_summary": "No changes needed.",
}

MOCK_REPLY = "I understand, no changes were needed."


MOCK_REFINEMENT_DONE = {"done": True}


def _patch_agents(
    context_result=None,
    reasoning_result=None,
    reply=None,
    refinement_result=None,
):
    """Return a context manager patching all agent functions."""
    from unittest.mock import patch

    ctx = context_result or MOCK_CONTEXT_RESULT
    rea = reasoning_result or MOCK_REASONING_RESULT
    rep = reply or MOCK_REPLY
    ref = refinement_result or MOCK_REFINEMENT_DONE

    return [
        patch("backend.routers.chat.run_context_agent", new=AsyncMock(return_value=ctx)),
        patch("backend.routers.chat.run_reasoning_agent", new=AsyncMock(return_value=rea)),
        patch("backend.routers.chat.run_response_agent", new=AsyncMock(return_value=rep)),
        patch("backend.routers.chat.run_context_refinement", new=AsyncMock(return_value=ref)),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestChatPipeline:
    async def test_basic_chat_returns_200(self, async_client):
        patches = _patch_agents()
        with patches[0], patches[1], patches[2], patches[3]:
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
        with patches[0], patches[1], patches[2], patches[3]:
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
            "storage_changes": {
                "create": [{"title": "New Pipeline Task", "type_hint": "task", "priority": 2}],
                "update": [],
                "delete": [],
            },
            "questions_for_user": [],
            "reasoning_summary": "Creating a new task.",
        }
        patches = _patch_agents(reasoning_result=reasoning_with_create)
        with patches[0], patches[1], patches[2], patches[3]:
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
            "storage_changes": {
                "create": [],
                "update": [{"id": thing_id, "changes": {"title": "Updated Title"}}],
                "delete": [],
            },
            "questions_for_user": [],
            "reasoning_summary": "Updating title.",
        }
        patches = _patch_agents(reasoning_result=reasoning_with_update)
        with patches[0], patches[1], patches[2], patches[3]:
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
            "storage_changes": {
                "create": [],
                "update": [],
                "delete": [thing_id],
            },
            "questions_for_user": [],
            "reasoning_summary": "Deleting the thing.",
        }
        patches = _patch_agents(reasoning_result=reasoning_with_delete)
        with patches[0], patches[1], patches[2], patches[3]:
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "delete-sess", "message": "Remove that thing"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert thing_id in data["applied_changes"]["deleted"]

    async def test_chat_with_questions_for_user(self, async_client):
        reasoning_with_questions = {
            "storage_changes": {"create": [], "update": [], "delete": []},
            "questions_for_user": ["What priority should this be?"],
            "reasoning_summary": "Ambiguous request, asking for clarification.",
        }
        patches = _patch_agents(reasoning_result=reasoning_with_questions)
        with patches[0], patches[1], patches[2], patches[3]:
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
        with patches[0], patches[1], patches[2], patches[3]:
            # Also spy on reasoning agent to verify history is passed
            with patch(
                "backend.routers.chat.run_reasoning_agent",
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
            "storage_changes": {
                "create": [],
                "update": [],
                "delete": ["nonexistent-id-xyz"],
            },
            "questions_for_user": [],
            "reasoning_summary": "Trying to delete unknown.",
        }
        patches = _patch_agents(reasoning_result=reasoning_with_bad_delete)
        with patches[0], patches[1], patches[2], patches[3]:
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "bad-del-sess", "message": "Delete nothing"},
            )
        assert resp.status_code == 200
        # Unknown ID silently skipped — not in deleted list
        assert "nonexistent-id-xyz" not in resp.json()["applied_changes"]["deleted"]

    async def test_chat_with_web_search(self, async_client):
        """When context agent requests web search and it's configured, results are included."""
        from backend.web_search import SearchResult

        context_with_search = {
            "search_queries": ["test"],
            "filter_params": {"active_only": True, "type_hint": None},
            "needs_web_search": True,
            "web_search_query": "python fastapi tutorial",
        }

        mock_search_results = [
            SearchResult(title="FastAPI Tutorial", url="https://example.com/fastapi", snippet="Learn FastAPI..."),
            SearchResult(title="Python Docs", url="https://docs.python.org", snippet="Official docs..."),
        ]

        patches = _patch_agents(context_result=context_with_search)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patch("backend.routers.chat.is_search_configured", return_value=True),
            patch("backend.routers.chat.google_search", new=AsyncMock(return_value=mock_search_results)),
        ):
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "search-sess", "message": "How do I use FastAPI?"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "web_results" in data["applied_changes"]
        assert len(data["applied_changes"]["web_results"]) == 2
        assert data["applied_changes"]["web_results"][0]["title"] == "FastAPI Tutorial"

    async def test_chat_web_search_skipped_when_not_configured(self, async_client):
        """When search is not configured, web search is skipped even if requested."""
        context_with_search = {
            "search_queries": ["test"],
            "filter_params": {"active_only": True, "type_hint": None},
            "needs_web_search": True,
            "web_search_query": "something",
        }
        patches = _patch_agents(context_result=context_with_search)
        with patches[0], patches[1], patches[2], patches[3]:
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "no-search-sess", "message": "Search for something"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "web_results" not in data["applied_changes"]

    async def test_chat_iterative_context_gathering(self, async_client):
        """Context agent can request additional searches in refinement loop."""
        # Create two things: one that references the other
        await async_client.post("/api/things", json={"title": "Sarah", "type_hint": "person"})
        await async_client.post(
            "/api/things", json={"title": "Barcelona Flat", "type_hint": "place"}
        )

        # First refinement asks for more, second says done
        refinement_calls = [
            {
                "done": False,
                "search_queries": ["Barcelona Flat"],
                "thing_ids": [],
                "filter_params": {"active_only": True},
            },
            {"done": True},
        ]
        refinement_mock = AsyncMock(side_effect=refinement_calls)

        patches = _patch_agents()
        with (
            patches[0],
            patches[1],
            patches[2],
            patch("backend.routers.chat.run_context_refinement", new=refinement_mock),
        ):
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "iter-sess", "message": "Book near Sarah's flat"},
            )
        assert resp.status_code == 200
        # Refinement was called (at least once for initial results, possibly twice)
        assert refinement_mock.call_count >= 1

    async def test_chat_context_refinement_stops_at_done(self, async_client):
        """Refinement loop stops when agent says done=true."""
        refinement_mock = AsyncMock(return_value={"done": True})

        patches = _patch_agents()
        with (
            patches[0],
            patches[1],
            patches[2],
            patch("backend.routers.chat.run_context_refinement", new=refinement_mock),
        ):
            resp = await async_client.post(
                "/api/chat",
                json={"session_id": "done-sess", "message": "Hello"},
            )
        assert resp.status_code == 200
        # Should be called exactly once (first refinement says done)
        # Note: may be 0 if no Things found to refine on
        assert refinement_mock.call_count <= 1

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
        from backend.routers.chat import _fetch_user_relationships

        with db() as conn:
            # Create user Thing
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("user-1", "Alice", "person", 3, 1, 1),
            )
            # Create related Things
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("sister-1", "Bob (sister)", "person", 3, 1, 1),
            )
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface) "
                "VALUES (?, ?, ?, ?, ?, ?)",
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
        from backend.routers.chat import _fetch_user_relationships

        with db() as conn:
            results = _fetch_user_relationships(conn, "user-1", [])
            assert results == []

    def test_no_relationships_returns_empty(self, patched_db):
        """User with no relationships returns empty list."""
        from backend.database import db
        from backend.routers.chat import _fetch_user_relationships

        with db() as conn:
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("user-1", "Alice", "person", 3, 1, 1),
            )
            results = _fetch_user_relationships(conn, "user-1", ["anything"])
            assert results == []

    def test_recently_referenced_sorted_first(self, patched_db):
        """Things with recent last_referenced should appear before older ones."""
        from backend.database import db
        from backend.routers.chat import _fetch_user_relationships

        with db() as conn:
            conn.execute(
                "INSERT INTO things (id, title, type_hint, priority, active, surface) "
                "VALUES (?, ?, ?, ?, ?, ?)",
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
