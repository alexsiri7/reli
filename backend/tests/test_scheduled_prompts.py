"""The three scheduled-task prompts under ``prompts/scheduled/`` (#1413).

The passes are prose run by an external Claude, so this repository cannot prove Claude will follow
them. It can prove three things, and these tests are scoped to exactly those: the files say what
the issue requires, the tool chain a pass follows produces the end state the acceptance criteria
name, and the actor filter the learning pass relies on is mechanical rather than a sentence.

The content tests assert exact literals against prose, so every literal lives in the tuples at the
top: a wording change fails one obvious place. Two spelling rules make them mechanical — a write's
attribution is always ``actor="..."`` (which separates it from the ``actors=[...]`` read filter),
and a preference scope is always ``scope="..."``.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from backend import db_models, prompts
from backend.db_models import OBSERVATION_TAG, REJECTED_TAG
from backend.mcp_server import (
    archive_thing,
    create_thing,
    due_for_checkin,
    get_related,
    get_thing_history,
    get_user_model,
    journal_since,
    record_preference,
    update_thing,
)
from backend.tests.conftest import RETIRED_GOOGLE_TOOL_NAMES

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS = REPO_ROOT / "prompts" / "scheduled"

RESOLUTION = "resolution-pass.md"
LEARNING = "learning-pass.md"
MORNING = "morning-conversation.md"
FILES = (RESOLUTION, LEARNING, MORNING)

SCHEDULED_TASK_TAG = "#ScheduledTask"
BRIEFING_TAG = "#Briefing"
SCHEDULED = 'actor="claude_scheduled"'
INTERACTIVE = 'actor="claude_interactive"'

HEARTBEAT_TITLES = {RESOLUTION: "Resolution pass", LEARNING: "Learning pass", MORNING: "Morning conversation"}

# Pinned on its own: the convention below is carried verbatim, which proves a file matches the
# constant but not that this clause survives a reword of it.
CHECKIN_FALLBACK = "when you cannot tell, the check-in is not resolved"

RESOLUTION_LITERALS = (
    "due_for_checkin",
    "archive_thing",
    "needs_input()",
    BRIEFING_TAG,
    "#NeedsInput",
    "References",
    "The user never hears about it.",
    "write the union",
    "expected to be attached to this scheduled task",
    "record the missing connectors",
    "paging an inbox into context",
    "never sends mail",
    "goes to `unresolved`",
    CHECKIN_FALLBACK,
)
LEARNING_LITERALS = (
    "journal_since",
    'actors=["user", "claude_interactive"]',
    "get_user_model(include_rejected=true)",
    BRIEFING_TAG,
    REJECTED_TAG,
    OBSERVATION_TAG,
    "journal_entry_id",
    "journal_watermark",
    "add_preference_evidence",
    "record_preference",
    "One entry is not a pattern.",
)
MORNING_LITERALS = (
    f'get_user_model(scope="{prompts.SCHEDULING_SCOPE}")',
    f"reli://user-model/{prompts.SCHEDULING_SCOPE}",
    BRIEFING_TAG,
    OBSERVATION_TAG,
    "reject_preference",
    "did not complete last night",
    "A morning chat that only reports is a notification with extra steps.",
    "every write that encodes something the user said",
    CHECKIN_FALLBACK,
)
SCOPE_ARGUMENT = re.compile(r'scope="([a-z]+)"')
SCOPES = {prompts.CAPTURE_SCOPE, prompts.SCHEDULING_SCOPE, prompts.PLANNING_SCOPE, prompts.REVIEW_SCOPE}


def _text(name):
    return (PROMPTS / name).read_text()


# --- The files -------------------------------------------------------------


@pytest.mark.parametrize("name", FILES)
def test_the_three_prompt_files_exist_and_are_not_empty(name):
    assert _text(name).strip()
    assert _text(name).startswith("# ")


@pytest.mark.parametrize("name", FILES)
@pytest.mark.parametrize("tool", RETIRED_GOOGLE_TOOL_NAMES)
def test_no_pass_reaches_for_a_reli_google_tool(name, tool):
    """#1487: a pass looks through the connectors attached to its own session."""
    assert tool not in _text(name)


def test_the_resolution_pass_carries_the_checkin_semantics_verbatim():
    assert prompts.CHECKIN_SEMANTICS in _text(RESOLUTION)


def test_the_morning_conversation_carries_both_conventions_verbatim():
    text = _text(MORNING)

    assert prompts.PREFERENCE_CAPTURE_CONVENTION in text
    assert prompts.CHECKIN_SEMANTICS in text


@pytest.mark.parametrize("name", (RESOLUTION, LEARNING))
def test_the_overnight_passes_write_as_claude_scheduled_only(name):
    """A bare ``claude_interactive`` check would fail a correct learning pass, which names it in
    the ``actors=`` read filter; the ``actor=`` prefix is what marks a write."""
    text = _text(name)

    assert SCHEDULED in text
    assert INTERACTIVE not in text


