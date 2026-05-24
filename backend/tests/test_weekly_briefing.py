"""Tests for weekly_briefing helpers."""

import pytest

from backend.models import WeeklyBriefingItem
from backend.weekly_briefing import _urgency_sort_key


def _make_item(detail: str | None = None) -> WeeklyBriefingItem:
    return WeeklyBriefingItem(thing_id="t1", title="X", detail=detail)


class TestUrgencySortKey:
    """Verify _urgency_sort_key handles all detail string formats without crashing."""

    @pytest.mark.parametrize(
        "detail,expected",
        [
            ("Check-in due today", 0),
            ("Deadline today", 0),
            ("Deadline in 1d", 1),
            ("Deadline in 3d", 3),
            ("Birthday in 7d", 7),
            ("Check-in in 3d", 3),
            ("Check-in tomorrow", 1),  # regression: contains "in " but is not urgency pattern
            ("Check-in due tomorrow", 1),
            (None, 1),
        ],
    )
    def test_sort_key_values(self, detail: str | None, expected: int):
        assert _urgency_sort_key(_make_item(detail)) == expected

    def test_sort_order(self):
        """Items sort: today first, then by ascending days, then default last."""
        items = [
            _make_item("Birthday in 5d"),
            _make_item("Deadline in 2d"),
            _make_item("Check-in due today"),
        ]
        items.sort(key=_urgency_sort_key)
        assert [i.detail for i in items] == [
            "Check-in due today",
            "Deadline in 2d",
            "Birthday in 5d",
        ]
