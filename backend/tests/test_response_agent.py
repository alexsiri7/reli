"""Tests for response_agent parse_response and streaming fence suppression."""

import pytest

from backend.response_agent import ResponseResult, parse_response


class TestParseResponse:
    def test_plain_text_no_json_block(self):
        result = parse_response("Hello, how can I help?")
        assert result.text == "Hello, how can I help?"
        assert result.referenced_things == []

    def test_extracts_referenced_things(self):
        raw = (
            "I talked to Bob about the trip.\n"
            "```json\n"
            '{"referenced_things": [{"mention": "Bob", "thing_id": "uuid-42"}, {"mention": "trip", "thing_id": "uuid-7"}]}\n'
            "```"
        )
        result = parse_response(raw)
        assert result.text == "I talked to Bob about the trip."
        assert len(result.referenced_things) == 2
        assert result.referenced_things[0] == {"mention": "Bob", "thing_id": "uuid-42"}
        assert result.referenced_things[1] == {"mention": "trip", "thing_id": "uuid-7"}

    def test_empty_referenced_things_list(self):
        raw = (
            "No specific Things mentioned.\n"
            "```json\n"
            '{"referenced_things": []}\n'
            "```"
        )
        result = parse_response(raw)
        assert result.text == "No specific Things mentioned."
        assert result.referenced_things == []

    def test_malformed_json_falls_back_gracefully(self):
        raw = (
            "Some response text.\n"
            "```json\n"
            "{not valid json}\n"
            "```"
        )
        result = parse_response(raw)
        # text is everything before the fence
        assert result.text == "Some response text."
        assert result.referenced_things == []

    def test_invalid_referenced_things_entries_filtered(self):
        raw = (
            "Response.\n"
            "```json\n"
            '{"referenced_things": [{"mention": "Bob"}, {"mention": "X", "thing_id": "id-1"}]}\n'
            "```"
        )
        result = parse_response(raw)
        # Entry without thing_id is dropped; valid entry is kept
        assert len(result.referenced_things) == 1
        assert result.referenced_things[0]["mention"] == "X"


class TestStreamingFenceSuppression:
    """Test that _run_agent_for_stream strips the JSON block.

    We test the fence-stripping logic indirectly by verifying that
    parse_response correctly splits raw output, which is what the non-streaming
    path uses.  For the streaming path, we verify the fence-stripping logic
    is present in the source and that parse_response handles the full raw output.
    """

    def test_parse_response_strips_fence_from_full_output(self):
        """Simulate what happens after streaming: full raw text is parsed."""
        full_raw = (
            "I scheduled the meeting with Alice.\n\n"
            "```json\n"
            '{"referenced_things": [{"mention": "Alice", "thing_id": "t-alice"}]}\n'
            "```\n"
        )
        result = parse_response(full_raw)
        assert result.text == "I scheduled the meeting with Alice."
        assert result.referenced_things == [{"mention": "Alice", "thing_id": "t-alice"}]

    def test_fence_suppression_logic_in_source(self):
        """Verify that the streaming generator contains fence-stripping code."""
        import inspect
        from backend.response_agent import _run_agent_for_stream
        source = inspect.getsource(_run_agent_for_stream)
        assert "```json" in source, "Streaming generator must check for JSON fence"
        assert "fence_hit" in source, "Streaming generator must track fence_hit flag"

    @pytest.mark.asyncio
    async def test_streaming_suppresses_json_block(self):
        """End-to-end: streaming yields only the text portion, not the JSON block."""
        from unittest.mock import AsyncMock, MagicMock, patch, AsyncMock
        from backend.response_agent import _run_agent_for_stream, _session_service

        full_text = (
            "Great, I've noted that.\n"
            "```json\n"
            '{"referenced_things": []}\n'
            "```"
        )

        # Build fake ADK events: one partial (full text so far), one final
        def _make_event(text: str, partial: bool, usage=False):
            part = MagicMock()
            part.text = text
            content = MagicMock()
            content.parts = [part]
            event = MagicMock()
            event.content = content
            event.partial = partial
            event.usage_metadata = None
            event.model_version = None
            return event

        events = [
            _make_event(full_text, partial=True),
            _make_event(full_text, partial=False),
        ]

        async def _fake_run_async(**kwargs):  # noqa: ARG001
            for ev in events:
                yield ev

        mock_runner = MagicMock()
        mock_runner.run_async.return_value = _fake_run_async()

        mock_agent = MagicMock()

        async def _fake_create_session(**kwargs):  # noqa: ARG001
            sess = MagicMock()
            sess.id = "test-session"
            return sess

        with patch("backend.response_agent.Runner", return_value=mock_runner), \
             patch.object(_session_service, "create_session", side_effect=_fake_create_session):
            tokens = []
            async for token in _run_agent_for_stream(mock_agent, "Hello"):
                tokens.append(token)

        collected = "".join(tokens)
        assert "```json" not in collected
        assert "referenced_things" not in collected
        assert "Great, I've noted that." in collected
