"""Tests for payload size limits on Pydantic models (issue #445)."""

import pytest
from pydantic import ValidationError

from backend.models import (
    ChatMessageCreate,
    ChatRequest,
    ConnectionSuggestionAccept,
    MergeRequest,
    MigrateSessionRequest,
    PersonalityPattern,
    RelationshipCreate,
    SweepFindingCreate,
    ThingCreate,
    ThingUpdate,
)


class TestThingCreateLimits:
    def test_title_too_long(self) -> None:
        with pytest.raises(ValidationError, match="string_too_long|max_length"):
            ThingCreate(title="x" * 501)

    def test_type_hint_too_long(self) -> None:
        with pytest.raises(ValidationError, match="string_too_long|max_length"):
            ThingCreate(title="ok", type_hint="x" * 101)

    def test_data_too_large(self) -> None:
        big = {"k": "v" * 200_000}
        with pytest.raises(ValidationError, match="data payload must be under"):
            ThingCreate(title="ok", data=big)

    def test_data_within_limit(self) -> None:
        t = ThingCreate(title="ok", data={"note": "hello"})
        assert t.data == {"note": "hello"}

    def test_open_questions_too_many(self) -> None:
        with pytest.raises(ValidationError, match="at most 100"):
            ThingCreate(title="ok", open_questions=["q"] * 101)

    def test_open_questions_item_too_long(self) -> None:
        with pytest.raises(ValidationError, match="at most 2000"):
            ThingCreate(title="ok", open_questions=["q" * 2001])


class TestThingUpdateLimits:
    def test_title_too_long(self) -> None:
        with pytest.raises(ValidationError, match="string_too_long|max_length"):
            ThingUpdate(title="x" * 501)

    def test_data_too_large(self) -> None:
        big = {"k": "v" * 200_000}
        with pytest.raises(ValidationError, match="data payload must be under"):
            ThingUpdate(data=big)


class TestChatRequestLimits:
    def test_message_too_long(self) -> None:
        with pytest.raises(ValidationError, match="string_too_long|max_length"):
            ChatRequest(session_id="s", message="x" * 10_001)

    def test_session_id_too_long(self) -> None:
        with pytest.raises(ValidationError, match="string_too_long|max_length"):
            ChatRequest(session_id="x" * 201, message="hi")


class TestRelationshipCreateLimits:
    def test_metadata_too_large(self) -> None:
        big = {"k": "v" * 200_000}
        with pytest.raises(ValidationError, match="metadata must be under"):
            RelationshipCreate(from_thing_id="a", to_thing_id="b", relationship_type="rel", metadata=big)


class TestChatMessageCreateLimits:
    def test_content_too_long(self) -> None:
        with pytest.raises(ValidationError, match="string_too_long|max_length"):
            ChatMessageCreate(session_id="s", role="user", content="x" * 100_001)

    def test_session_id_too_long(self) -> None:
        with pytest.raises(ValidationError, match="string_too_long|max_length"):
            ChatMessageCreate(session_id="x" * 201, role="user", content="hi")


class TestMigrateSessionLimits:
    def test_session_ids_too_long(self) -> None:
        with pytest.raises(ValidationError):
            MigrateSessionRequest(old_session_id="x" * 201, new_session_id="ok")


class TestSweepFindingCreateLimits:
    def test_message_too_long(self) -> None:
        with pytest.raises(ValidationError, match="string_too_long|max_length"):
            SweepFindingCreate(finding_type="stale", message="x" * 5001)


class TestPersonalityPatternLimits:
    def test_pattern_too_long(self) -> None:
        with pytest.raises(ValidationError, match="string_too_long|max_length"):
            PersonalityPattern(pattern="x" * 2001)


class TestMergeRequestLimits:
    def test_id_too_long(self) -> None:
        with pytest.raises(ValidationError, match="string_too_long|max_length"):
            MergeRequest(keep_id="x" * 101, remove_id="ok")


class TestConnectionSuggestionAcceptLimits:
    def test_relationship_type_too_long(self) -> None:
        with pytest.raises(ValidationError, match="string_too_long|max_length"):
            ConnectionSuggestionAccept(relationship_type="x" * 101)
