"""Tests for summarization wiring into the chat pipeline.

Covers:
- _fetch_history uses summary + recent messages when a summary exists
- _fetch_history falls back to raw history when no summary exists
- _maybe_trigger_summarization fires at correct intervals
- Async summarization doesn't block the chat response
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.routers.chat import _fetch_history, _maybe_trigger_summarization
from backend.summarization_agent import create_summary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_test_user(conn, user_id="test-user"):
    conn.execute(
        "INSERT OR IGNORE INTO users (id, email, google_id, name) VALUES (?, ?, ?, ?)",
        (user_id, f"{user_id}@test.com", f"google-{user_id}", "Test User"),
    )


def _insert_messages(conn, user_id, messages, session_id="sess-1"):
    """Insert chat messages and return their IDs."""
    ids = []
    for role, content in messages:
        cursor = conn.execute(
            "INSERT INTO chat_history (session_id, role, content, user_id) VALUES (?, ?, ?, ?)",
            (session_id, role, content, user_id),
        )
        ids.append(cursor.lastrowid)
    return ids


# ---------------------------------------------------------------------------
# _fetch_history tests
# ---------------------------------------------------------------------------


class TestFetchHistory:
    """Test that _fetch_history correctly uses summaries when available."""

    def test_fallback_to_raw_history_without_summary(self, patched_db, db):
        """Without a summary, returns raw history messages."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            _insert_messages(
                conn,
                user_id,
                [
                    ("user", "Hello"),
                    ("assistant", "Hi there!"),
                    ("user", "How are you?"),
                    ("assistant", "I'm great!"),
                ],
            )

        history = _fetch_history("sess-1", context_window=50, user_id=user_id)
        assert len(history) == 4
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello"
        assert history[3]["content"] == "I'm great!"

    def test_uses_summary_plus_recent_messages(self, patched_db, db):
        """With a summary, returns summary as system message + only recent messages."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            msg_ids = _insert_messages(
                conn,
                user_id,
                [
                    ("user", "Old message 1"),
                    ("assistant", "Old response 1"),
                    ("user", "Old message 2"),
                    ("assistant", "Old response 2"),
                ],
            )

        # Create summary covering the first two messages
        create_summary(user_id, "User discussed old topics.", msg_ids[1], 100)

        with db() as conn:
            _insert_messages(
                conn,
                user_id,
                [
                    ("user", "New message"),
                    ("assistant", "New response"),
                ],
            )

        history = _fetch_history("sess-1", context_window=50, user_id=user_id)

        # First entry should be the summary as a system message
        assert history[0]["role"] == "system"
        assert "[Conversation summary]" in history[0]["content"]
        assert "User discussed old topics." in history[0]["content"]

        # Remaining entries should be messages after the summary point
        non_system = [h for h in history if h["role"] != "system"]
        # msg_ids[1] was summarized up to, so messages with id > msg_ids[1] should appear
        # That includes Old message 2, Old response 2, New message, New response
        assert len(non_system) == 4
        assert non_system[0]["content"] == "Old message 2"
        assert non_system[-1]["content"] == "New response"

    def test_summary_excludes_old_messages(self, patched_db, db):
        """Messages before the summary cutoff are NOT returned."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            msg_ids = _insert_messages(
                conn,
                user_id,
                [
                    ("user", "Ancient message"),
                    ("assistant", "Ancient response"),
                    ("user", "Recent message"),
                    ("assistant", "Recent response"),
                ],
            )

        # Summarize up to the second message
        create_summary(user_id, "Ancient topics were discussed.", msg_ids[1], 50)

        history = _fetch_history("sess-1", context_window=50, user_id=user_id)

        all_content = " ".join(h["content"] for h in history)
        assert "Ancient message" not in all_content
        assert "Ancient response" not in all_content
        assert "Recent message" in all_content
        assert "Recent response" in all_content

    def test_no_user_id_falls_back_to_raw_history(self, patched_db, db):
        """Without a user_id, summary lookup is skipped."""
        with db() as conn:
            _create_test_user(conn, "test-user")
            _insert_messages(
                conn,
                "test-user",
                [
                    ("user", "Hello"),
                    ("assistant", "Hi!"),
                ],
            )

        # No user_id — should return raw history
        history = _fetch_history("sess-1", context_window=50, user_id="")
        assert len(history) == 2
        assert history[0]["content"] == "Hello"

    def test_enrichment_metadata_preserved(self, patched_db, db):
        """Assistant messages with applied_changes get structured context_things in history."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            conn.execute(
                "INSERT INTO chat_history (session_id, role, content, applied_changes, user_id) VALUES (?, ?, ?, ?, ?)",
                (
                    "sess-1",
                    "assistant",
                    "I found that task",
                    json.dumps({"context_things": [{"id": "t1", "title": "My Task", "type_hint": "task"}]}),
                    user_id,
                ),
            )

        history = _fetch_history("sess-1", context_window=50, user_id=user_id)
        assert len(history) == 1
        assert "context_things" in history[0]
        assert history[0]["context_things"][0]["title"] == "My Task"


# ---------------------------------------------------------------------------
# _maybe_trigger_summarization tests
# ---------------------------------------------------------------------------


class TestMaybeTriggerSummarization:
    """Test that summarization is triggered at correct intervals."""

    def test_does_not_trigger_below_threshold(self, patched_db, db):
        """No summarization when message count is below threshold."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            _insert_messages(conn, user_id, [("user", f"msg{i}") for i in range(5)])

        with patch("backend.summarization_agent.summarize_conversation") as mock_summarize:
            _maybe_trigger_summarization(user_id)
            mock_summarize.assert_not_called()

    @pytest.mark.asyncio
    async def test_triggers_at_threshold(self, patched_db, db):
        """Summarization fires when message count reaches threshold."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            # DEFAULT_SUMMARY_TRIGGER_N is 20, so insert 20 messages
            _insert_messages(conn, user_id, [("user", f"msg{i}") for i in range(20)])

        with patch("backend.summarization_agent.summarize_conversation", new_callable=AsyncMock) as mock_summarize:
            _maybe_trigger_summarization(user_id)
            # Let background task run
            await asyncio.sleep(0.1)
            mock_summarize.assert_called_once_with(user_id)

    @pytest.mark.asyncio
    async def test_triggers_at_custom_threshold_below_default(self, patched_db, db):
        """Custom threshold below the default causes summarization at fewer messages."""
        from sqlmodel import Session

        import backend.db_engine as _engine_mod
        from backend.routers.settings import _set_user_setting

        user_id = "test-user-low-threshold"
        with db() as conn:
            _create_test_user(conn, user_id)
            # 15 messages would NOT trigger default threshold (20), but should trigger threshold=15
            _insert_messages(conn, user_id, [("user", f"msg{i}") for i in range(15)])

        with Session(_engine_mod.engine) as session:
            _set_user_setting(session, user_id, "messages_until_compression", "15")
            session.commit()

        with patch("backend.summarization_agent.summarize_conversation", new_callable=AsyncMock) as mock_summarize:
            _maybe_trigger_summarization(user_id)
            await asyncio.sleep(0.1)
            mock_summarize.assert_called_once_with(user_id)

    def test_does_not_trigger_below_custom_threshold(self, patched_db, db):
        """Custom threshold above the default suppresses summarization that would otherwise fire."""
        from sqlmodel import Session

        import backend.db_engine as _engine_mod
        from backend.routers.settings import _set_user_setting

        user_id = "test-user-high-threshold"
        with db() as conn:
            _create_test_user(conn, user_id)
            # 20 messages would trigger default threshold (20), but NOT threshold=30
            _insert_messages(conn, user_id, [("user", f"msg{i}") for i in range(20)])

        with Session(_engine_mod.engine) as session:
            _set_user_setting(session, user_id, "messages_until_compression", "30")
            session.commit()

        with patch("backend.summarization_agent.summarize_conversation") as mock_summarize:
            _maybe_trigger_summarization(user_id)
            mock_summarize.assert_not_called()

    def test_does_not_trigger_without_user_id(self, patched_db):
        """No summarization when user_id is empty."""
        with patch("backend.summarization_agent.should_summarize") as mock_should:
            _maybe_trigger_summarization("")
            mock_should.assert_not_called()


# ---------------------------------------------------------------------------
# Pipeline integration: summarization doesn't block response
# ---------------------------------------------------------------------------


class TestSummarizationNonBlocking:
    """Test that async summarization doesn't block the chat response."""

    @pytest.mark.asyncio
    async def test_chat_endpoint_returns_before_summarization_completes(self, patched_db, db):
        """The summarization runs in background and doesn't delay the response."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            _insert_messages(conn, user_id, [("user", f"msg{i}") for i in range(20)])

        summarization_started = asyncio.Event()
        summarization_can_finish = asyncio.Event()

        async def slow_summarize(uid):
            summarization_started.set()
            await summarization_can_finish.wait()

        with (
            patch("backend.summarization_agent.should_summarize", return_value=True),
            patch("backend.summarization_agent.summarize_conversation", side_effect=slow_summarize),
        ):
            # Trigger summarization — it should create a background task
            _maybe_trigger_summarization(user_id)

            # Give the background task a moment to start
            await asyncio.sleep(0.05)

            # Summarization should have started
            assert summarization_started.is_set(), "Background summarization should have started"

            # Let it finish
            summarization_can_finish.set()
            await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_summarization_error_does_not_crash_pipeline(self, patched_db, db):
        """If summarization fails, it logs but doesn't crash."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            _insert_messages(conn, user_id, [("user", f"msg{i}") for i in range(20)])

        async def failing_summarize(uid):
            raise RuntimeError("LLM is down")

        with (
            patch("backend.summarization_agent.should_summarize", return_value=True),
            patch("backend.summarization_agent.summarize_conversation", side_effect=failing_summarize),
        ):
            # Should not raise
            _maybe_trigger_summarization(user_id)
            await asyncio.sleep(0.1)  # Let background task run and fail gracefully
