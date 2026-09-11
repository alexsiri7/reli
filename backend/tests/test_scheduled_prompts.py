"""The three scheduled-task prompts under ``prompts/scheduled/`` (#1413).

The passes are prose run by an external Claude, so this repository cannot prove Claude will follow
them. It can prove four things, and these tests are scoped to exactly those: the files say what
the issue requires, the tool chain a pass follows produces the end state the acceptance criteria
name, the actor filter the learning pass relies on is mechanical rather than a sentence, and the
watchdog's script — run as Actions runs it — flags exactly the heartbeats a missed run leaves.

The content tests assert exact literals against prose, so every literal lives in the tuples at the
top: a wording change fails one obvious place. Two spelling rules make them mechanical — a write's
attribution is always ``actor="..."`` (which separates it from the ``actors=[...]`` read filter),
and a preference scope is always ``scope="..."``.
"""

import json
import re
import shutil
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text

from backend import prompts
from backend.db_models import OBSERVATION_TAG, REJECTED_TAG
from backend.mcp_server import (
    archive_thing,
    create_thing,
    due_for_checkin,
    find_correspondence,
    get_related,
    get_thing_history,
    get_user_model,
    journal_since,
    record_preference,
    update_thing,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS = REPO_ROOT / "prompts" / "scheduled"
WATCHDOG = REPO_ROOT / ".github" / "workflows" / "scheduled-run-health.yml"

RESOLUTION = "resolution-pass.md"
LEARNING = "learning-pass.md"
MORNING = "morning-conversation.md"
FILES = (RESOLUTION, LEARNING, MORNING)

SCHEDULED_TASK_TAG = "#ScheduledTask"
BRIEFING_TAG = "#Briefing"
SCHEDULED = 'actor="claude_scheduled"'
INTERACTIVE = 'actor="claude_interactive"'

HEARTBEAT_TITLES = {RESOLUTION: "Resolution pass", LEARNING: "Learning pass", MORNING: "Morning conversation"}

RESOLUTION_LITERALS = (
    "due_for_checkin",
    "archive_thing",
    "find_correspondence",
    "check_occurred",
    BRIEFING_TAG,
    "#NeedsInput",
    "References",
    "The user never hears about it.",
    "write the union",
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


def test_the_watchdog_reads_the_same_heartbeat_tag_the_prompts_write():
    """A rename in either place would silently kill the missed-run signal."""
    workflow = WATCHDOG.read_text()

    assert f'index("{SCHEDULED_TASK_TAG}")' in workflow
    assert "checkin_date != null" in workflow
    assert "/api/things" in workflow


# --- The watchdog, run as GitHub Actions runs it -------------------------

# The date the stubbed `date` answers, so the fixtures below are fixed rather than wall-clock
# relative and both sides of the `<=` are reachable.
WATCHDOG_TODAY = "2026-09-11"
TOMORROW = "2026-09-12"
WATCHDOG_TOOLS = ("bash", "jq", "paste")
HEARTBEAT_ISSUE_TITLES = {
    "absent": "Scheduled pass missed — a heartbeat is absent",
    "due": "Scheduled pass missed — a heartbeat is still due",
}


def _heartbeat(title: str, checkin_date: str | None) -> dict:
    return {"id": str(uuid.uuid4()), "title": title, "tags": [SCHEDULED_TASK_TAG], "checkin_date": checkin_date}


def _heartbeats(
    resolution: str | None = TOMORROW, learning: str | None = TOMORROW, morning: str | None = TOMORROW
) -> list[dict]:
    return [
        _heartbeat(HEARTBEAT_TITLES[RESOLUTION], resolution),
        _heartbeat(HEARTBEAT_TITLES[LEARNING], learning),
        _heartbeat(HEARTBEAT_TITLES[MORNING], morning),
    ]


def _watchdog_script() -> str:
    workflow = yaml.safe_load(WATCHDOG.read_text())
    (step,) = workflow["jobs"]["check-heartbeats"]["steps"]
    return step["run"]


def _run_watchdog(
    tmp_path: Path, things: list[dict], *, gh_fails: bool = False
) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run the step's script under the shell Actions gives a `run:` step, on a PATH holding its
    genuine externals plus stubs: `curl` serves `things` as `/api/things` and logs an ntfy post,
    `gh` logs every call and prints no open issue, `date` answers `WATCHDOG_TODAY`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in WATCHDOG_TOOLS:
        real = shutil.which(tool)
        assert real, f"{tool} is not installed; the watchdog needs it"
        (bin_dir / tool).symlink_to(real)
    body = tmp_path / "things.json"
    body.write_text(json.dumps({"things": things}))
    log = tmp_path / "calls.log"
    stubs = {
        "date": f'echo "{WATCHDOG_TODAY}"\n',
        "curl": (
            f'case "$*" in *"/api/things"*) printf "%s" "$(< "{body}")" ;; '
            f'*ntfy.sh/*) echo "curl $*" >> "{log}" ;; *) exit 22 ;; esac\n'
        ),
        "gh": f'echo "gh $*" >> "{log}"\nexit {1 if gh_fails else 0}\n',
    }
    for name, script in stubs.items():
        stub = bin_dir / name
        stub.write_text("#!/usr/bin/env bash\n" + script)
        stub.chmod(0o755)
    env = {
        "PATH": str(bin_dir),
        "WEB_UI_PASSWORD": "secret",
        "RAILWAY_PRODUCTION_URL": "https://reli.example",
        "NTFY_TOPIC": "reli-test",
        "GH_TOKEN": "stub",
    }
    result = subprocess.run(
        [str(bin_dir / "bash"), "--noprofile", "--norc", "-eo", "pipefail", "-c", _watchdog_script()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls


def _issues_created(calls: list[str]) -> list[str]:
    return [call for call in calls if call.startswith("gh issue create ")]


def _notifications(calls: list[str]) -> list[str]:
    return [call for call in calls if call.startswith("curl ")]


def test_the_watchdog_is_quiet_when_every_heartbeat_was_pushed_past_today(tmp_path):
    """Only #ScheduledTask Things count: an ordinary Thing due today is a check-in, not a missed run."""
    checkin = {
        "id": str(uuid.uuid4()),
        "title": "Confirm the dentist appointment",
        "tags": [],
        "checkin_date": WATCHDOG_TODAY,
    }
    things = [*_heartbeats(), checkin]

    result, calls = _run_watchdog(tmp_path, things)

    assert result.returncode == 0, result.stderr
    assert "All 3 scheduled passes have run since yesterday." in result.stdout
    assert calls == []


@pytest.mark.parametrize("still_due", (WATCHDOG_TODAY, "2026-09-10"))
def test_the_watchdog_names_the_heartbeat_still_due_today_or_earlier(tmp_path, still_due):
    result, calls = _run_watchdog(tmp_path, _heartbeats(learning=still_due))

    assert result.returncode == 1
    message = f"Still due on {WATCHDOG_TODAY}, so the last run did not complete: Learning pass."
    (issue,) = _issues_created(calls)
    assert f"--title {HEARTBEAT_ISSUE_TITLES['due']}" in issue
    assert message in issue
    (notification,) = _notifications(calls)
    assert message in notification


def test_the_watchdog_lists_every_heartbeat_still_due(tmp_path):
    result, calls = _run_watchdog(tmp_path, _heartbeats(resolution=WATCHDOG_TODAY, learning=WATCHDOG_TODAY))

    assert result.returncode == 1
    (issue,) = _issues_created(calls)
    assert "did not complete: Resolution pass,Learning pass." in issue


def test_the_watchdog_does_not_flag_a_heartbeat_without_a_date(tmp_path):
    """In jq, null <= a string is true; the guard keeps a dateless heartbeat from reading as due."""
    result, calls = _run_watchdog(tmp_path, _heartbeats(resolution=None, learning=None, morning=None))

    assert result.returncode == 0, result.stderr
    assert calls == []


def test_the_watchdog_counts_the_heartbeats_before_it_reads_their_dates(tmp_path):
    result, calls = _run_watchdog(tmp_path, _heartbeats(learning=WATCHDOG_TODAY)[:2])

    assert result.returncode == 1
    message = "Only 2 of the three #ScheduledTask heartbeats exist: a pass has never run."
    (issue,) = _issues_created(calls)
    assert f"--title {HEARTBEAT_ISSUE_TITLES['absent']}" in issue
    assert message in issue
    (notification,) = _notifications(calls)
    assert message in notification


def test_a_missed_run_is_notified_even_when_filing_the_issue_fails(tmp_path):
    """The step runs under `-e`, so a failing `gh` aborts whatever comes after it. The ntfy ping is
    the time-sensitive channel and must not depend on the issue."""
    result, calls = _run_watchdog(tmp_path, _heartbeats(resolution=WATCHDOG_TODAY), gh_fails=True)

    assert result.returncode != 0
    (notification,) = _notifications(calls)
    assert "did not complete: Resolution pass." in notification


# --- The acceptance scenarios, as the tool calls a pass makes ------------


def _newest_journal_id(session):
    return session.execute(text("SELECT coalesce(max(id), 0) FROM journal")).scalar_one()


def test_a_checkin_settled_from_gmail_is_archived_without_a_briefing_entry(tools, google):
    """Criterion 2: the Thing is archived by claude_scheduled and the briefing never mentions it."""
    today = datetime.now(UTC).date()
    thing = create_thing(actor="claude_interactive", title="Confirm the dentist appointment", checkin_date=today)

    assert thing["id"] in {due["id"] for due in due_for_checkin()}
    found = find_correspondence("dentist appointment", since=today - timedelta(days=7))
    assert any(message["subject"] == "Appointment confirmed" for message in found)

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
