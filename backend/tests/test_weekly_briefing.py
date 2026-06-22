"""Tests for weekly_briefing helpers."""

import json
import logging
import uuid
from datetime import date, timedelta

import pytest
from sqlmodel import Session

import backend.db_engine as engine_mod
from backend.db_models import ThingRecord
from backend.models import WeeklyBriefingItem
from backend.weekly_briefing import MAX_THINGS_PER_BRIEFING, _urgency_sort_key, generate_weekly_briefing


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


class TestWeeklyBriefingLimit:
    def test_generate_weekly_briefing_limits_things_loaded(self, patched_db):
        """Regression: weekly briefing must not load more than MAX_THINGS_PER_BRIEFING Things."""
        over_limit = MAX_THINGS_PER_BRIEFING + 50
        # Give every record a deadline within 7 days so active_rows feeds upcoming (1 entry per thing).
        soon = (date.today() + timedelta(days=3)).isoformat()

        with Session(engine_mod.engine) as session:
            for i in range(over_limit):
                session.add(
                    ThingRecord(
                        id=str(uuid.uuid4()),
                        title=f"Thing {i}",
                        active=True,
                        data=json.dumps({"deadline": soon}),
                    )
                )
            session.commit()

        # Should not OOM or raise — limit must have been applied at the query level
        result = generate_weekly_briefing(user_id="")
        # upcoming is populated 1-to-1 from active_rows (one deadline per thing via `break`).
        # Without the .limit() cap, len(upcoming) would approach over_limit.
        # With the cap applied it must be <= MAX_THINGS_PER_BRIEFING.
        assert len(result.upcoming) <= MAX_THINGS_PER_BRIEFING

    def test_warning_emitted_when_capped(self, patched_db, caplog):
        """Warning is logged when active Things reach the cap."""
        with Session(engine_mod.engine) as session:
            for i in range(MAX_THINGS_PER_BRIEFING):
                session.add(ThingRecord(id=str(uuid.uuid4()), title=f"T{i}", active=True))
            session.commit()

        with caplog.at_level(logging.WARNING, logger="backend.weekly_briefing"):
            generate_weekly_briefing(user_id="")

        assert any("capped at" in r.message for r in caplog.records)
