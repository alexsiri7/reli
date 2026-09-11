"""The ``/api`` routes the web view consumes: what they return, what they refuse, and who they let in.

The routes are built onto a fresh ``FastAPI()`` with ``api._session`` bound to the fixture session,
so a route's read and the assertion about it share one transaction. ``backend.main.app`` is
deliberately not used: the ``client`` fixture's docstring explains that a second ``TestClient`` over
it breaks the MCP session manager.
"""

import base64
import uuid
from contextlib import contextmanager
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend import api
from backend.config import settings
from backend.db_models import (
    OBSERVATION_TAG,
    PREFERENCE_TAG,
    REJECTED_TAG,
    USER_TAG,
    Actor,
    RelationshipType,
)
from backend.service import create_thing, get_or_create_user_anchor, record_preference, relate, update_thing

PASSWORD = "test-password"


def _routed_app(session, monkeypatch) -> FastAPI:
    """The ``/api`` router plus a stand-in ``/healthz``, behind the Basic check."""

    @contextmanager
    def _fixture_session():
        yield session

    monkeypatch.setattr(api, "_session", _fixture_session)

    app = FastAPI()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "reli"}

    app.include_router(api.router)
    api.add_web_view_auth(app)
    return app


@pytest.fixture()
def web_password():
    """A known password on the settings singleton, mutated rather than rebound, and put back."""
    previous = settings.WEB_UI_PASSWORD
    settings.WEB_UI_PASSWORD = PASSWORD
    yield PASSWORD
    settings.WEB_UI_PASSWORD = previous


