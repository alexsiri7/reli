"""The MCP surface: what it exposes, what it refuses, and what it writes to the journal.

The tools are called directly — ``@reli_mcp.tool()`` returns the function unchanged and registers
it as a side effect — with ``_session`` bound to the fixture session so a tool's write and the
assertion about it share one transaction. The two transport tests go through the real app instead,
because auth and the mount are properties of the ASGI stack and not of the functions.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import get_args

import jwt
import pytest
from sqlalchemy import text

from backend import auth, prompts
from backend.config import settings
from backend.db_models import Actor, RelationshipType
from backend.mcp_server import (
    McpActor,
    add_preference_evidence,
    archive_thing,
    blocked,
    children,
    create_thing,
    due_for_checkin,
    find_things,
    get_initial_instructions,
    get_related,
    get_thing,
    get_thing_history,
    get_user_model,
    journal_since,
    needs_input,
    record_preference,
    reject_preference,
    relate,
    reli_mcp,
    stale,
    unrelate,
    update_thing,
)
from backend.service import ThingNotFound
from backend.tests.conftest import RETIRED_GOOGLE_TOOL_NAMES

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
    "needs_input",
    "children",
    "get_thing_history",
    "journal_since",
    "record_preference",
    "add_preference_evidence",
    "reject_preference",
    "get_user_model",
    "get_initial_instructions",
}

WRITING_TOOLS = {
    "create_thing",
    "update_thing",
    "archive_thing",
    "relate",
    "unrelate",
    "record_preference",
    "add_preference_evidence",
    "reject_preference",
}


def _journal_count(session):
    return session.execute(text("SELECT count(*) FROM journal")).scalar_one()


def _newest_journal_id(session):
    return session.execute(text("SELECT coalesce(max(id), 0) FROM journal")).scalar_one()


def _entries_since(session, count_before):
    return session.execute(
        text("SELECT actor, operation, entity_type, entity_id FROM journal ORDER BY id OFFSET :n"),
        {"n": count_before},
    ).all()


def _tool_schemas():
    return {tool.name: tool.inputSchema for tool in asyncio.run(reli_mcp.list_tools())}


# --- The surface -----------------------------------------------------------


def test_the_exposed_tools_are_exactly_the_twenty():
    assert set(_tool_schemas()) == TOOL_NAMES


def test_hard_delete_is_not_exposed():
    """#1409: there is no hard delete via MCP. service.delete_thing stays in-process only."""
    assert "delete_thing" not in _tool_schemas()


@pytest.mark.parametrize("tool", RETIRED_GOOGLE_TOOL_NAMES)
def test_the_retired_google_tools_are_not_exposed(tool):
    """#1488: Reli holds no Calendar or Gmail integration — a session brings its own connector."""
    assert tool not in _tool_schemas()


@pytest.mark.parametrize("tool", RETIRED_GOOGLE_TOOL_NAMES)
def test_the_server_instructions_name_no_retired_google_tool(tool):
    """The instructions reach a session before any prompt does, so they cannot name a dead tool."""
    assert tool not in (reli_mcp.instructions or "")


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


def test_needs_input_returns_the_tagged_things_with_the_truncation_signal(tools):
    for priority in range(3):
        create_thing(actor="claude_interactive", title=f"p{priority}", tags=["#NeedsInput"], priority=float(priority))
    settled = create_thing(actor="claude_interactive", title="settled", tags=["#NeedsInput"], priority=9.0)
    create_thing(actor="claude_interactive", title="untagged", priority=9.0)
    archive_thing(actor="claude_interactive", thing_id=uuid.UUID(settled["id"]))

    result = needs_input()

    assert [t["title"] for t in result["things"]] == ["p2", "p1", "p0"]
    assert result["total"] == 3
    assert result["truncated"] is False
    assert json.loads(json.dumps(result))

    capped = needs_input(limit=1)

    assert [t["title"] for t in capped["things"]] == ["p2"]
    assert capped["total"] == 3
    assert capped["truncated"] is True


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

    result = get_thing_history(uuid.UUID(thing["id"]))

    entries = result["entries"]
    assert [(e["operation"], e["actor"]) for e in entries] == [
        ("create", "claude_scheduled"),
        ("update", "claude_interactive"),
    ]
    assert entries[1]["before"]["title"] == "traced"
    assert result["total"] == 2
    assert result["truncated"] is False
    assert [e["entity_id"] for e in get_thing_history(uuid.UUID(other["id"]))["entries"]] == [other["id"]]
    assert json.loads(json.dumps(result))


