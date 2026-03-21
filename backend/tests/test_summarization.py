"""Tests for the summarization agent and conversation_summaries CRUD."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from backend.database import (
    create_summary,
    db,
    get_latest_summary,
    get_message_count_since_summary,
    get_messages_since_summary,
)
from backend.summarization_agent import (
    DEFAULT_SUMMARY_TRIGGER_N,
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
            _insert_messages(conn, user_id, [
                ("user", "Hello"),
                ("assistant", "Hi there!"),
                ("user", "How are you?"),
            ])

        messages = get_messages_since_summary(user_id)
        assert len(messages) == 3
        assert messages[0]["content"] == "Hello"
        assert messages[2]["content"] == "How are you?"

    def test_get_messages_since_summary_after_summary(self, patched_db):
        """After creating a summary, only returns newer messages."""
        user_id = "test-user"
        with db() as conn:
            _create_test_user(conn, user_id)
            msg_ids = _insert_messages(conn, user_id, [
                ("user", "Old message 1"),
                ("assistant", "Old response 1"),
                ("user", "Old message 2"),
            ])

        # Summarize up to the second message
        create_summary(user_id, "Summary of old messages", msg_ids[1], 100)

        with db() as conn:
            _insert_messages(conn, user_id, [
                ("user", "New message"),
                ("assistant", "New response"),
            ])

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
            msg_ids = _insert_messages(conn, user_id, [
                ("user", "msg1"),
                ("assistant", "resp1"),
            ])

        assert get_message_count_since_summary(user_id) == 2

        create_summary(user_id, "Summary", msg_ids[-1], 50)
        assert get_message_count_since_summary(user_id) == 0

        with db() as conn:
            _insert_messages(conn, user_id, [
                ("user", "msg2"),
                ("assistant", "resp2"),
                ("user", "msg3"),
            ])

        assert get_message_count_since_summary(user_id) == 3

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
                conn, user_id,
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
            _insert_messages(conn, user_id, [
                ("user", "I need to plan my vacation to Japan"),
                ("assistant", "I'd love to help you plan your Japan trip!"),
                ("user", "I want to visit Tokyo and Kyoto"),
                ("assistant", "Great choices! Tokyo for modern culture, Kyoto for temples."),
            ])

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
            msg_ids = _insert_messages(conn, user_id, [
                ("user", "Old conversation about dogs"),
                ("assistant", "Dogs are great pets!"),
            ])

        create_summary(user_id, "User likes dogs.", msg_ids[-1], 50)

        with db() as conn:
            _insert_messages(conn, user_id, [
                ("user", "Now let's talk about cats"),
                ("assistant", "Cats are independent and elegant!"),
            ])

        captured_messages = []

        async def mock_acomplete(messages, model, **kwargs):
            captured_messages.extend(messages)
            resp = MagicMock()
            resp.choices = [
                MagicMock(message=MagicMock(content="User likes dogs and cats."))
            ]
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
            _insert_messages(conn, user_id, [
                ("user", "x" * 5000),  # Very long message
            ])

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
