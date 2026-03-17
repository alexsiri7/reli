"""Tests for the interaction style calibration module."""

from backend.interaction_style import (
    InteractionStyle,
    determine_style,
    get_reasoning_style_hint,
    get_style_prompt,
)


class TestDetermineStyle:
    """Tests for determine_style()."""

    def test_explicit_coaching_preference(self):
        style = determine_style("coaching", "hello", [])
        assert style == InteractionStyle.COACHING

    def test_explicit_consultant_preference(self):
        style = determine_style("consultant", "hello", [])
        assert style == InteractionStyle.CONSULTANT

    def test_briefing_mode_overrides_to_consultant(self):
        style = determine_style("coaching", "what's on my plate?", [], briefing_mode=True)
        assert style == InteractionStyle.CONSULTANT

    def test_adaptive_detects_coaching_signals(self):
        style = determine_style("adaptive", "how should i approach this project? I'm not sure where to start", [])
        assert style == InteractionStyle.COACHING

    def test_adaptive_detects_consultant_signals(self):
        style = determine_style("adaptive", "create a reminder to call the dentist", [])
        assert style == InteractionStyle.CONSULTANT

    def test_adaptive_defaults_to_consultant(self):
        # Neutral message with no strong signals
        style = determine_style("adaptive", "hello there", [])
        assert style == InteractionStyle.CONSULTANT

    def test_invalid_preference_treated_as_adaptive(self):
        style = determine_style("invalid_value", "create a task", [])
        assert style == InteractionStyle.CONSULTANT

    def test_question_mark_boosts_coaching(self):
        style = determine_style("adaptive", "what do you think about this approach? help me decide", [])
        assert style == InteractionStyle.COACHING

    def test_history_influences_style(self):
        history = [
            {"role": "user", "content": "how should I handle this?"},
            {"role": "assistant", "content": "Great question!"},
            {"role": "user", "content": "what do you think about this?"},
            {"role": "assistant", "content": "I'd suggest..."},
        ]
        style = determine_style("adaptive", "what are my options?", history)
        assert style == InteractionStyle.COACHING


class TestGetStylePrompt:
    """Tests for get_style_prompt()."""

    def test_coaching_prompt_contains_questions(self):
        prompt = get_style_prompt(InteractionStyle.COACHING)
        assert "COACHING" in prompt
        assert "questions" in prompt.lower()

    def test_consultant_prompt_contains_recommendations(self):
        prompt = get_style_prompt(InteractionStyle.CONSULTANT)
        assert "CONSULTANT" in prompt
        assert "recommend" in prompt.lower()

    def test_adaptive_falls_back_to_consultant(self):
        prompt = get_style_prompt(InteractionStyle.ADAPTIVE)
        assert "CONSULTANT" in prompt


class TestGetReasoningStyleHint:
    """Tests for get_reasoning_style_hint()."""

    def test_coaching_hint(self):
        hint = get_reasoning_style_hint(InteractionStyle.COACHING)
        assert "COACHING" in hint
        assert len(hint) > 0

    def test_consultant_hint(self):
        hint = get_reasoning_style_hint(InteractionStyle.CONSULTANT)
        assert "CONSULTANT" in hint

    def test_adaptive_returns_empty(self):
        hint = get_reasoning_style_hint(InteractionStyle.ADAPTIVE)
        assert hint == ""
