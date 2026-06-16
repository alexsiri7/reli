"""Tests for _thing_for_llm field allowlist."""

from backend.pipeline import _LLM_THING_FIELDS, _thing_for_llm


class TestThingForLlm:
    def test_excludes_user_id(self):
        """user_id must never be sent to external LLM providers."""
        thing = {"id": "t1", "title": "Alice", "user_id": "u99", "type_hint": "person"}
        result = _thing_for_llm(thing)
        assert "user_id" not in result

    def test_excludes_internal_fields(self):
        """Internal metadata fields must be excluded."""
        thing = {
            "id": "t1",
            "title": "Note",
            "embedding_updated_at": "2026-01-01",
            "created_at": "2026-01-01",
            "updated_at": "2026-01-01",
            "data": {"secret": "value"},
        }
        result = _thing_for_llm(thing)
        assert "embedding_updated_at" not in result
        assert "created_at" not in result
        assert "updated_at" not in result
        assert "data" not in result

    def test_includes_user_facing_fields(self):
        """All fields in _LLM_THING_FIELDS should pass through."""
        thing = {k: f"val-{k}" for k in _LLM_THING_FIELDS}
        # Add some extra fields that should be stripped
        thing["data"] = {"internal": True}
        thing["user_id"] = "u1"
        result = _thing_for_llm(thing)
        for field in _LLM_THING_FIELDS:
            assert field in result, f"Expected {field} in result"
        assert len(result) == len(_LLM_THING_FIELDS)
