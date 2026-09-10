"""The MCP surface: what it exposes, what it refuses, and what it writes to the journal.

The tools are called directly — ``@reli_mcp.tool()`` returns the function unchanged and registers
it as a side effect — with ``_session`` bound to the fixture session so a tool's write and the
assertion about it share one transaction. The two transport tests go through the real app instead,
because auth and the mount are properties of the ASGI stack and not of the functions.
"""

import asyncio
import json
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import get_args

import pytest
from sqlalchemy import text

from backend import mcp_server
from backend.config import settings
from backend.db_models import RelationshipType
from backend.mcp_server import (
    McpActor,
    archive_thing,
    blocked,
    children,
    create_thing,
    due_for_checkin,
    find_things,
    get_related,
    get_thing,
    get_thing_history,
    relate,
    reli_mcp,
    stale,
    unrelate,
    update_thing,
)
from backend.service import ThingNotFound

TOOL_NAMES = {
    "create_thing",
    "update_thing",
    "archive_thing",
    "relate",
    "unrelate",
    "get_thing",
    "find_things",
    "get_related",
    "due_for_checkin",
    "stale",
    "blocked",
    "children",
    "get_thing_history",
}

WRITING_TOOLS = {"create_thing", "update_thing", "archive_thing", "relate", "unrelate"}


@pytest.fixture()
def tools(session, monkeypatch):
    """Bind every tool to the fixture session for the duration of one test."""

    @contextmanager
    def _fixture_session():
        yield session

    monkeypatch.setattr(mcp_server, "_session", _fixture_session)
    return session


def _journal_count(session):
    return session.execute(text("SELECT count(*) FROM journal")).scalar_one()


def _entries_since(session, count_before):
    return session.execute(
        text("SELECT actor, operation, entity_type, entity_id FROM journal ORDER BY id OFFSET :n"),
        {"n": count_before},
    ).all()


def _tool_schemas():
    return {tool.name: tool.inputSchema for tool in asyncio.run(reli_mcp.list_tools())}


# --- The surface -----------------------------------------------------------


def test_the_exposed_tools_are_exactly_the_thirteen():
    assert set(_tool_schemas()) == TOOL_NAMES


def test_hard_delete_is_not_exposed():
    """#1409: there is no hard delete via MCP. service.delete_thing stays in-process only."""
    assert "delete_thing" not in _tool_schemas()


@pytest.mark.parametrize("tool_name", sorted(WRITING_TOOLS))
def test_every_writing_tool_requires_an_actor(tool_name):
    """No default means argument validation rejects a write before any tool body runs."""
    schema = _tool_schemas()[tool_name]

    assert "actor" in schema["required"]
    assert schema["properties"]["actor"]["enum"] == [actor.value for actor in get_args(McpActor)]


# --- Writes and their journal entries --------------------------------------


def test_create_thing_journals_the_actor_it_was_given(tools):
    before = _journal_count(tools)

    thing = create_thing(actor="claude_scheduled", title="scheduled write", tags=["auto"])

    entries = _entries_since(tools, before)
    assert len(entries) == 1
    assert entries[0].actor == "claude_scheduled"
    assert entries[0].operation == "create"
    assert entries[0].entity_id == uuid.UUID(thing["id"])
    assert thing["tags"] == ["auto"]
    assert json.loads(json.dumps(thing))["title"] == "scheduled write"


def test_update_thing_journals_an_update_by_the_interactive_actor(tools):
    thing = create_thing(actor="claude_scheduled", title="original")
    before = _journal_count(tools)

    updated = update_thing(actor="claude_interactive", thing_id=uuid.UUID(thing["id"]), title="renamed")

    entries = _entries_since(tools, before)
    assert [(e.actor, e.operation) for e in entries] == [("claude_interactive", "update")]
    assert updated["title"] == "renamed"


def test_update_thing_replaces_collections_rather_than_merging(tools):
    """The #337 regression: passing tags writes exactly that list, and drops the rest."""
    thing = create_thing(actor="claude_interactive", title="t", tags=["a", "b"], notes={"one": "first"})

    updated = update_thing(
        actor="claude_interactive",
        thing_id=uuid.UUID(thing["id"]),
        tags=["c"],
        notes={"two": "second"},
    )

    assert updated["tags"] == ["c"]
    assert updated["notes"] == {"two": "second"}


