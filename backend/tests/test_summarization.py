"""Tests for the summarization agent and conversation_summaries CRUD."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.database import db
from backend.routers.chat import _fetch_history, _maybe_trigger_summarization
from backend.summarization_agent import (
    DEFAULT_SUMMARY_TRIGGER_N,
    create_summary,
    get_latest_summary,
    get_message_count_since_summary,
    get_messages_since_summary,
    should_summarize,
    summarize_conversation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_test_user(conn, user_id="test-user"):
    """Insert a test user into the users table."""
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
# Database CRUD tests
# ---------------------------------------------------------------------------


class TestConversationSummariesCRUD:
    """Test conversation_summaries table and CRUD functions."""

    def test_create_and_get_summary(self, patched_db):
        """create_summary persists a row and get_latest_summary retrieves it."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)

        row_id = create_summary(
            user_id=user_id,
            summary_text="User discussed project plans.",
            messages_summarized_up_to=42,
            token_count=150,
        )
        assert row_id is not None

        latest = get_latest_summary(user_id)
        assert latest is not None
        assert latest["summary_text"] == "User discussed project plans."
        assert latest["messages_summarized_up_to"] == 42
        assert latest["token_count"] == 150

    def test_get_latest_returns_most_recent(self, patched_db):
        """get_latest_summary returns the summary with highest messages_summarized_up_to."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)

        create_summary(user_id, "First summary", 10, 100)
        create_summary(user_id, "Second summary", 25, 200)
        create_summary(user_id, "Third summary", 20, 150)

        latest = get_latest_summary(user_id)
        assert latest is not None
        assert latest["summary_text"] == "Second summary"
        assert latest["messages_summarized_up_to"] == 25

    def test_get_latest_returns_none_when_empty(self, patched_db):
        """get_latest_summary returns None when no summaries exist."""
        assert get_latest_summary("nonexistent-user") is None

    def test_get_messages_since_summary_all_messages(self, patched_db):
        """Without a summary, returns all messages for the user."""
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
                ],
            )

        messages = get_messages_since_summary(user_id)
        assert len(messages) == 3
        assert messages[0]["content"] == "Hello"
        assert messages[2]["content"] == "How are you?"

    def test_get_messages_since_summary_after_summary(self, patched_db):
        """After creating a summary, only returns newer messages."""
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
                ],
            )

        # Summarize up to the second message
        create_summary(user_id, "Summary of old messages", msg_ids[1], 100)

        with db() as conn:
            _insert_messages(
                conn,
                user_id,
                [
                    ("user", "New message"),
                    ("assistant", "New response"),
                ],
            )

        messages = get_messages_since_summary(user_id)
        # Should include msg_ids[2] ("Old message 2") and the two new ones
        assert len(messages) == 3
        assert messages[0]["content"] == "Old message 2"
        assert messages[1]["content"] == "New message"

    def test_get_message_count_since_summary(self, patched_db):
        """get_message_count_since_summary returns the correct count."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            msg_ids = _insert_messages(
                conn,
                user_id,
                [
                    ("user", "msg1"),
                    ("assistant", "resp1"),
                ],
            )

        assert get_message_count_since_summary(user_id) == 2

        create_summary(user_id, "Summary", msg_ids[-1], 50)
        assert get_message_count_since_summary(user_id) == 0

        with db() as conn:
            _insert_messages(
                conn,
                user_id,
                [
                    ("user", "msg2"),
                    ("assistant", "resp2"),
                    ("user", "msg3"),
                ],
            )

        assert get_message_count_since_summary(user_id) == 3

    def test_create_summary_default_token_count(self, patched_db):
        """create_summary defaults token_count to 0 when omitted."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)

        create_summary(user_id, "A summary", 10)

        latest = get_latest_summary(user_id)
        assert latest is not None
        assert latest["token_count"] == 0

    def test_created_at_is_populated(self, patched_db):
        """create_summary sets created_at timestamp automatically."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)

        create_summary(user_id, "A summary", 5, 50)

        latest = get_latest_summary(user_id)
        assert latest is not None
        assert latest["created_at"] is not None

    def test_user_isolation(self, patched_db):
        """Summaries and messages are isolated per user."""
        with db() as conn:
            _create_test_user(conn, "user-a")
            _create_test_user(conn, "user-b")
            _insert_messages(conn, "user-a", [("user", "A's message")])
            _insert_messages(conn, "user-b", [("user", "B's message")])

        create_summary("user-a", "A's summary", 999, 100)

        assert get_latest_summary("user-a") is not None
        assert get_latest_summary("user-b") is None

        msgs_a = get_messages_since_summary("user-a")
        msgs_b = get_messages_since_summary("user-b")
        assert all(m["content"].startswith("A") for m in msgs_a)
        assert all(m["content"].startswith("B") for m in msgs_b)


