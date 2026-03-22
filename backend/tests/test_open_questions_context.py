"""Tests for open_questions surfacing in the context pipeline."""

import json

from backend.pipeline import _parse_thing_open_questions


# ---------------------------------------------------------------------------
# _parse_thing_open_questions
# ---------------------------------------------------------------------------


def test_parse_json_string_to_list():
    """JSON-encoded string is deserialized to a list."""
    thing = {"id": "t1", "open_questions": '["Q1?", "Q2?"]'}
    result = _parse_thing_open_questions(thing)
    assert result["open_questions"] == ["Q1?", "Q2?"]


def test_parse_already_list():
    """Already-parsed list is left unchanged."""
    thing = {"id": "t1", "open_questions": ["Q1?"]}
    result = _parse_thing_open_questions(thing)
    assert result["open_questions"] == ["Q1?"]


def test_parse_none():
    """None is left as None."""
    thing = {"id": "t1", "open_questions": None}
    result = _parse_thing_open_questions(thing)
    assert result["open_questions"] is None


def test_parse_missing():
    """Missing key is left absent."""
    thing = {"id": "t1"}
    result = _parse_thing_open_questions(thing)
    assert "open_questions" not in result


def test_parse_empty_string():
    """Empty string is left as-is (falsy)."""
    thing = {"id": "t1", "open_questions": ""}
    result = _parse_thing_open_questions(thing)
    assert result["open_questions"] == ""


def test_parse_invalid_json():
    """Invalid JSON string is set to None."""
    thing = {"id": "t1", "open_questions": "not valid json"}
    result = _parse_thing_open_questions(thing)
    assert result["open_questions"] is None


def test_parse_json_non_list():
    """JSON string encoding a non-list (e.g. dict) is set to None."""
    thing = {"id": "t1", "open_questions": '{"key": "value"}'}
    result = _parse_thing_open_questions(thing)
    assert result["open_questions"] is None


def test_parse_empty_list_string():
    """JSON string '[]' is deserialized to empty list."""
    thing = {"id": "t1", "open_questions": "[]"}
    result = _parse_thing_open_questions(thing)
    assert result["open_questions"] == []


# ---------------------------------------------------------------------------
# _collect_open_questions handles pre-parsed lists
# ---------------------------------------------------------------------------


def test_collect_open_questions_with_parsed_lists():
    """_collect_open_questions works with both pre-parsed lists and JSON strings."""
    from backend.pipeline import ChatPipeline

    relevant = [
        {"id": "t1", "title": "Trip", "open_questions": ["When?", "Where?"]},
        {"id": "t2", "title": "Meeting", "open_questions": '["Who is attending?"]'},
        {"id": "t3", "title": "No questions", "open_questions": None},
    ]
    applied = {"created": [], "updated": []}

    result = ChatPipeline._collect_open_questions(relevant, applied)
    assert result["Trip"] == ["When?", "Where?"]
    assert result["Meeting"] == ["Who is attending?"]
    assert "No questions" not in result


def test_collect_open_questions_from_applied_changes():
    """_collect_open_questions also picks up questions from newly created Things."""
    from backend.pipeline import ChatPipeline

    relevant = []
    applied = {
        "created": [
            {"id": "new1", "title": "New Task", "open_questions": ["What's the deadline?"]},
        ],
        "updated": [],
    }

    result = ChatPipeline._collect_open_questions(relevant, applied)
    assert result["New Task"] == ["What's the deadline?"]
