"""Tests for response_agent.parse_response() and _build_user_prompt()."""

from backend.response_agent import _build_user_prompt, parse_response


class TestParseResponse:
    def test_valid_json_fence_with_referenced_things(self):
        raw = (
            'Here is your answer.\n\n```json\n{"referenced_things": [{"mention": "PR review", "thing_id": "t-1"}]}\n```'
        )
        result = parse_response(raw)
        assert result.text == "Here is your answer."
        assert result.referenced_things == [{"mention": "PR review", "thing_id": "t-1"}]

    def test_no_json_fence(self):
        raw = "Just a plain response with no JSON."
        result = parse_response(raw)
        assert result.text == "Just a plain response with no JSON."
        assert result.referenced_things == []

    def test_malformed_json_inside_fence(self):
        raw = "Some text before.\n\n```json\n{not valid json}\n```"
        result = parse_response(raw)
        assert result.text == "Some text before."
        assert result.referenced_things == []

    def test_referenced_things_not_a_list(self):
        raw = 'Text.\n\n```json\n{"referenced_things": "not a list"}\n```'
        result = parse_response(raw)
        assert result.text == "Text."
        assert result.referenced_things == []

    def test_entries_missing_required_keys(self):
        raw = (
            "Text.\n\n"
            "```json\n"
            '{"referenced_things": [{"mention": "only mention"}, {"thing_id": "only id"},'
            ' {"mention": "ok", "thing_id": "t-2"}]}\n'
            "```"
        )
        result = parse_response(raw)
        assert result.text == "Text."
        assert result.referenced_things == [{"mention": "ok", "thing_id": "t-2"}]

    def test_multiple_json_fences_causes_malformed_json(self):
        raw = (
            "First block:\n\n"
            "```json\n"
            '{"referenced_things": [{"mention": "first", "thing_id": "t-1"}]}\n'
            "```\n\n"
            "More text.\n\n"
            "```json\n"
            '{"referenced_things": [{"mention": "second", "thing_id": "t-2"}]}\n'
            "```"
        )
        result = parse_response(raw)
        # DOTALL regex spans both fences, producing malformed JSON → fallback
        assert result.text == "First block:"
        assert result.referenced_things == []


class TestBuildUserPrompt:
    def test_basic_message_and_reasoning(self):
        result = _build_user_prompt(
            message="Hello",
            reasoning_summary="User said hello",
            questions_for_user=[],
            applied_changes={},
        )
        assert "Hello" in result
        assert "User said hello" in result

    def test_with_web_results(self):
        result = _build_user_prompt(
            message="Search for X",
            reasoning_summary="Found info about X",
            questions_for_user=[],
            applied_changes={},
            web_results=[{"title": "Result 1", "url": "http://example.com"}],
        )
        assert "Web search results" in result
        assert "Result 1" in result

    def test_with_briefing_mode(self):
        result = _build_user_prompt(
            message="Good morning",
            reasoning_summary="Briefing summary",
            questions_for_user=[],
            applied_changes={},
            briefing_mode=True,
        )
        assert "true" in result.lower() or "True" in result

    def test_with_open_questions(self):
        result = _build_user_prompt(
            message="Tell me about my tasks",
            reasoning_summary="Context gathered",
            questions_for_user=[],
            applied_changes={},
            open_questions_by_thing={"task-1": ["What is the deadline?"]},
        )
        assert "Open questions" in result
        assert "What is the deadline?" in result