def test_the_morning_conversation_splits_its_actors():
    text = _text(MORNING)

    assert SCHEDULED in text
    assert INTERACTIVE in text
    assert "your own bookkeeping" in text


@pytest.mark.parametrize("literal", RESOLUTION_LITERALS)
def test_the_resolution_pass_settles_before_it_briefs(literal):
    assert literal in _text(RESOLUTION)


@pytest.mark.parametrize("literal", LEARNING_LITERALS)
def test_the_learning_pass_reads_the_journal_by_actor_and_checks_rejections(literal):
    assert literal in _text(LEARNING)


def test_the_learning_pass_records_only_under_the_scopes_the_prompts_load():
    named = set(SCOPE_ARGUMENT.findall(_text(LEARNING)))

    assert named
    assert named <= SCOPES


@pytest.mark.parametrize("literal", MORNING_LITERALS)
def test_the_morning_conversation_presents_and_writes_back(literal):
    assert literal in _text(MORNING)


@pytest.mark.parametrize("name", FILES)
def test_every_task_maintains_its_heartbeat(name):
    text = _text(name)

    assert SCHEDULED_TASK_TAG in text
    assert f"`{HEARTBEAT_TITLES[name]}`" in text
    assert "tomorrow" in text


def test_the_prompts_write_the_heartbeat_tag_the_module_defines():
    """The literal asserted against the prose above must be the one constant the code holds.

    A rename in only one place would silently kill the missed-run signal: the passes would tag
    their heartbeats one way and ``due_for_checkin`` would surface them by another.
    """
    assert SCHEDULED_TASK_TAG == db_models.SCHEDULED_TASK_TAG


# --- The acceptance scenarios, as the tool calls a pass makes ------------


def _newest_journal_id(session):
    return session.execute(text("SELECT coalesce(max(id), 0) FROM journal")).scalar_one()


def test_a_checkin_the_pass_settled_is_archived_without_a_briefing_entry(tools):
    """Criterion 2: the Thing is archived by claude_scheduled and the briefing never mentions it.

    The lookup that settles it happens in the session's own Gmail and Calendar (#1487), so it is
    not a tool call this repository can make. What remains here is the graph side.
    """
    today = datetime.now(UTC).date()
    thing = create_thing(actor="claude_interactive", title="Confirm the dentist appointment", checkin_date=today)

    assert thing["id"] in {due["id"] for due in due_for_checkin()}

    archived = archive_thing(actor="claude_scheduled", thing_id=uuid.UUID(thing["id"]))
    briefing = create_thing(
        actor="claude_scheduled",
        title=f"Briefing for {today.isoformat()}",
        tags=[BRIEFING_TAG],
        checkin_date=today,
        notes={"unresolved": "", "decisions": ""},
    )

    assert archived["active"] is False
    settled = get_thing_history(uuid.UUID(thing["id"]))["entries"][-1]
    assert (settled["actor"], settled["after"]["active"]) == ("claude_scheduled", False)
    assert thing["id"] not in {due["id"] for due in due_for_checkin()}
    assert all(thing["title"] not in note and thing["id"] not in note for note in briefing["notes"].values())
    assert get_related(uuid.UUID(briefing["id"])) == []


def test_the_learning_pass_input_never_contains_claudes_own_scheduled_edits(tools):
    """Criterion 3: a check-in date claude_scheduled moved is not in the window, and the one the
    user moved in conversation becomes evidence the usual way."""
    today = datetime.now(UTC).date()
    by_claude = create_thing(actor="claude_interactive", title="moved by the resolution pass", checkin_date=today)
    by_user = create_thing(actor="claude_interactive", title="moved in conversation", checkin_date=today)
    watermark = _newest_journal_id(tools)
    update_thing(actor="claude_scheduled", thing_id=uuid.UUID(by_claude["id"]), checkin_date=today + timedelta(days=1))
    update_thing(actor="claude_interactive", thing_id=uuid.UUID(by_user["id"]), checkin_date=today + timedelta(days=1))

    window = journal_since(after_id=watermark, actors=["user", "claude_interactive"])

    assert [(e["actor"], e["entity_id"]) for e in window["entries"]] == [("claude_interactive", by_user["id"])]
    assert window["truncated"] is False
    (moved,) = window["entries"]
    assert moved["before"]["checkin_date"] != moved["after"]["checkin_date"]

    observation = create_thing(
        actor="claude_scheduled",
        title="Pushed a check-in by a day in conversation",
        tags=[OBSERVATION_TAG],
        notes={"journal_entry_id": str(moved["id"])},
    )
    recorded = record_preference(
        actor="claude_scheduled",
        title="Pushes check-ins a day at a time",
        scope=prompts.SCHEDULING_SCOPE,
        evidence_ids=[uuid.UUID(observation["id"])],
    )

    assert recorded["evidence_count"] == 1
    model = get_user_model(scope=prompts.SCHEDULING_SCOPE)["preferences"]
    assert [preference["thing"]["id"] for preference in model] == [recorded["thing"]["id"]]