# ---------------------------------------------------------------------------
# should_summarize tests
# ---------------------------------------------------------------------------


class TestShouldSummarize:
    def test_below_threshold(self, patched_db):
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            _insert_messages(conn, user_id, [("user", f"msg{i}") for i in range(5)])

        assert should_summarize(user_id) is False

    def test_at_threshold(self, patched_db):
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            _insert_messages(
                conn,
                user_id,
                [("user", f"msg{i}") for i in range(DEFAULT_SUMMARY_TRIGGER_N)],
            )

        assert should_summarize(user_id) is True

    def test_custom_threshold(self, patched_db):
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            _insert_messages(conn, user_id, [("user", f"msg{i}") for i in range(5)])

        assert should_summarize(user_id, trigger_n=5) is True
        assert should_summarize(user_id, trigger_n=6) is False


# ---------------------------------------------------------------------------
# summarize_conversation tests
# ---------------------------------------------------------------------------


class TestSummarizeConversation:
    @pytest.mark.asyncio
    async def test_no_messages_returns_none(self, patched_db):
        result = await summarize_conversation("nonexistent-user")
        assert result is None

    @pytest.mark.asyncio
    async def test_summarizes_messages(self, patched_db):
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            _insert_messages(
                conn,
                user_id,
                [
                    ("user", "I need to plan my vacation to Japan"),
                    ("assistant", "I'd love to help you plan your Japan trip!"),
                    ("user", "I want to visit Tokyo and Kyoto"),
                    ("assistant", "Great choices! Tokyo for modern culture, Kyoto for temples."),
                ],
            )

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="User is planning a vacation to Japan, visiting Tokyo and Kyoto."))
        ]
        mock_response.usage = MagicMock(prompt_tokens=200, completion_tokens=50)

        with patch("backend.summarization_agent.acomplete", new_callable=AsyncMock, return_value=mock_response):
            result = await summarize_conversation(user_id)

        assert result is not None
        assert "Japan" in result["summary_text"]
        assert result["messages_compressed"] == 4
        assert result["token_count"] == 250

        # Verify it was persisted
        latest = get_latest_summary(user_id)
        assert latest is not None
        assert "Japan" in latest["summary_text"]

    @pytest.mark.asyncio
    async def test_includes_previous_summary_in_prompt(self, patched_db):
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            msg_ids = _insert_messages(
                conn,
                user_id,
                [
                    ("user", "Old conversation about dogs"),
                    ("assistant", "Dogs are great pets!"),
                ],
            )

        create_summary(user_id, "User likes dogs.", msg_ids[-1], 50)

        with db() as conn:
            _insert_messages(
                conn,
                user_id,
                [
                    ("user", "Now let's talk about cats"),
                    ("assistant", "Cats are independent and elegant!"),
                ],
            )

        captured_messages = []

        async def mock_acomplete(messages, model, **kwargs):
            captured_messages.extend(messages)
            resp = MagicMock()
            resp.choices = [MagicMock(message=MagicMock(content="User likes dogs and cats."))]
            resp.usage = MagicMock(prompt_tokens=100, completion_tokens=30)
            return resp

        with patch("backend.summarization_agent.acomplete", side_effect=mock_acomplete):
            result = await summarize_conversation(user_id)

        assert result is not None
        # The user prompt should contain the previous summary
        user_prompt = captured_messages[1]["content"]
        assert "User likes dogs." in user_prompt
        assert "New Messages" in user_prompt

    @pytest.mark.asyncio
    async def test_tracks_usage_stats(self, patched_db):
        from backend.agents import UsageStats

        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            _insert_messages(conn, user_id, [("user", "Hello"), ("assistant", "Hi!")])

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Summary"))]
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=20)

        usage = UsageStats()

        with patch("backend.summarization_agent.acomplete", new_callable=AsyncMock, return_value=mock_response):
            await summarize_conversation(user_id, usage_stats=usage)

        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 20
        assert usage.api_calls == 1

    @pytest.mark.asyncio
    async def test_truncates_long_messages(self, patched_db):
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            _insert_messages(
                conn,
                user_id,
                [
                    ("user", "x" * 5000),  # Very long message
                ],
            )

        captured_messages = []

        async def mock_acomplete(messages, model, **kwargs):
            captured_messages.extend(messages)
            resp = MagicMock()
            resp.choices = [MagicMock(message=MagicMock(content="Summary of long msg"))]
            resp.usage = MagicMock(prompt_tokens=100, completion_tokens=20)
            return resp

        with patch("backend.summarization_agent.acomplete", side_effect=mock_acomplete):
            await summarize_conversation(user_id)

        user_prompt = captured_messages[1]["content"]
        assert "[truncated]" in user_prompt

    @pytest.mark.asyncio
    async def test_output_dict_has_all_keys(self, patched_db):
        """summarize_conversation returns a dict with all expected keys."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            _insert_messages(conn, user_id, [("user", "Hello"), ("assistant", "Hi!")])

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Summary text here"))]
        mock_response.usage = MagicMock(prompt_tokens=80, completion_tokens=15)

        with patch("backend.summarization_agent.acomplete", new_callable=AsyncMock, return_value=mock_response):
            result = await summarize_conversation(user_id)

        assert result is not None
        assert set(result.keys()) == {
            "id",
            "summary_text",
            "messages_summarized_up_to",
            "messages_compressed",
            "token_count",
            "cost_usd",
        }
        assert isinstance(result["id"], int)
        assert result["summary_text"] == "Summary text here"
        assert isinstance(result["messages_summarized_up_to"], int)
        assert result["messages_compressed"] == 2
        assert result["token_count"] == 95  # 80 + 15
        assert isinstance(result["cost_usd"], float)

    @pytest.mark.asyncio
    async def test_messages_summarized_up_to_is_last_msg_id(self, patched_db):
        """messages_summarized_up_to should equal the ID of the last message processed."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            msg_ids = _insert_messages(
                conn,
                user_id,
                [("user", "First"), ("assistant", "Second"), ("user", "Third")],
            )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Summary"))]
        mock_response.usage = MagicMock(prompt_tokens=50, completion_tokens=10)

        with patch("backend.summarization_agent.acomplete", new_callable=AsyncMock, return_value=mock_response):
            result = await summarize_conversation(user_id)

        assert result is not None
        assert result["messages_summarized_up_to"] == msg_ids[-1]