def test_get_thing_history_excludes_relationship_entries(tools):
    source = create_thing(actor="claude_interactive", title="source")
    target = create_thing(actor="claude_interactive", title="target")
    relate(
        actor="claude_interactive",
        source_thing_id=uuid.UUID(source["id"]),
        target_thing_id=uuid.UUID(target["id"]),
        relationship_type=RelationshipType.REFERENCES,
    )

    assert [e["operation"] for e in get_thing_history(uuid.UUID(source["id"]))["entries"]] == ["create"]


def test_get_thing_history_reports_the_newest_window_and_its_truncation(tools):
    thing = create_thing(actor="claude_interactive", title="busy")
    for version in range(6):
        update_thing(actor="claude_interactive", thing_id=uuid.UUID(thing["id"]), title=f"v{version}")

    result = get_thing_history(uuid.UUID(thing["id"]), limit=2)

    assert [e["after"]["title"] for e in result["entries"]] == ["v4", "v5"]
    assert result["total"] == 7
    assert result["truncated"] is True


def test_journal_since_is_a_read_and_takes_no_actor_argument():
    """The ``actors`` filter is a different key, and it admits all three actors: a read may ask for
    the user's own edits, which no write over MCP may claim."""
    schema = _tool_schemas()["journal_since"]

    assert "actor" not in schema["properties"]
    assert "actors" in schema["properties"]
    assert schema["$defs"]["Actor"]["enum"] == [actor.value for actor in Actor]


def test_journal_since_over_mcp_excludes_the_actor_it_was_told_to(tools):
    watermark = _newest_journal_id(tools)
    create_thing(actor="claude_scheduled", title="claude, unattended")
    relayed = create_thing(actor="claude_interactive", title="relayed in conversation")

    result = journal_since(after_id=watermark, actors=["claude_interactive"])

    assert [(e["actor"], e["entity_id"]) for e in result["entries"]] == [("claude_interactive", relayed["id"])]
    assert result["total"] == 1
    assert result["truncated"] is False
    assert json.loads(json.dumps(result))


# --- The user model --------------------------------------------------------


def _resource_json(uri):
    (content,) = asyncio.run(reli_mcp.read_resource(uri))
    return json.loads(content.content)


def test_reject_preference_cannot_claim_the_user_made_the_decision():
    """Over MCP the honest actor is the Claude session that relayed the rejection, not the user."""
    assert Actor.USER.value not in _tool_schemas()["reject_preference"]["properties"]["actor"]["enum"]


def test_record_preference_over_mcp_returns_the_preference_with_its_evidence(tools):
    evidence = create_thing(actor=Actor.CLAUDE_INTERACTIVE, title="declined a 9am meeting")

    recorded = record_preference(
        actor=Actor.CLAUDE_INTERACTIVE,
        title="Prefers deep work 9-11am",
        scope="scheduling",
        evidence_ids=[uuid.UUID(evidence["id"])],
    )

    assert recorded["scope"] == "scheduling"
    assert recorded["evidence_count"] == 1
    assert recorded["rejected"] is False
    assert [thing["id"] for thing in recorded["evidence"]] == [evidence["id"]]


def test_add_preference_evidence_over_mcp_returns_the_reinforced_preference(tools):
    evidence = create_thing(actor=Actor.CLAUDE_INTERACTIVE, title="declined a 9am meeting")
    recorded = record_preference(
        actor=Actor.CLAUDE_INTERACTIVE,
        title="Prefers deep work 9-11am",
        scope="scheduling",
        evidence_ids=[uuid.UUID(evidence["id"])],
    )
    more = create_thing(actor=Actor.CLAUDE_INTERACTIVE, title="moved standup to noon")

    reinforced = add_preference_evidence(
        actor=Actor.CLAUDE_SCHEDULED,
        preference_id=uuid.UUID(recorded["thing"]["id"]),
        evidence_id=uuid.UUID(more["id"]),
    )

    assert reinforced["evidence_count"] == 2


