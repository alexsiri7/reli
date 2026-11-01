"""api.py and mcp_server.py each hand-list which fields of a queries.Preference and a
queries.History they expose — one into a Pydantic model, the other into a dict — with nothing
today to catch one being updated and the other forgotten.

No database involved: a Preference and a History are built directly from in-memory records.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend import api, mcp_server, queries
from backend.db_models import Actor, EntityType, JournalRecord, Operation, ThingRecord


def _preference() -> queries.Preference:
    thing = ThingRecord(title="a preference", tags=["#Preference"], notes={"scope": "voice"})
    evidence = ThingRecord(title="an observation", tags=["#Observation"])
    return queries.Preference(thing=thing, evidence=[evidence])


def _history() -> queries.History:
    entry = JournalRecord(
        id=1,
        occurred_at=datetime.now(UTC),
        actor=Actor.USER,
        operation=Operation.CREATE,
        entity_type=EntityType.THING,
        entity_id=ThingRecord(title="unrelated").id,
    )
    return queries.History(entries=[entry], total=1)


def test_preference_serializations_expose_the_same_fields():
    preference = _preference()
    api_fields = set(api._preference(preference).model_dump().keys())
    mcp_fields = set(mcp_server._preference_dict(preference).keys())
    assert api_fields == mcp_fields


def test_history_serializations_expose_the_same_fields():
    history = _history()
    api_fields = set(api._history(history).model_dump().keys())
    mcp_fields = set(mcp_server._history_dict(history).keys())
    assert api_fields == mcp_fields