def _basic(password, username="reli"):
    return {"Authorization": "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()}


@pytest.fixture()
def client(session, monkeypatch, web_password):
    """An authenticated client. Without the password every route below would answer 401."""
    return TestClient(_routed_app(session, monkeypatch), headers=_basic(web_password))


@pytest.fixture()
def anonymous(session, monkeypatch):
    """A client carrying no credentials, for the auth tests that drive the password themselves."""
    return TestClient(_routed_app(session, monkeypatch))


def _thing(session, title, **fields):
    return create_thing(session, actor=Actor.CLAUDE_INTERACTIVE, title=title, **fields)


def _relate(session, source, target, relationship_type, context=None):
    return relate(
        session,
        actor=Actor.CLAUDE_INTERACTIVE,
        source_thing_id=source.id,
        target_thing_id=target.id,
        relationship_type=relationship_type,
        context=context,
    )


def _journal_count(session):
    return session.execute(text("SELECT count(*) FROM journal")).scalar_one()


def _preference(session, title="Prefers deep work 9-11am", scope="scheduling"):
    """A preference with one ``#Observation`` behind it — the shape ``user_model`` requires."""
    observation = _thing(session, "Moved the 9am standup again", tags=[OBSERVATION_TAG])
    preference = record_preference(
        session,
        actor=Actor.CLAUDE_INTERACTIVE,
        title=title,
        scope=scope,
        evidence_ids=[observation.id],
    )
    return preference, observation


# --- GET /api/things: one level of the tree --------------------------------


def test_the_top_level_is_the_things_nothing_claims_as_a_child(client, session):
    parent = _thing(session, "Rebuild Reli")
    child = _thing(session, "Read-only web view")
    _relate(session, parent, child, RelationshipType.CHILD_OF)

    titles = [thing["title"] for thing in client.get("/api/things").json()["things"]]

    assert titles == ["Rebuild Reli"]


def test_the_top_level_leaves_out_the_user_model_machinery(client, session):
    _thing(session, "Rebuild Reli")
    get_or_create_user_anchor(session, actor=Actor.CLAUDE_INTERACTIVE)
    _preference(session)

    tags = [tag for thing in client.get("/api/things").json()["things"] for tag in thing["tags"]]

    assert tags == []
    assert {USER_TAG, PREFERENCE_TAG, OBSERVATION_TAG}.isdisjoint(tags)


def test_has_children_distinguishes_a_parent_from_a_leaf(client, session):
    parent = _thing(session, "Rebuild Reli")
    leaf = _thing(session, "Buy milk")
    _relate(session, parent, _thing(session, "Read-only web view"), RelationshipType.CHILD_OF)

    found = {thing["title"]: thing["has_children"] for thing in client.get("/api/things").json()["things"]}

    assert found == {"Rebuild Reli": True, "Buy milk": False}
    assert leaf.id is not None


def test_has_children_is_false_when_every_child_is_archived(client, session):
    parent = _thing(session, "Rebuild Reli")
    child = _thing(session, "Retired idea")
    _relate(session, parent, child, RelationshipType.CHILD_OF)
    update_thing(session, actor=Actor.CLAUDE_INTERACTIVE, thing_id=child.id, active=False)

    found = client.get("/api/things").json()["things"]

    assert [thing["has_children"] for thing in found] == [False]
    assert client.get(f"/api/things?parent={parent.id}").json()["things"] == []


def test_a_child_of_an_archived_parent_returns_to_the_top_level(client, session):
    """Archiving a parent must not strand its children: an inactive parent claims nothing.

    The parent has dropped out of the tree, so a child still counted as claimed would appear at no
    level at all and be reachable only by pasting a URL.
    """
    parent = _thing(session, "Retired project")
    child = _thing(session, "Still worth doing")
    _relate(session, parent, child, RelationshipType.CHILD_OF)
    update_thing(session, actor=Actor.CLAUDE_INTERACTIVE, thing_id=parent.id, active=False)

    titles = [thing["title"] for thing in client.get("/api/things").json()["things"]]

    assert titles == ["Still worth doing"]


def test_a_parent_query_returns_exactly_that_things_children(client, session):
    parent = _thing(session, "Rebuild Reli")
    other_parent = _thing(session, "Unrelated project")
    _relate(session, parent, _thing(session, "Read-only web view", priority=2.0), RelationshipType.CHILD_OF)
    _relate(session, parent, _thing(session, "Learning pass", priority=5.0), RelationshipType.CHILD_OF)
    _relate(session, other_parent, _thing(session, "Somebody else's child"), RelationshipType.CHILD_OF)

    titles = [thing["title"] for thing in client.get(f"/api/things?parent={parent.id}").json()["things"]]

    assert titles == ["Learning pass", "Read-only web view"]


def test_a_tree_level_carries_the_fields_the_view_renders(client, session):
    _thing(session, "Rebuild Reli", tags=["#Project"], priority=3.0, checkin_date=date(2026, 10, 1))

    (found,) = client.get("/api/things").json()["things"]

    assert found == {
        "id": found["id"],
        "title": "Rebuild Reli",
        "tags": ["#Project"],
        "priority": 3.0,
        "active": True,
        "checkin_date": "2026-10-01",
        "has_children": False,
    }


# --- GET /api/things/{id}: the detail payload ------------------------------


def test_thing_detail_returns_the_whole_thing(client, session):
    thing = _thing(
        session,
        "Rebuild Reli",
        description="The v4 rewrite",
        notes={"why": "The old schema is **gone**"},
        tags=["#Project"],
        urls={"issue": "https://github.com/alexsiri7/reli/issues/1414"},
        priority=4.0,
    )

    payload = client.get(f"/api/things/{thing.id}").json()["thing"]

    assert payload["title"] == "Rebuild Reli"
    assert payload["notes"] == {"why": "The old schema is **gone**"}
    assert payload["urls"] == {"issue": "https://github.com/alexsiri7/reli/issues/1414"}
    assert payload["description"] == "The v4 rewrite"
    assert payload["priority"] == 4.0


def test_thing_detail_resolves_each_edges_direction_and_far_end(client, session):
    thing = _thing(session, "Read-only web view")
    parent = _thing(session, "Rebuild Reli", tags=["#Project"])
    blocker = _thing(session, "The user model")
    _relate(session, parent, thing, RelationshipType.CHILD_OF, context="ninth issue")
    _relate(session, thing, blocker, RelationshipType.BLOCKS)

    edges = {edge["relationship_type"]: edge for edge in client.get(f"/api/things/{thing.id}").json()["relationships"]}

    assert edges["ChildOf"]["direction"] == "incoming"
    assert edges["ChildOf"]["other"] == {"id": str(parent.id), "title": "Rebuild Reli", "tags": ["#Project"]}
    assert edges["ChildOf"]["context"] == "ninth issue"
    assert edges["Blocks"]["direction"] == "outgoing"
    assert edges["Blocks"]["other"]["title"] == "The user model"


def test_thing_detail_is_404_for_an_unknown_id(client):
    assert client.get(f"/api/things/{uuid.uuid4()}").status_code == 404


# --- GET /api/things/{id}/history -----------------------------------------


def test_history_returns_entries_oldest_first_with_the_actor(client, session):
    thing = _thing(session, "Rebuild Reli")
    update_thing(session, actor=Actor.CLAUDE_SCHEDULED, thing_id=thing.id, title="Rebuild Reli v4")

    payload = client.get(f"/api/things/{thing.id}/history").json()

    assert [entry["operation"] for entry in payload["entries"]] == ["create", "update"]
    assert [entry["actor"] for entry in payload["entries"]] == ["claude_interactive", "claude_scheduled"]
    assert payload["total"] == 2
    assert payload["truncated"] is False


def test_history_reports_truncation_when_the_limit_cuts_the_window(client, session):
    thing = _thing(session, "Rebuild Reli")
    update_thing(session, actor=Actor.CLAUDE_INTERACTIVE, thing_id=thing.id, priority=1.0)

    payload = client.get(f"/api/things/{thing.id}/history?limit=1").json()

    assert payload["truncated"] is True
    assert payload["total"] == 2
    assert [entry["operation"] for entry in payload["entries"]] == ["update"]


def test_history_refuses_a_limit_below_one(client, session):
    thing = _thing(session, "Rebuild Reli")

    assert client.get(f"/api/things/{thing.id}/history?limit=0").status_code == 422


# --- GET /api/user-model --------------------------------------------------


def test_the_user_model_carries_each_preference_with_its_evidence(client, session):
    preference, observation = _preference(session)

    (found,) = client.get("/api/user-model").json()["preferences"]

    assert found["thing"]["id"] == str(preference.id)
    assert found["scope"] == "scheduling"
    assert found["rejected"] is False
    assert found["evidence"] == [{"id": str(observation.id), "title": observation.title, "tags": [OBSERVATION_TAG]}]
    assert found["evidence_count"] == 1


def test_the_user_model_shows_rejected_preferences(client, session):
    """The view's job is to make a wrong preference spottable, so it cannot hide the rejected ones."""
    preference, _ = _preference(session)
    client.post(f"/api/preferences/{preference.id}/reject")

    (found,) = client.get("/api/user-model").json()["preferences"]

    assert found["rejected"] is True
    assert REJECTED_TAG in found["thing"]["tags"]
    assert found["evidence_count"] == 1


def test_the_user_model_filters_by_scope(client, session):
    _preference(session, title="Prefers deep work 9-11am", scope="scheduling")
    _preference(session, title="Prefers kebab-case slugs", scope="naming")

    payload = client.get("/api/user-model?scope=naming").json()

    assert payload["scope"] == "naming"
    assert [found["thing"]["title"] for found in payload["preferences"]] == ["Prefers kebab-case slugs"]


def test_the_user_model_names_no_confidence(client, session):
    _preference(session)

    assert "confidence" not in client.get("/api/user-model").text


# --- POST /api/preferences/{id}/reject: the one write ---------------------


def test_rejecting_a_preference_tags_it_and_journals_the_user(client, session):
    preference, _ = _preference(session)
    before = _journal_count(session)

    payload = client.post(f"/api/preferences/{preference.id}/reject").json()

    assert payload["rejected"] is True
    assert REJECTED_TAG in payload["thing"]["tags"]
    entries = session.execute(text("SELECT actor, operation FROM journal ORDER BY id OFFSET :n"), {"n": before}).all()
    assert entries == [(Actor.USER.value, "update")]


def test_rejecting_twice_changes_and_journals_nothing(client, session):
    preference, _ = _preference(session)
    client.post(f"/api/preferences/{preference.id}/reject")
    before = _journal_count(session)

    response = client.post(f"/api/preferences/{preference.id}/reject")

    assert response.status_code == 200
    assert response.json()["rejected"] is True
    assert _journal_count(session) == before


def test_rejecting_a_thing_that_is_not_a_preference_is_404(client, session):
    """The path names a preference resource, and there is no preference there."""
    thing = _thing(session, "Rebuild Reli")

    assert client.post(f"/api/preferences/{thing.id}/reject").status_code == 404


def test_rejecting_an_unknown_id_is_404(client):
    assert client.post(f"/api/preferences/{uuid.uuid4()}/reject").status_code == 404


# --- The read-only boundary ----------------------------------------------

#: The catch-all is exempt: it answers 404 to every method and reaches no service function, so it
#: cannot create or modify anything. ``test_an_unmatched_api_path_is_404_for_any_method`` proves it.
_CATCH_ALL_PATH = "/api/{unmatched:path}"

REJECT_PATH = "/api/preferences/{preference_id}/reject"


def test_the_reject_route_is_the_only_api_route_that_is_not_a_get():
    """The issue's first acceptance criterion, made mechanical: no second write can arrive quietly."""
    writable = {
        route.path: sorted(route.methods)
        for route in api.router.routes
        if route.path not in (REJECT_PATH, _CATCH_ALL_PATH) and set(route.methods) != {"GET"}
    }

    assert writable == {}
    assert {route.path: sorted(route.methods) for route in api.router.routes if route.path == REJECT_PATH} == {
        REJECT_PATH: ["POST"]
    }


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
def test_an_unmatched_api_path_is_404_for_any_method(client, method):
    """Without the catch-all a typo'd endpoint would fall through to the SPA and answer 200 html."""
    response = getattr(client, method)("/api/no-such-endpoint")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


# --- Access control ------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/things", "/api/user-model"])
def test_an_unset_password_closes_the_view_rather_than_opening_it(anonymous, path):
    previous = settings.WEB_UI_PASSWORD
    settings.WEB_UI_PASSWORD = ""
    try:
        assert anonymous.get(path).status_code == 401
    finally:
        settings.WEB_UI_PASSWORD = previous


def test_healthz_stays_open_so_a_missing_password_cannot_roll_a_deploy_back(anonymous):
    previous = settings.WEB_UI_PASSWORD
    settings.WEB_UI_PASSWORD = ""
    try:
        response = anonymous.get("/healthz")
    finally:
        settings.WEB_UI_PASSWORD = previous

    assert response.status_code == 200


def test_a_missing_header_is_401_and_asks_the_browser_to_prompt(anonymous, web_password):
    response = anonymous.get("/api/things")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="reli"'


def test_the_wrong_password_is_401(anonymous, web_password):
    assert anonymous.get("/api/things", headers=_basic("not-the-password")).status_code == 401


def test_the_right_password_is_admitted_whatever_the_username(anonymous, web_password):
    """There is one user, so there are no accounts to tell apart."""
    response = anonymous.get("/api/things", headers=_basic(web_password, username="anyone"))

    assert response.status_code == 200


@pytest.mark.parametrize(
    "header",
    ["Bearer test-password", "Basic not-base64!!", f"Basic {base64.b64encode(b'no-colon').decode()}"],
    ids=["bearer", "undecodable", "no-separator"],
)
def test_a_malformed_authorization_header_is_401_and_not_a_500(anonymous, web_password, header):
    assert anonymous.get("/api/things", headers={"Authorization": header}).status_code == 401


def test_the_mcp_mount_is_not_touched_by_the_basic_check(session, monkeypatch, web_password):
    """/mcp carries its own bearer check, which must stay the only thing deciding it."""
    app = _routed_app(session, monkeypatch)

    @app.get("/mcp/")
    def fake_mcp() -> dict[str, str]:
        return {"mounted": "yes"}

    assert TestClient(app).get("/mcp/").status_code == 200


@pytest.mark.parametrize("path", ["/.well-known/x", "/oauth/x", "/api/auth/x"])
def test_the_authorization_servers_surface_is_not_touched_by_the_basic_check(anonymous, web_password, path):
    """These reach the router — a 404 here, where nothing is registered — rather than the middleware."""
    assert anonymous.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/api/authors", "/api/auth", "/oauth", "/.well-known"])
def test_the_exemption_is_by_whole_path_segment(anonymous, web_password, path):
    assert anonymous.get(path).status_code == 401


# --- Serving the built frontend ------------------------------------------


def _dist(tmp_path, body="<!doctype html><title>Reli</title>"):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(body)
    return tmp_path


def test_a_deep_link_is_served_the_bundle_so_a_reload_resolves_client_side(tmp_path):
    app = FastAPI()
    api.mount_frontend(app, _dist(tmp_path))

    response = TestClient(app).get(f"/things/{uuid.uuid4()}")

    assert response.status_code == 200
    assert "<title>Reli</title>" in response.text


def test_an_image_built_without_a_frontend_still_boots(tmp_path):
    app = FastAPI()

    api.mount_frontend(app, tmp_path / "absent")

    assert TestClient(app).get("/").status_code == 404


@pytest.mark.parametrize("path", ["/", "/assets/app.js"], ids=["spa", "asset"])
def test_the_bundle_is_behind_the_same_password_as_the_api(tmp_path, web_password, path):
    """Both the SPA catch-all and the ``/assets`` sub-app, which are registered separately.

    A guard attached to ``api.router`` alone would leave the bundle open; that this is what prompts
    the browser once, and then carries the header onto the XHRs, is the reason there is no login view.
    """
    dist = _dist(tmp_path)
    (dist / "assets" / "app.js").write_text("export {};")
    app = FastAPI()
    api.mount_frontend(app, dist)
    api.add_web_view_auth(app)
    client = TestClient(app)

    anonymous = client.get(path)
    assert anonymous.status_code == 401
    assert anonymous.headers["WWW-Authenticate"] == 'Basic realm="reli"'

    assert client.get(path, headers=_basic(web_password)).status_code == 200
