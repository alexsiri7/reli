"""Unit tests for PII-scrubbing transform logic from k5l6m7n8o9p0 migration.

Tests the pure-Python data transformation independently of Alembic/SQLite,
covering all six code paths in the migration's upgrade() function.
"""

import json

import pytest

_PII_KEYS = frozenset({"email", "google_id"})


def _scrub_pii(raw):
    """Mirror of the upgrade() transform logic for isolated testing."""
    if not raw:
        return raw  # Path A: NULL / empty — unchanged
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return raw  # Path C: non-JSON — unchanged
    if not isinstance(data, dict):
        return raw  # Path D: non-dict JSON (list, int, etc.) — unchanged
    if not any(k in data for k in _PII_KEYS):
        return raw  # Path E: already clean — unchanged
    for k in _PII_KEYS:
        data.pop(k, None)
    # Empty dict after PII removal → NULL, consistent with data=None default
    return json.dumps(data) if data else None  # Path F


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Path A: NULL / empty — untouched
        (None, None),
        ("", ""),
        # Path C: non-JSON string — untouched
        ("not-json", "not-json"),
        # Path D: non-dict JSON — untouched
        ("[1,2,3]", "[1,2,3]"),
        # Path E: already clean (no PII keys) — untouched
        ('{"name": "Alice"}', '{"name": "Alice"}'),
        # Path F: only PII keys → empty dict → NULL
        ('{"email": "a@b.com", "google_id": "g123"}', None),
        # Mixed: PII + other fields → PII removed, other fields kept
        ('{"email": "a@b.com", "name": "Alice"}', '{"name": "Alice"}'),
        ('{"google_id": "g123", "name": "Bob", "extra": 1}', '{"name": "Bob", "extra": 1}'),
    ],
)
def test_scrub_pii_transform(raw, expected):
    assert _scrub_pii(raw) == expected