def test_archive_thing_deactivates_without_deleting(tools):
    thing = create_thing(actor="claude_interactive", title="done with this")
    before = _journal_count(tools)

    archived = archive_thing(actor="claude_interactive", thing_id=uuid.UUID(thing["id"]))

    assert archived["active"] is False
    assert [(e.actor, e.operation) for e in _entries_since(tools, before)] == [("claude_interactive", "update")]
    assert get_thing(uuid.UUID(thing["id"]))["thing"]["active"] is False


def test_relate_and_unrelate_journal_the_edge(tools):
    source = create_thing(actor="claude_interactive", title="parent")
    target = create_thing(actor="claude_interactive", title="child")
    before = _journal_count(tools)

    edge = relate(
        actor="claude_interactive",
        source_thing_id=uuid.UUID(source["id"]),
        target_thing_id=uuid.UUID(target["id"]),
        relationship_type=RelationshipType.CHILD_OF,
        context="because",
    )
    removed = unrelate(actor="claude_scheduled", relationship_id=uuid.UUID(edge["id"]))

    entries = _entries_since(tools, before)
    assert [(e.actor, e.operation, e.entity_id) for e in entries] == [
        ("claude_interactive", "relate", uuid.UUID(edge["id"])),
        ("claude_scheduled", "unrelate", uuid.UUID(edge["id"])),
    ]
    assert removed == {"unrelated": edge["id"]}


def test_update_thing_on_an_unknown_id_raises(tools):
    with pytest.raises(ThingNotFound):
        update_thing(actor="claude_interactive", thing_id=uuid.uuid4(), title="nobody")


# --- Reads -----------------------------------------------------------------


def test_get_thing_returns_edges_in_both_directions_with_the_id_unrelate_takes(tools):
    thing = create_thing(actor="claude_interactive", title="middle")
    other = create_thing(actor="claude_interactive", title="other")
    relate(
        actor="claude_interactive",
        source_thing_id=uuid.UUID(other["id"]),
        target_thing_id=uuid.UUID(thing["id"]),
        relationship_type=RelationshipType.BLOCKS,
    )

    found = get_thing(uuid.UUID(thing["id"]))

    assert found["thing"]["title"] == "middle"
    assert len(found["relationships"]) == 1
    unrelate(actor="claude_interactive", relationship_id=uuid.UUID(found["relationships"][0]["id"]))
    assert get_thing(uuid.UUID(thing["id"]))["relationships"] == []


def test_get_thing_on_an_unknown_id_raises(tools):
    with pytest.raises(ThingNotFound):
        get_thing(uuid.uuid4())


def test_find_things_filters_and_returns_json_safe_dicts(tools):
    create_thing(actor="claude_interactive", title="wanted", tags=["work"], priority=5.0)
    create_thing(actor="claude_interactive", title="unwanted", tags=["home"], priority=5.0)

    found = find_things(tags=["work"])

    assert [t["title"] for t in found] == ["wanted"]
    assert json.loads(json.dumps(found))


def test_find_things_omitting_active_returns_only_live_things(tools):
    """The tool declares its own active default: an unfiltered listing must not leak archived Things."""
    live = create_thing(actor="claude_interactive", title="live")
    archived = create_thing(actor="claude_interactive", title="archived")
    archive_thing(actor="claude_interactive", thing_id=uuid.UUID(archived["id"]))

    found = find_things()

    assert [t["title"] for t in found] == ["live"]
    assert [t["id"] for t in found] == [live["id"]]
    assert sorted(t["title"] for t in find_things(active=None)) == ["archived", "live"]


def test_get_related_reports_depth_and_edge_type(tools):
    origin = create_thing(actor="claude_interactive", title="origin")
    neighbour = create_thing(actor="claude_interactive", title="neighbour")
    relate(
        actor="claude_interactive",
        source_thing_id=uuid.UUID(origin["id"]),
        target_thing_id=uuid.UUID(neighbour["id"]),
        relationship_type=RelationshipType.RELATED_TO,
    )

    found = get_related(uuid.UUID(origin["id"]))

    assert [(f["thing"]["title"], f["depth"], f["relationship_type"]) for f in found] == [("neighbour", 1, "RelatedTo")]
    assert get_related(uuid.uuid4()) == []
    assert json.loads(json.dumps(found))


def test_due_for_checkin_defaults_to_today(tools):
    # The tool's "today" is UTC, so the fixture's must be too, or this flakes either side of
    # local midnight in any offset timezone.
    today = datetime.now(UTC).date()
    create_thing(actor="claude_interactive", title="due", checkin_date=today)
    create_thing(actor="claude_interactive", title="later", checkin_date=today + timedelta(days=7))

    assert [t["title"] for t in due_for_checkin()] == ["due"]
    assert sorted(t["title"] for t in due_for_checkin(as_of=today + timedelta(days=7))) == ["due", "later"]