def test_reject_preference_over_mcp_hides_it_from_the_default_model(tools):
    evidence = create_thing(actor=Actor.CLAUDE_INTERACTIVE, title="declined a 9am meeting")
    recorded = record_preference(
        actor=Actor.CLAUDE_INTERACTIVE,
        title="Prefers deep work 9-11am",
        scope="scheduling",
        evidence_ids=[uuid.UUID(evidence["id"])],
    )

    rejected = reject_preference(actor=Actor.CLAUDE_INTERACTIVE, preference_id=uuid.UUID(recorded["thing"]["id"]))

    assert rejected["rejected"] is True
    assert get_user_model()["preferences"] == []
    assert len(get_user_model(include_rejected=True)["preferences"]) == 1


def test_the_user_model_is_exposed_as_a_resource_scoped_and_unscoped():
    resources = {str(resource.uri) for resource in asyncio.run(reli_mcp.list_resources())}
    templates = {template.uriTemplate for template in asyncio.run(reli_mcp.list_resource_templates())}

    assert "reli://user-model" in resources
    assert "reli://user-model/{scope}" in templates


def test_the_user_model_resource_returns_the_same_payload_as_the_tool(tools):
    evidence = create_thing(actor=Actor.CLAUDE_INTERACTIVE, title="declined a 9am meeting")
    record_preference(
        actor=Actor.CLAUDE_INTERACTIVE,
        title="Prefers deep work 9-11am",
        scope="scheduling",
        evidence_ids=[uuid.UUID(evidence["id"])],
    )

    assert _resource_json("reli://user-model") == get_user_model()


def test_the_user_model_resource_filters_by_scope(tools):
    evidence = create_thing(actor=Actor.CLAUDE_INTERACTIVE, title="declined a 9am meeting")
    for title, scope in (("Prefers deep work 9-11am", "scheduling"), ("Names projects by outcome", "naming")):
        record_preference(
            actor=Actor.CLAUDE_INTERACTIVE,
            title=title,
            scope=scope,
            evidence_ids=[uuid.UUID(evidence["id"])],
        )

    scoped = _resource_json("reli://user-model/scheduling")

    assert [preference["thing"]["title"] for preference in scoped["preferences"]] == ["Prefers deep work 9-11am"]


def test_no_user_model_payload_carries_a_confidence_score(tools):
    evidence = create_thing(actor=Actor.CLAUDE_INTERACTIVE, title="declined a 9am meeting")
    record_preference(
        actor=Actor.CLAUDE_INTERACTIVE,
        title="Prefers deep work 9-11am",
        scope="scheduling",
        evidence_ids=[uuid.UUID(evidence["id"])],
    )

    assert "confidence" not in json.dumps(get_user_model())


# --- Prompts: the hats ------------------------------------------------------

PROMPT_SCOPES = {
    "capture": prompts.CAPTURE_SCOPE,
    "daily-planning": prompts.SCHEDULING_SCOPE,
    "project-planning": prompts.PLANNING_SCOPE,
    "review": prompts.REVIEW_SCOPE,
}


def _prompts():
    return {prompt.name: prompt for prompt in asyncio.run(reli_mcp.list_prompts())}


def _prompt_text(name):
    result = asyncio.run(reli_mcp.get_prompt(name))
    (message,) = result.messages
    assert message.role == "user"
    return message.content.text


def test_the_exposed_prompts_are_exactly_the_four_hats():
    """#1411: the names are the ones the issue gives, hyphens included, not the function names."""
    assert set(_prompts()) == set(PROMPT_SCOPES)


@pytest.mark.parametrize("name", sorted(PROMPT_SCOPES))
def test_every_prompt_carries_the_preference_capture_convention(name):
    """The explicit half of learning depends on this appearing in every prompt, not just one."""
    text = _prompt_text(name)

    assert prompts.PREFERENCE_CAPTURE_CONVENTION in text
    assert "record_preference" in text
    assert "in the same turn you noticed it" in text
    assert '"I hate morning meetings" is a preference' in text
    assert '"Move that to Thursday" on its own is not' in text


@pytest.mark.parametrize("name", sorted(PROMPT_SCOPES))
def test_every_prompt_states_what_a_checkin_date_means(name):
    text = _prompt_text(name)

    assert prompts.CHECKIN_SEMANTICS in text
    assert "A check-in date is your obligation, not the user's." in text
    assert "resolved without involving the user" in text
    assert "evidence, not a verdict" in text
    assert "when you cannot tell, the check-in is not resolved" in text


@pytest.mark.parametrize("name", sorted(PROMPT_SCOPES))
@pytest.mark.parametrize("tool", RETIRED_GOOGLE_TOOL_NAMES)
def test_no_prompt_sends_a_session_to_a_reli_google_tool(name, tool):
    """#1487: a session looks through its own Calendar and Gmail connectors."""
    assert tool not in _prompt_text(name)