# ---------------------------------------------------------------------------
# _fetch_history (pipeline uses summary + recent) tests
# ---------------------------------------------------------------------------


class TestFetchHistory:
    """Test that _fetch_history uses summary + recent messages when available."""

    def test_without_summary_returns_raw_history(self, patched_db):
        """Without a summary, returns all messages up to context_window * 2."""
        user_id = "test-user"
        session_id = "sess-1"
        with db() as conn:
            _create_test_user(conn, user_id)
            _insert_messages(
                conn,
                user_id,
                [
                    ("user", "Hello"),
                    ("assistant", "Hi there!"),
                    ("user", "How are you?"),
                ],
                session_id=session_id,
            )

        history = _fetch_history(session_id, context_window=10, user_id=user_id)
        assert len(history) == 3
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello"
        # No system summary message
        assert all(h["role"] in ("user", "assistant") for h in history)

    def test_with_summary_prepends_summary_and_returns_recent(self, patched_db):
        """With a summary, returns [summary_system_msg, ...recent_messages]."""
        user_id = "test-user"
        session_id = "sess-1"
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
                session_id=session_id,
            )

        # Summarize up to the second message
        create_summary(user_id, "User discussed old topics.", msg_ids[1], 100)

        # Add newer messages
        with db() as conn:
            _insert_messages(
                conn,
                user_id,
                [
                    ("user", "New question"),
                    ("assistant", "New answer"),
                ],
                session_id=session_id,
            )

        history = _fetch_history(session_id, context_window=10, user_id=user_id)

        # First message should be the summary as a system message
        assert history[0]["role"] == "system"
        assert "[Conversation summary]" in history[0]["content"]
        assert "User discussed old topics." in history[0]["content"]

        # Remaining messages are those after the summary point
        recent = history[1:]
        assert len(recent) == 4  # msg_ids[2], msg_ids[3], + 2 new
        assert recent[0]["content"] == "Old message 2"
        assert recent[-1]["content"] == "New answer"

    def test_without_user_id_falls_back_to_raw_history(self, patched_db):
        """Without user_id, skips summary lookup and returns raw history."""
        session_id = "sess-1"
        with db() as conn:
            _create_test_user(conn, "some-user")
            _insert_messages(
                conn,
                "some-user",
                [("user", "Hello"), ("assistant", "Hi")],
                session_id=session_id,
            )

        history = _fetch_history(session_id, context_window=10, user_id="")
        assert len(history) == 2
        assert history[0]["role"] == "user"

    def test_summary_excludes_old_messages(self, patched_db):
        """Messages before the summary point should not appear in history."""
        user_id = "test-user"
        session_id = "sess-1"
        with db() as conn:
            _create_test_user(conn, user_id)
            msg_ids = _insert_messages(
                conn,
                user_id,
                [
                    ("user", "Ancient message"),
                    ("assistant", "Ancient response"),
                ],
                session_id=session_id,
            )

        # Summarize up to last message
        create_summary(user_id, "Ancient history.", msg_ids[-1], 50)

        # Only new messages after summary
        with db() as conn:
            _insert_messages(
                conn,
                user_id,
                [("user", "Fresh message")],
                session_id=session_id,
            )

        history = _fetch_history(session_id, context_window=10, user_id=user_id)
        assert history[0]["role"] == "system"  # summary
        assert len(history) == 2  # summary + 1 new message
        assert history[1]["content"] == "Fresh message"
        # Old messages should NOT appear
        contents = [h["content"] for h in history]
        assert not any("Ancient" in c for c in contents if "[Conversation summary]" not in c)

    def test_respects_context_window_limit(self, patched_db):
        """History with summary is limited to context_window * 2 recent messages."""
        user_id = "test-user"
        session_id = "sess-1"
        with db() as conn:
            _create_test_user(conn, user_id)
            msg_ids = _insert_messages(
                conn,
                user_id,
                [("user", "Summarized msg")],
                session_id=session_id,
            )

        create_summary(user_id, "Old summary.", msg_ids[-1], 50)

        # Insert many messages after summary
        with db() as conn:
            _insert_messages(
                conn,
                user_id,
                [("user", f"msg-{i}") for i in range(20)],
                session_id=session_id,
            )

        # context_window=3 means limit is 6 recent messages
        history = _fetch_history(session_id, context_window=3, user_id=user_id)
        # Should be: 1 summary system msg + at most 6 recent messages
        assert history[0]["role"] == "system"
        assert len(history) <= 7  # 1 summary + 6 max


