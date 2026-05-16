"""Tests for get_preferences and update_preference — tools layer (real DB) and MCP wrappers."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session

import backend.db_engine as _engine_mod
from backend.db_models import ThingRecord
from backend.mcp_server import get_preferences, update_preference
from backend.tools import get_preferences as tools_get_preferences
from backend.tools import update_preference as tools_update_preference


# ---------------------------------------------------------------------------
# tools.py unit tests (hit real temp DB)
# ---------------------------------------------------------------------------


class TestGetPreferencesTools:
    def test_returns_empty_list_when_no_preferences(self, patched_db) -> None:
        result = tools_get_preferences(user_id="u1")
        assert result == []

    def test_returns_only_active_preferences(self, patched_db) -> None:
        now = datetime.now(timezone.utc)
        with Session(_engine_mod.engine) as session:
            # Active preference
            session.add(
                ThingRecord(
                    id="pref1",
                    title="Communication style",
                    type_hint="preference",
                    active=True,
                    user_id="u1",
                    created_at=now,
                    updated_at=now,
                    data={"patterns": [{"pattern": "Be concise", "confidence": "strong", "observations": 5}]},
                )
            )
            # Inactive preference (should not appear)
            session.add(
                ThingRecord(
                    id="pref2",
                    title="Old preference",
                    type_hint="preference",
                    active=False,
                    user_id="u1",
                    created_at=now,
                    updated_at=now,
                    data={},
                )
            )
            # Non-preference thing (should not appear)
            session.add(
                ThingRecord(
                    id="task1",
                    title="Buy milk",
                    type_hint="task",
                    active=True,
                    user_id="u1",
                    created_at=now,
                    updated_at=now,
                    data={},
                )
            )
            session.commit()

        result = tools_get_preferences(user_id="u1")
        assert len(result) == 1
        assert result[0]["id"] == "pref1"
        assert result[0]["type_hint"] == "preference"


class TestUpdatePreferenceTools:
    def _create_preference(self, thing_id="pref1", user_id="u1", data=None):
        now = datetime.now(timezone.utc)
        with Session(_engine_mod.engine) as session:
            session.add(
                ThingRecord(
                    id=thing_id,
                    title="Comm style",
                    type_hint="preference",
                    active=True,
                    user_id=user_id,
                    created_at=now,
                    updated_at=now,
                    data=data or {"other_key": "preserved"},
                )
            )
            session.commit()

    def test_valid_update(self, patched_db) -> None:
        self._create_preference()
        patterns = [{"pattern": "Be concise", "confidence": "strong", "observations": 5}]
        result = tools_update_preference(
            thing_id="pref1",
            patterns_json=json.dumps(patterns),
            user_id="u1",
        )
        assert "error" not in result
        assert result["data"]["patterns"] == patterns
        # Other keys preserved
        assert result["data"]["other_key"] == "preserved"

    def test_invalid_confidence(self, patched_db) -> None:
        self._create_preference()
        patterns = [{"pattern": "Be concise", "confidence": "unknown", "observations": 3}]
        result = tools_update_preference(
            thing_id="pref1",
            patterns_json=json.dumps(patterns),
            user_id="u1",
        )
        assert "error" in result
        assert "confidence" in result["error"]

    def test_wrong_type_hint(self, patched_db) -> None:
        now = datetime.now(timezone.utc)
        with Session(_engine_mod.engine) as session:
            session.add(
                ThingRecord(
                    id="task1",
                    title="A task",
                    type_hint="task",
                    active=True,
                    user_id="u1",
                    created_at=now,
                    updated_at=now,
                    data={},
                )
            )
            session.commit()

        patterns = [{"pattern": "Be concise", "confidence": "strong", "observations": 3}]
        result = tools_update_preference(
            thing_id="task1",
            patterns_json=json.dumps(patterns),
            user_id="u1",
        )
        assert "error" in result
        assert "not a preference" in result["error"]

    def test_empty_thing_id(self, patched_db) -> None:
        result = tools_update_preference(thing_id="  ", patterns_json="[]", user_id="u1")
        assert result == {"error": "thing_id is required"}

    def test_observations_must_be_positive(self, patched_db) -> None:
        self._create_preference()
        patterns = [{"pattern": "Be concise", "confidence": "strong", "observations": 0}]
        result = tools_update_preference(
            thing_id="pref1",
            patterns_json=json.dumps(patterns),
            user_id="u1",
        )
        assert "error" in result
        assert "observations" in result["error"]

    def test_accepts_established_confidence(self, patched_db) -> None:
        self._create_preference()
        patterns = [{"pattern": "Be concise", "confidence": "established", "observations": 3}]
        result = tools_update_preference(
            thing_id="pref1",
            patterns_json=json.dumps(patterns),
            user_id="u1",
        )
        assert "error" not in result

    def test_thing_not_found(self, patched_db) -> None:
        patterns = [{"pattern": "Be concise", "confidence": "strong", "observations": 3}]
        result = tools_update_preference(
            thing_id="does-not-exist",
            patterns_json=json.dumps(patterns),
            user_id="u1",
        )
        assert "error" in result
        assert "not found" in result["error"]

    def test_boolean_observations_rejected(self, patched_db) -> None:
        self._create_preference()
        # Python bool is a subclass of int; True must be rejected
        patterns = [{"pattern": "Be concise", "confidence": "strong", "observations": True}]
        result = tools_update_preference(
            thing_id="pref1",
            patterns_json=json.dumps(patterns),
            user_id="u1",
        )
        assert "error" in result
        assert "observations" in result["error"]

    def test_inactive_thing_returns_error(self, patched_db) -> None:
        now = datetime.now(timezone.utc)
        with Session(_engine_mod.engine) as session:
            session.add(
                ThingRecord(
                    id="pref_inactive",
                    title="Old",
                    type_hint="preference",
                    active=False,
                    user_id="u1",
                    created_at=now,
                    updated_at=now,
                    data={},
                )
            )
            session.commit()

        patterns = [{"pattern": "Be concise", "confidence": "strong", "observations": 3}]
        result = tools_update_preference(
            thing_id="pref_inactive",
            patterns_json=json.dumps(patterns),
            user_id="u1",
        )
        assert "error" in result
        assert "not active" in result["error"]


# ---------------------------------------------------------------------------
# MCP wrapper tests (mock shared_tools)
# ---------------------------------------------------------------------------


class TestGetPreferencesMCP:
    @patch("backend.mcp_server.shared_tools.get_preferences")
    def test_delegates_to_shared_tools(self, mock_get: MagicMock) -> None:
        mock_get.return_value = [{"id": "p1", "title": "Comm style", "type_hint": "preference"}]
        result = get_preferences()
        mock_get.assert_called_once_with(user_id="")
        assert len(result) == 1
        assert result[0]["id"] == "p1"

    @patch("backend.mcp_server.shared_tools.get_preferences")
    def test_empty_list(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        result = get_preferences()
        assert result == []


class TestUpdatePreferenceMCP:
    @patch("backend.mcp_server.shared_tools.update_preference")
    def test_delegates_to_shared_tools(self, mock_update: MagicMock) -> None:
        mock_update.return_value = {"id": "p1", "data": {"patterns": [{"pattern": "X", "confidence": "strong", "observations": 3}]}}
        patterns = [{"pattern": "X", "confidence": "strong", "observations": 3}]
        result = update_preference(thing_id="p1", patterns=patterns)
        mock_update.assert_called_once_with(
            thing_id="p1",
            patterns_json=json.dumps(patterns),
            user_id="",
        )
        assert result["id"] == "p1"

    @patch("backend.mcp_server.shared_tools.update_preference")
    def test_error_passthrough(self, mock_update: MagicMock) -> None:
        mock_update.return_value = {"error": "Thing p1 not found"}
        result = update_preference(thing_id="p1", patterns=[])
        assert "error" in result


# ---------------------------------------------------------------------------
# Cross-user isolation tests
# ---------------------------------------------------------------------------


class TestUpdatePreferenceIsolation:
    def test_other_user_cannot_update(self, patched_db) -> None:
        now = datetime.now(timezone.utc)
        with Session(_engine_mod.engine) as session:
            session.add(
                ThingRecord(
                    id="pref_owned",
                    title="Comm style",
                    type_hint="preference",
                    active=True,
                    user_id="user-a",
                    created_at=now,
                    updated_at=now,
                    data={},
                )
            )
            session.commit()

        patterns = [{"pattern": "Be concise", "confidence": "strong", "observations": 3}]
        result = tools_update_preference(
            thing_id="pref_owned",
            patterns_json=json.dumps(patterns),
            user_id="user-b",
        )
        assert result == {"error": "Unauthorized"}

    def test_empty_user_id_bypasses_check(self, patched_db) -> None:
        now = datetime.now(timezone.utc)
        with Session(_engine_mod.engine) as session:
            session.add(
                ThingRecord(
                    id="pref_sys",
                    title="Comm style",
                    type_hint="preference",
                    active=True,
                    user_id="user-a",
                    created_at=now,
                    updated_at=now,
                    data={},
                )
            )
            session.commit()

        patterns = [{"pattern": "Be concise", "confidence": "strong", "observations": 3}]
        result = tools_update_preference(
            thing_id="pref_sys",
            patterns_json=json.dumps(patterns),
            user_id="",
        )
        assert "error" not in result