@pytest.mark.parametrize("tool", RETIRED_GOOGLE_TOOL_NAMES)
def test_the_initial_instructions_send_no_session_to_a_reli_google_tool(tool):
    assert tool not in get_initial_instructions()


@pytest.mark.parametrize(("name", "scope"), sorted(PROMPT_SCOPES.items()))
def test_every_prompt_names_the_scope_it_loads_in_its_description_and_its_body(name, scope):
    """The description is what a connected session shows before the prompt is picked."""
    assert f"'{scope}'" in _prompts()[name].description
    assert f'get_user_model(scope="{scope}")' in _prompt_text(name)
    assert f"reli://user-model/{scope}" in _prompt_text(name)


def test_the_prompts_take_no_arguments():
    assert all(prompt.arguments == [] for prompt in _prompts().values())


# --- get_initial_instructions ----------------------------------------------
#
# #1466: a prompt reaches a session only when the user picks it, so the default behaviour is also
# a tool. It is called without the ``tools`` fixture: it reads nothing from the graph.


def test_get_initial_instructions_is_the_capture_prompt_plus_the_hats():
    text = get_initial_instructions()

    assert text.startswith(prompts.capture())
    assert prompts.HAT_ORIENTATION in text
    for hat in ("daily-planning", "project-planning", "review"):
        assert f"`{hat}`" in text


def test_get_initial_instructions_carries_the_shared_conventions():
    text = get_initial_instructions()

    assert prompts.PREFERENCE_CAPTURE_CONVENTION in text
    assert prompts.CHECKIN_SEMANTICS in text
    assert f'get_user_model(scope="{prompts.CAPTURE_SCOPE}")' in text
    assert 'actor="claude_interactive"' in text


def test_get_initial_instructions_follows_an_edit_to_the_convention(monkeypatch):
    """One source, not two: the text is derived at call time, so editing the constant is enough."""
    monkeypatch.setattr(prompts, "PREFERENCE_CAPTURE_CONVENTION", "## Sentinel convention")

    assert "## Sentinel convention" in get_initial_instructions()
    assert "## Sentinel convention" in _prompt_text("capture")


def test_get_initial_instructions_takes_no_arguments():
    assert _tool_schemas()["get_initial_instructions"]["properties"] == {}


# --- Transport and auth ----------------------------------------------------

_TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
_PROMPTS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "prompts/list", "params": {}}
_MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture()
def secret_key():
    """A signing key on the settings singleton, as conftest does for DATABASE_URL, and put it back."""
    previous = settings.SECRET_KEY
    settings.SECRET_KEY = "a-test-secret-key-that-is-forty-eight-chars-long"
    yield settings.SECRET_KEY
    settings.SECRET_KEY = previous


@pytest.fixture()
def mcp_token(secret_key):
    """What a connector holds after the Google sign-in: an ``aud="mcp"`` JWT the authorization server minted."""
    return auth.create_jwt("1234567890", "owner@example.com", audience="mcp")


def _bearer(token):
    return {**_MCP_HEADERS, "Authorization": f"Bearer {token}"}


def test_mcp_endpoint_refuses_an_unauthenticated_request(client, secret_key):
    response = client.post("/mcp/", json=_TOOLS_LIST, headers=_MCP_HEADERS)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer")


def test_mcp_endpoint_refuses_a_bearer_that_is_not_a_jwt(client, secret_key):
    response = client.post("/mcp/", json=_TOOLS_LIST, headers=_bearer("wrong-token"))

    assert response.status_code == 401


def test_the_bare_path_reaches_the_mcp_app_with_the_same_bearer_check(client, mcp_token):
    """#1450: what the claude.ai connector actually sends is POST /mcp, with no trailing slash."""
    headers = {**_MCP_HEADERS, "Authorization": f"Bearer {mcp_token}"}

    admitted = client.post("/mcp", json=_TOOLS_LIST, headers=headers, follow_redirects=False)
    refused = client.post("/mcp", json=_TOOLS_LIST, headers=_MCP_HEADERS, follow_redirects=False)

    assert admitted.status_code == 200
    assert "create_thing" in admitted.text
    assert refused.status_code == 401
    assert refused.json() == client.post("/mcp/", json=_TOOLS_LIST, headers=_MCP_HEADERS).json()