# ---------------------------------------------------------------------------
# _maybe_trigger_summarization tests
# ---------------------------------------------------------------------------


class TestMaybeTriggerSummarization:
    """Test that the compression trigger fires correctly."""

    def test_does_not_trigger_below_threshold(self, patched_db):
        """No summarization when message count is below threshold."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            _insert_messages(conn, user_id, [("user", f"msg{i}") for i in range(5)])

        with patch("backend.summarization_agent.summarize_conversation") as mock_summarize:
            _maybe_trigger_summarization(user_id)
            mock_summarize.assert_not_called()

    def test_triggers_at_threshold(self, patched_db):
        """Summarization is triggered when message count reaches threshold."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            _insert_messages(
                conn,
                user_id,
                [("user", f"msg{i}") for i in range(DEFAULT_SUMMARY_TRIGGER_N)],
            )

        loop = asyncio.new_event_loop()
        tasks_created = []

        original_create_task = loop.create_task

        def tracking_create_task(coro):
            task = original_create_task(coro)
            tasks_created.append(task)
            return task

        loop.create_task = tracking_create_task

        with patch("backend.routers.chat.asyncio.get_running_loop", return_value=loop):
            _maybe_trigger_summarization(user_id)

        assert len(tasks_created) == 1
        # Clean up: cancel the task and close the loop
        for t in tasks_created:
            t.cancel()
        loop.close()

    def test_does_not_trigger_for_empty_user_id(self, patched_db):
        """No summarization when user_id is empty."""
        with patch("backend.summarization_agent.should_summarize") as mock_should:
            _maybe_trigger_summarization("")
            mock_should.assert_not_called()

    def test_does_not_trigger_after_summary_resets_count(self, patched_db):
        """After summarization resets the count, trigger should not fire again."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            msg_ids = _insert_messages(
                conn,
                user_id,
                [("user", f"msg{i}") for i in range(DEFAULT_SUMMARY_TRIGGER_N)],
            )

        # Create a summary that covers all messages -- count resets to 0
        create_summary(user_id, "All summarized.", msg_ids[-1], 100)

        with patch("backend.summarization_agent.summarize_conversation") as mock_summarize:
            _maybe_trigger_summarization(user_id)
            mock_summarize.assert_not_called()
