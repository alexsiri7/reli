"""Tests for the _assert_safe_columns SQL injection guard."""

import pytest

from backend.agents import _THINGS_UPDATABLE_COLUMNS, _assert_safe_columns


class TestAssertSafeColumns:
    def test_rejects_injection_attempt(self):
        """SQL injection payloads in column names must be rejected."""
        with pytest.raises(ValueError, match="SQL injection guard"):
            _assert_safe_columns({"'; DROP TABLE things; --": "v"})

    def test_rejects_unknown_column(self):
        """Columns not in the allowlist must be rejected."""
        with pytest.raises(ValueError, match="SQL injection guard"):
            _assert_safe_columns({"user_id": 1})

    def test_accepts_all_valid_columns(self):
        """Every column in _THINGS_UPDATABLE_COLUMNS should be accepted."""
        fields = {col: "test" for col in _THINGS_UPDATABLE_COLUMNS}
        _assert_safe_columns(fields)  # should not raise