def test_stale_counts_days_of_silence(tools):
    thing = create_thing(actor="claude_interactive", title="forgotten")
    tools.execute(
        text("UPDATE things SET updated_at = :ts WHERE id = :id"),
        {"ts": datetime.now(UTC) - timedelta(days=90), "id": uuid.UUID(thing["id"])},
    )
    tools.commit()

    assert [t["title"] for t in stale(days=30)] == ["forgotten"]
    assert stale(days=365) == []


def test_blocked_returns_the_waiting_thing(tools):
    waiting = create_thing(actor="claude_interactive", title="waiting")
    blocker = create_thing(actor="claude_interactive", title="blocker")
    relate(
        actor="claude_interactive",
        source_thing_id=uuid.UUID(waiting["id"]),
        target_thing_id=uuid.UUID(blocker["id"]),
        relationship_type=RelationshipType.BLOCKS,
    )

    assert [t["title"] for t in blocked()] == ["waiting"]


def test_children_returns_the_targets_of_child_of_edges(tools):
    parent = create_thing(actor="claude_interactive", title="parent")
    child = create_thing(actor="claude_interactive", title="child")
    relate(
        actor="claude_interactive",
        source_thing_id=uuid.UUID(parent["id"]),
        target_thing_id=uuid.UUID(child["id"]),
        relationship_type=RelationshipType.CHILD_OF,
    )

    assert [t["title"] for t in children(uuid.UUID(parent["id"]))] == ["child"]
    assert children(uuid.uuid4()) == []


def test_get_thing_history_traces_one_thing_oldest_first(tools):
    thing = create_thing(actor="claude_scheduled", title="traced")
    other = create_thing(actor="claude_interactive", title="untraced")
    update_thing(actor="claude_interactive", thing_id=uuid.UUID(thing["id"]), title="renamed")

    entries = get_thing_history(uuid.UUID(thing["id"]))

    assert [(e["operation"], e["actor"]) for e in entries] == [
        ("create", "claude_scheduled"),
        ("update", "claude_interactive"),
    ]
    assert entries[1]["before"]["title"] == "traced"
    assert [e["entity_id"] for e in get_thing_history(uuid.UUID(other["id"]))] == [other["id"]]
    assert json.loads(json.dumps(entries))


def test_get_thing_history_excludes_relationship_entries(tools):
    source = create_thing(actor="claude_interactive", title="source")
    target = create_thing(actor="claude_interactive", title="target")
    relate(
        actor="claude_interactive",
        source_thing_id=uuid.UUID(source["id"]),
        target_thing_id=uuid.UUID(target["id"]),
        relationship_type=RelationshipType.REFERENCES,
    )

    assert [e["operation"] for e in get_thing_history(uuid.UUID(source["id"]))] == ["create"]


# --- Transport and auth ----------------------------------------------------

_TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
_MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture()
def mcp_token():
    """Set a token on the settings singleton, as conftest does for DATABASE_URL, and put it back."""
    previous = settings.MCP_API_TOKEN
    settings.MCP_API_TOKEN = "test-token"
    yield "test-token"
    settings.MCP_API_TOKEN = previous


def test_mcp_endpoint_refuses_an_unauthenticated_request(client, mcp_token):
    response = client.post("/mcp/", json=_TOOLS_LIST, headers=_MCP_HEADERS)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer")


def test_mcp_endpoint_refuses_the_wrong_token(client, mcp_token):
    response = client.post("/mcp/", json=_TOOLS_LIST, headers={**_MCP_HEADERS, "Authorization": "Bearer wrong-token"})

    assert response.status_code == 401


def test_mcp_endpoint_admits_the_configured_token(client, mcp_token):
    response = client.post("/mcp/", json=_TOOLS_LIST, headers={**_MCP_HEADERS, "Authorization": f"Bearer {mcp_token}"})

    assert response.status_code != 401
    assert "create_thing" in response.text


def test_an_unset_token_closes_the_endpoint_rather_than_opening_it(client):
    previous = settings.MCP_API_TOKEN
    settings.MCP_API_TOKEN = ""
    try:
        response = client.post("/mcp/", json=_TOOLS_LIST, headers=_MCP_HEADERS)
    finally:
        settings.MCP_API_TOKEN = previous

    assert response.status_code == 401