@pytest.mark.parametrize(("method", "status"), [("GET", 406), ("DELETE", 405)])
def test_the_bare_path_answers_the_other_transport_methods_like_the_slash_path(client, mcp_token, method, status):
    """Streamable HTTP also uses GET (the listening stream) and DELETE (session end); both must reach
    the transport on either path, and neither may be a redirect. The JSON-only Accept keeps the GET
    from opening a stream that never ends, so what comes back is the transport's own 406; stateless
    mode has no session for the DELETE to end, so that is its 405. A 401 or 3xx would be the check or
    the router answering instead."""
    headers = {"Accept": "application/json", "Authorization": f"Bearer {mcp_token}"}

    bare = client.request(method, "/mcp", headers=headers, follow_redirects=False)
    canonical = client.request(method, "/mcp/", headers=headers, follow_redirects=False)

    assert bare.status_code == canonical.status_code == status


def test_the_prompts_are_retrievable_over_mcp(client, mcp_token):
    """#1411's first acceptance criterion, through the real transport rather than the registry."""
    headers = {**_MCP_HEADERS, "Authorization": f"Bearer {mcp_token}"}

    response = client.post("/mcp/", json=_PROMPTS_LIST, headers=headers)

    assert response.status_code == 200
    assert all(name in response.text for name in PROMPT_SCOPES)


def test_an_unset_secret_key_closes_the_endpoint_rather_than_opening_it(client):
    previous = settings.SECRET_KEY
    settings.SECRET_KEY = ""
    try:
        response = client.post("/mcp/", json=_TOOLS_LIST, headers=_MCP_HEADERS)
    finally:
        settings.SECRET_KEY = previous

    assert response.status_code == 401


def test_mcp_endpoint_admits_a_jwt_the_authorization_server_minted(client, mcp_token):
    response = client.post("/mcp/", json=_TOOLS_LIST, headers=_bearer(mcp_token))

    assert response.status_code != 401
    assert "create_thing" in response.text


def test_mcp_endpoint_refuses_a_jwt_for_another_audience(client, secret_key):
    token = auth.create_jwt("1234567890", "owner@example.com", audience="web")

    response = client.post("/mcp/", json=_TOOLS_LIST, headers=_bearer(token))

    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["WWW-Authenticate"]


def test_an_expired_jwt_is_refused_naming_the_refresh_path(client, secret_key):
    expired = jwt.encode(
        {"sub": "1234567890", "aud": "mcp", "exp": datetime.now(UTC) - timedelta(seconds=1)},
        secret_key,
        algorithm="HS256",
    )

    response = client.post("/mcp/", json=_TOOLS_LIST, headers=_bearer(expired))

    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["WWW-Authenticate"]
    assert "/oauth/token" in response.json()["detail"]


def test_the_401_points_at_the_resource_metadata_when_a_base_url_is_set(client, secret_key):
    previous = settings.RELI_BASE_URL
    settings.RELI_BASE_URL = "https://reli.example.test"
    try:
        response = client.post("/mcp/", json=_TOOLS_LIST, headers=_MCP_HEADERS)
    finally:
        settings.RELI_BASE_URL = previous

    assert response.status_code == 401
    assert (
        'resource_metadata="https://reli.example.test/.well-known/oauth-protected-resource"'
        in response.headers["WWW-Authenticate"]
    )


def test_with_secret_key_unset_the_401_names_what_to_set(client):
    previous = settings.SECRET_KEY
    settings.SECRET_KEY = ""
    try:
        response = client.post("/mcp/", json=_TOOLS_LIST, headers=_bearer("anything"))
    finally:
        settings.SECRET_KEY = previous

    assert response.status_code == 401
    assert "SECRET_KEY" in response.json()["detail"]


def test_a_static_token_left_in_the_environment_is_not_a_credential(client, secret_key, monkeypatch):
    """#1461 retired MCP_API_TOKEN: a deploy still carrying the variable boots, and the value it
    holds is refused like any other non-JWT bearer, naming the sign-in as the remedy."""
    monkeypatch.setenv("MCP_API_TOKEN", "the-retired-static-token")
    assert not hasattr(type(settings)(), "MCP_API_TOKEN")

    response = client.post("/mcp/", json=_TOOLS_LIST, headers=_bearer("the-retired-static-token"))

    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["WWW-Authenticate"]
    assert "Google" in response.json()["detail"]
