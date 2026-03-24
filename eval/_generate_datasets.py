#!/usr/bin/env python3
"""Generate golden eval datasets for reasoning and context agents.

Run once to produce .test.json files:
    python -m eval._generate_datasets
"""

from __future__ import annotations

import json
import pathlib

from google.adk.evaluation.eval_case import (
    EvalCase,
    IntermediateData,
    Invocation,
)
from google.adk.evaluation.eval_set import EvalSet
from google.genai import types as genai_types

HERE = pathlib.Path(__file__).resolve().parent


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def _user(text: str) -> genai_types.Content:
    return genai_types.Content(
        role="user",
        parts=[genai_types.Part.from_text(text=text)],
    )


def _model(text: str) -> genai_types.Content:
    return genai_types.Content(
        role="model",
        parts=[genai_types.Part.from_text(text=text)],
    )


def _fc(name: str, args: dict) -> genai_types.FunctionCall:
    return genai_types.FunctionCall(name=name, args=args)


def _fr(name: str, response: dict) -> genai_types.FunctionResponse:
    return genai_types.FunctionResponse(name=name, response=response)


def _final_json(**kwargs: object) -> str:
    defaults: dict[str, object] = {
        "questions_for_user": [],
        "priority_question": "",
        "reasoning_summary": "",
        "briefing_mode": False,
    }
    defaults.update(kwargs)
    return json.dumps(defaults)


def _empty_ctx() -> dict:
    return {"things": [], "relationships": [], "count": 0}


def _things_ctx(*things: dict) -> dict:
    return {"things": list(things), "count": len(things)}


# Shared date prefix for user prompts
_DATE_PREFIX = "Today's date: 2026-03-18 (Wednesday)\n\n"


def _reasoning_prompt(
    user_msg: str, things_json: str = "[]"
) -> str:
    return (
        f"{_DATE_PREFIX}"
        f"<user_message>\n{user_msg}\n</user_message>\n\n"
        f"Relevant Things from database:\n{things_json}"
    )


# -------------------------------------------------------------------
# Reasoning Agent — Create Thing scenarios
# -------------------------------------------------------------------

_REASONING_CREATE = EvalSet(
    eval_set_id="reasoning-create-thing",
    name="Reasoning Agent — Create Thing",
    description="Golden dataset: creating Things with various attributes",
    eval_cases=[
        # Simple task creation
        EvalCase(
            eval_id="create-simple-task",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt("Buy groceries")
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary="Created a grocery task."
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": (
                                    '["groceries", "buy groceries"]'
                                ),
                            }),
                            _fc("create_thing", {
                                "title": "Buy groceries",
                                "type_hint": "task",
                                "priority": 3,
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _empty_ctx()),
                            _fr("create_thing", {
                                "id": "eval-thing-0001",
                                "title": "Buy groceries",
                                "type_hint": "task",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Create with data_json
        EvalCase(
            eval_id="create-thing-with-data",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "I have a dentist appointment "
                            "on April 5th at 2pm"
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Created dentist appointment "
                                "with date details."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": (
                                    '["dentist", "appointment"]'
                                ),
                            }),
                            _fc("create_thing", {
                                "title": "Dentist appointment",
                                "type_hint": "event",
                                "data_json": json.dumps({
                                    "date": "2026-04-05",
                                    "time": "14:00",
                                    "notes": "Dentist appointment",
                                }),
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _empty_ctx()),
                            _fr("create_thing", {
                                "id": "eval-thing-0002",
                                "title": "Dentist appointment",
                                "type_hint": "event",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Create with relationships (person entity)
        EvalCase(
            eval_id="create-thing-with-relationship",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Meeting with Sarah about the "
                            "budget project",
                            things_json=json.dumps([{
                                "id": "user-001",
                                "title": "User",
                                "type_hint": "person",
                            }]),
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Created meeting and Sarah entity, "
                                "linked them."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "Sarah",
                                    "budget project",
                                    "meeting",
                                ]),
                            }),
                            _fc("create_thing", {
                                "title": "Sarah",
                                "type_hint": "person",
                                "surface": False,
                            }),
                            _fc("create_thing", {
                                "title": (
                                    "Meeting with Sarah about "
                                    "budget project"
                                ),
                                "type_hint": "event",
                            }),
                            _fc("create_relationship", {
                                "from_thing_id": "eval-thing-0001",
                                "to_thing_id": "eval-thing-0002",
                                "relationship_type": "involves",
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _empty_ctx()),
                            _fr("create_thing", {
                                "id": "eval-thing-0001",
                                "title": "Sarah",
                                "type_hint": "person",
                            }),
                            _fr("create_thing", {
                                "id": "eval-thing-0002",
                                "title": (
                                    "Meeting with Sarah about "
                                    "budget project"
                                ),
                                "type_hint": "event",
                            }),
                            _fr("create_relationship", {
                                "from_thing_id": "eval-thing-0001",
                                "to_thing_id": "eval-thing-0002",
                                "relationship_type": "involves",
                            }),
                        ],
                    ),
                ),
            ],
        ),
    ],
)

# -------------------------------------------------------------------
# Reasoning Agent — Update Thing scenarios
# -------------------------------------------------------------------

_GROCERY_THING = json.dumps([{
    "id": "thing-100",
    "title": "Buy groceries",
    "type_hint": "task",
    "active": 1,
}])

_DENTIST_THING = json.dumps([{
    "id": "thing-200",
    "title": "Dentist appointment",
    "type_hint": "event",
    "priority": 3,
    "active": 1,
}])

_BUDGET_THING = json.dumps([{
    "id": "thing-300",
    "title": "Budget project",
    "type_hint": "project",
    "data": "{}",
    "active": 1,
}])

_REASONING_UPDATE = EvalSet(
    eval_set_id="reasoning-update-thing",
    name="Reasoning Agent — Update Thing",
    description=(
        "Golden dataset: updating existing Things "
        "(title, notes, priority, data fields)"
    ),
    eval_cases=[
        # Update title
        EvalCase(
            eval_id="update-thing-title",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Rename my grocery task to "
                            "'Weekly grocery shopping'",
                            things_json=_GROCERY_THING,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary="Renamed grocery task."
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": (
                                    '["groceries", "grocery"]'
                                ),
                            }),
                            _fc("update_thing", {
                                "thing_id": "thing-100",
                                "title": "Weekly grocery shopping",
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _things_ctx(
                                {"id": "thing-100", "title": "Buy groceries"},
                            )),
                            _fr("update_thing", {
                                "id": "thing-100",
                                "title": "Weekly grocery shopping",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Mark task done (active=false)
        EvalCase(
            eval_id="update-thing-complete",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "I finished the grocery shopping",
                            things_json=_GROCERY_THING,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Marked grocery task as done."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": (
                                    '["grocery shopping", "groceries"]'
                                ),
                            }),
                            _fc("update_thing", {
                                "thing_id": "thing-100",
                                "active": False,
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _things_ctx(
                                {"id": "thing-100", "title": "Buy groceries"},
                            )),
                            _fr("update_thing", {
                                "id": "thing-100",
                                "active": False,
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Update priority
        EvalCase(
            eval_id="update-thing-priority",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Make the dentist appointment "
                            "high priority",
                            things_json=_DENTIST_THING,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Updated dentist appointment "
                                "to high priority."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": (
                                    '["dentist appointment"]'
                                ),
                            }),
                            _fc("update_thing", {
                                "thing_id": "thing-200",
                                "priority": 1,
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _things_ctx({
                                "id": "thing-200",
                                "title": "Dentist appointment",
                            })),
                            _fr("update_thing", {
                                "id": "thing-200",
                                "priority": 1,
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Update data fields
        EvalCase(
            eval_id="update-thing-data",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Add a note to the budget project: "
                            "Q2 deadline is June 30",
                            things_json=_BUDGET_THING,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Added Q2 deadline note "
                                "to budget project."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": (
                                    '["budget project"]'
                                ),
                            }),
                            _fc("update_thing", {
                                "thing_id": "thing-300",
                                "data_json": json.dumps({
                                    "notes": (
                                        "Q2 deadline is June 30"
                                    ),
                                    "deadline": "2026-06-30",
                                }),
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _things_ctx({
                                "id": "thing-300",
                                "title": "Budget project",
                            })),
                            _fr("update_thing", {
                                "id": "thing-300",
                                "title": "Budget project",
                            }),
                        ],
                    ),
                ),
            ],
        ),
    ],
)

# -------------------------------------------------------------------
# Reasoning Agent — Delete Thing scenarios
# -------------------------------------------------------------------

_VACATION_THING = json.dumps([{
    "id": "thing-400",
    "title": "Vacation plan 2025",
    "type_hint": "project",
    "active": 1,
}])

_REASONING_DELETE = EvalSet(
    eval_set_id="reasoning-delete-thing",
    name="Reasoning Agent — Delete Thing",
    description="Golden dataset: deleting Things",
    eval_cases=[
        EvalCase(
            eval_id="delete-thing-simple",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Delete my old vacation plan",
                            things_json=_VACATION_THING,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Deleted old vacation plan."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": (
                                    '["vacation plan"]'
                                ),
                            }),
                            _fc("delete_thing", {
                                "thing_id": "thing-400",
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _things_ctx({
                                "id": "thing-400",
                                "title": "Vacation plan 2025",
                            })),
                            _fr("delete_thing", {
                                "deleted": "thing-400",
                                "title": "Vacation plan 2025",
                            }),
                        ],
                    ),
                ),
            ],
        ),
    ],
)

# -------------------------------------------------------------------
# Reasoning Agent — Merge Things scenarios
# -------------------------------------------------------------------

_MERGE_THINGS = json.dumps([
    {
        "id": "thing-500",
        "title": "Buy groceries",
        "type_hint": "task",
        "data": '{"store": "Trader Joe\'s"}',
        "active": 1,
    },
    {
        "id": "thing-501",
        "title": "Grocery shopping",
        "type_hint": "task",
        "data": '{"notes": "weekly"}',
        "active": 1,
    },
])

_REASONING_MERGE = EvalSet(
    eval_set_id="reasoning-merge-things",
    name="Reasoning Agent — Merge Things",
    description="Golden dataset: merging duplicate Things",
    eval_cases=[
        EvalCase(
            eval_id="merge-duplicate-tasks",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Those two grocery tasks are the "
                            "same thing, merge them",
                            things_json=_MERGE_THINGS,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Merged duplicate grocery tasks."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": (
                                    '["groceries", "grocery"]'
                                ),
                            }),
                            _fc("merge_things", {
                                "keep_id": "thing-500",
                                "remove_id": "thing-501",
                                "merged_data_json": json.dumps({
                                    "store": "Trader Joe's",
                                    "notes": "weekly",
                                }),
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _things_ctx(
                                {"id": "thing-500"},
                                {"id": "thing-501"},
                            )),
                            _fr("merge_things", {
                                "keep_id": "thing-500",
                                "remove_id": "thing-501",
                            }),
                        ],
                    ),
                ),
            ],
        ),
    ],
)

# -------------------------------------------------------------------
# Reasoning Agent — Multi-step scenarios
# -------------------------------------------------------------------

_JAPAN_THING = json.dumps([{
    "id": "thing-600",
    "title": "Japan trip",
    "type_hint": "project",
    "open_questions": json.dumps([
        "When are you planning to travel?",
        "What is your budget?",
    ]),
    "data": "{}",
    "active": 1,
}])

_REASONING_MULTISTEP = EvalSet(
    eval_set_id="reasoning-multi-step",
    name="Reasoning Agent — Multi-Step",
    description=(
        "Golden dataset: multi-step scenarios "
        "(create then update, etc.)"
    ),
    eval_cases=[
        # Create a project then add sub-tasks
        EvalCase(
            eval_id="create-project-with-subtask",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "I want to plan a trip to Japan. "
                            "I need to book flights and "
                            "find hotels."
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Created Japan trip project with "
                                "flight and hotel sub-tasks."
                            ),
                            questions_for_user=[
                                "When are you planning to travel?",
                                "What's your budget?",
                            ],
                            priority_question=(
                                "When are you planning to travel?"
                            ),
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "Japan", "trip", "travel",
                                ]),
                            }),
                            _fc("create_thing", {
                                "title": "Japan trip",
                                "type_hint": "project",
                                "priority": 2,
                                "open_questions_json": json.dumps([
                                    "When are you planning "
                                    "to travel?",
                                    "What is your budget?",
                                ]),
                            }),
                            _fc("create_thing", {
                                "title": "Book flights to Japan",
                                "type_hint": "task",
                                "priority": 2,
                            }),
                            _fc("create_thing", {
                                "title": "Find hotels in Japan",
                                "type_hint": "task",
                                "priority": 2,
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _empty_ctx()),
                            _fr("create_thing", {
                                "id": "eval-thing-0010",
                                "title": "Japan trip",
                                "type_hint": "project",
                            }),
                            _fr("create_thing", {
                                "id": "eval-thing-0011",
                                "title": "Book flights to Japan",
                                "type_hint": "task",
                            }),
                            _fr("create_thing", {
                                "id": "eval-thing-0012",
                                "title": "Find hotels in Japan",
                                "type_hint": "task",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Answering an open question then updating
        EvalCase(
            eval_id="answer-open-question-update",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "The Japan trip will be in October, "
                            "budget is $5000",
                            things_json=_JAPAN_THING,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Updated Japan trip with travel "
                                "dates and budget."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": (
                                    '["Japan trip"]'
                                ),
                            }),
                            _fc("update_thing", {
                                "thing_id": "thing-600",
                                "data_json": json.dumps({
                                    "travel_month": "October 2026",
                                    "budget": "$5000",
                                }),
                                "open_questions_json": "[]",
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _things_ctx({
                                "id": "thing-600",
                                "title": "Japan trip",
                            })),
                            _fr("update_thing", {
                                "id": "thing-600",
                                "title": "Japan trip",
                            }),
                        ],
                    ),
                ),
            ],
        ),
    ],
)

# -------------------------------------------------------------------
# Context Agent — Search param generation
# -------------------------------------------------------------------

_CONTEXT_SEARCH = EvalSet(
    eval_set_id="context-search-params",
    name="Context Agent — Search Param Generation",
    description=(
        "Golden dataset: context agent generating "
        "search queries and filter params"
    ),
    eval_cases=[
        EvalCase(
            eval_id="context-simple-query",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        "What are my tasks for this week?"
                    ),
                    final_response=_model(json.dumps({
                        "search_queries": [
                            "tasks", "this week", "weekly tasks",
                        ],
                        "filter_params": {
                            "active_only": True,
                            "type_hint": "task",
                        },
                    })),
                ),
            ],
        ),
        EvalCase(
            eval_id="context-person-query",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        "Conversation history:\n"
                        "<user>Tell me about Sarah</user>\n\n"
                        "Current user message: "
                        "What do I know about Sarah?"
                    ),
                    final_response=_model(json.dumps({
                        "search_queries": ["Sarah"],
                        "filter_params": {
                            "active_only": False,
                            "type_hint": None,
                        },
                    })),
                ),
            ],
        ),
        EvalCase(
            eval_id="context-multi-topic",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        "Show me everything about the Japan "
                        "trip and the budget project"
                    ),
                    final_response=_model(json.dumps({
                        "search_queries": [
                            "Japan trip", "budget project",
                        ],
                        "filter_params": {
                            "active_only": False,
                            "type_hint": None,
                        },
                    })),
                ),
            ],
        ),
        EvalCase(
            eval_id="context-completed-items",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        "What have I finished recently?"
                    ),
                    final_response=_model(json.dumps({
                        "search_queries": [
                            "completed", "finished", "done",
                        ],
                        "filter_params": {
                            "active_only": False,
                            "type_hint": None,
                        },
                    })),
                ),
            ],
        ),
        EvalCase(
            eval_id="context-type-filter",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user("Show me all my notes"),
                    final_response=_model(json.dumps({
                        "search_queries": ["notes"],
                        "filter_params": {
                            "active_only": True,
                            "type_hint": "note",
                        },
                    })),
                ),
            ],
        ),
    ],
)


# -------------------------------------------------------------------
# Reasoning Agent — Preference detection scenarios
# -------------------------------------------------------------------

# Existing scheduling preference (for reinforcement scenarios)
_SCHED_PREF = json.dumps([{
    "id": "pref-100",
    "title": "Scheduling preferences",
    "type_hint": "preference",
    "data": json.dumps({
        "patterns": [{
            "pattern": "Avoids morning meetings",
            "confidence": "emerging",
            "observations": 1,
            "first_observed": "2026-03-10",
            "last_observed": "2026-03-10",
        }],
    }),
    "active": 1,
}])

# Morning meeting Thing (for action + preference scenario)
_MORNING_MEETING = json.dumps([{
    "id": "thing-700",
    "title": "Team standup",
    "type_hint": "event",
    "data": json.dumps({"time": "09:00", "day": "Monday"}),
    "active": 1,
}])

# Travel Things (for inferred preference from pattern)
_TRAVEL_BOOKINGS = json.dumps([
    {
        "id": "thing-800",
        "title": "Flight to NYC",
        "type_hint": "task",
        "data": json.dumps({"airline": "Budget Air", "cost": "$120"}),
        "active": 1,
    },
    {
        "id": "thing-801",
        "title": "Flight to LA",
        "type_hint": "task",
        "data": json.dumps({"airline": "Budget Air", "cost": "$95"}),
        "active": 1,
    },
])

_REASONING_PREFERENCES = EvalSet(
    eval_set_id="reasoning-preference-detection",
    name="Reasoning Agent — Preference Detection",
    description=(
        "Golden dataset: detecting and creating/updating "
        "user preference Things from explicit statements "
        "and behavioral patterns"
    ),
    eval_cases=[
        # Explicit preference — direct statement creates new preference
        EvalCase(
            eval_id="preference-explicit-new",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "I hate morning meetings, they ruin "
                            "my focus time"
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Noted preference: avoids morning "
                                "meetings to protect focus time."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "morning meetings",
                                    "scheduling preferences",
                                    "preferences",
                                ]),
                            }),
                            _fc("create_thing", {
                                "title": "Scheduling preferences",
                                "type_hint": "preference",
                                "data_json": json.dumps({
                                    "patterns": [{
                                        "pattern": (
                                            "Avoids morning meetings"
                                        ),
                                        "confidence": "emerging",
                                        "observations": 1,
                                        "first_observed": "2026-03-18",
                                        "last_observed": "2026-03-18",
                                    }],
                                }),
                                "surface": False,
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _empty_ctx()),
                            _fr("create_thing", {
                                "id": "eval-pref-0001",
                                "title": "Scheduling preferences",
                                "type_hint": "preference",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Explicit preference alongside an action — update meeting
        # AND record preference
        EvalCase(
            eval_id="preference-explicit-with-action",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Move the team standup to afternoon, "
                            "I hate morning meetings",
                            things_json=_MORNING_MEETING,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Moved standup to afternoon and "
                                "noted morning meeting preference."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "team standup",
                                    "morning meetings",
                                    "scheduling preferences",
                                ]),
                            }),
                            _fc("update_thing", {
                                "thing_id": "thing-700",
                                "data_json": json.dumps({
                                    "time": "14:00",
                                    "day": "Monday",
                                    "notes": (
                                        "Moved from morning to "
                                        "afternoon"
                                    ),
                                }),
                            }),
                            _fc("create_thing", {
                                "title": "Scheduling preferences",
                                "type_hint": "preference",
                                "data_json": json.dumps({
                                    "patterns": [{
                                        "pattern": (
                                            "Avoids morning meetings"
                                        ),
                                        "confidence": "emerging",
                                        "observations": 1,
                                        "first_observed": "2026-03-18",
                                        "last_observed": "2026-03-18",
                                    }],
                                }),
                                "surface": False,
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _things_ctx(
                                {
                                    "id": "thing-700",
                                    "title": "Team standup",
                                },
                            )),
                            _fr("update_thing", {
                                "id": "thing-700",
                                "title": "Team standup",
                            }),
                            _fr("create_thing", {
                                "id": "eval-pref-0002",
                                "title": "Scheduling preferences",
                                "type_hint": "preference",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Reinforcement — existing preference gains confidence
        EvalCase(
            eval_id="preference-reinforcement",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Move that 8am call to after lunch, "
                            "mornings don't work for me",
                            things_json=_SCHED_PREF,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Reinforced morning meeting "
                                "avoidance preference."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "8am call",
                                    "morning meetings",
                                    "scheduling preferences",
                                ]),
                            }),
                            _fc("update_thing", {
                                "thing_id": "pref-100",
                                "data_json": json.dumps({
                                    "patterns": [{
                                        "pattern": (
                                            "Avoids morning meetings"
                                        ),
                                        "confidence": "moderate",
                                        "observations": 2,
                                        "first_observed": "2026-03-10",
                                        "last_observed": "2026-03-18",
                                    }],
                                }),
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _things_ctx(
                                {
                                    "id": "pref-100",
                                    "title": "Scheduling preferences",
                                    "type_hint": "preference",
                                },
                            )),
                            _fr("update_thing", {
                                "id": "pref-100",
                                "title": "Scheduling preferences",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Inferred preference — pattern from behavior
        EvalCase(
            eval_id="preference-inferred-pattern",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Cancel both of those Budget Air "
                            "flights and rebook with a real "
                            "airline. I always end up delayed "
                            "with them.",
                            things_json=_TRAVEL_BOOKINGS,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Cancelled Budget Air flights and "
                                "noted preference against budget "
                                "airlines."
                            ),
                            questions_for_user=[
                                "Which airline would you prefer "
                                "for the rebooking?",
                            ],
                            priority_question=(
                                "Which airline would you prefer "
                                "for the rebooking?"
                            ),
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "Budget Air flights",
                                    "travel preferences",
                                    "airline",
                                ]),
                            }),
                            _fc("delete_thing", {
                                "thing_id": "thing-800",
                            }),
                            _fc("delete_thing", {
                                "thing_id": "thing-801",
                            }),
                            _fc("create_thing", {
                                "title": "Travel preferences",
                                "type_hint": "preference",
                                "data_json": json.dumps({
                                    "patterns": [{
                                        "pattern": (
                                            "Avoids budget airlines "
                                            "(delays)"
                                        ),
                                        "confidence": "moderate",
                                        "observations": 2,
                                        "first_observed": "2026-03-18",
                                        "last_observed": "2026-03-18",
                                    }],
                                }),
                                "surface": False,
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _things_ctx(
                                {"id": "thing-800",
                                 "title": "Flight to NYC"},
                                {"id": "thing-801",
                                 "title": "Flight to LA"},
                            )),
                            _fr("delete_thing", {
                                "deleted": "thing-800",
                                "title": "Flight to NYC",
                            }),
                            _fr("delete_thing", {
                                "deleted": "thing-801",
                                "title": "Flight to LA",
                            }),
                            _fr("create_thing", {
                                "id": "eval-pref-0003",
                                "title": "Travel preferences",
                                "type_hint": "preference",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Negative preference — explicit avoidance
        EvalCase(
            eval_id="preference-negative-explicit",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Just book the cheap one. I always "
                            "go with the cheapest option for "
                            "work travel."
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Noted cost optimization preference "
                                "for work travel."
                            ),
                            questions_for_user=[
                                "What are you booking?",
                            ],
                            priority_question=(
                                "What are you booking?"
                            ),
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "work travel",
                                    "travel preferences",
                                    "booking",
                                ]),
                            }),
                            _fc("create_thing", {
                                "title": "Travel preferences",
                                "type_hint": "preference",
                                "data_json": json.dumps({
                                    "patterns": [{
                                        "pattern": (
                                            "Optimizes for cost "
                                            "on work travel"
                                        ),
                                        "confidence": "strong",
                                        "observations": 1,
                                        "first_observed": "2026-03-18",
                                        "last_observed": "2026-03-18",
                                    }],
                                }),
                                "surface": False,
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _empty_ctx()),
                            _fr("create_thing", {
                                "id": "eval-pref-0004",
                                "title": "Travel preferences",
                                "type_hint": "preference",
                            }),
                        ],
                    ),
                ),
            ],
        ),
    ],
)

# -------------------------------------------------------------------
# Reasoning Agent — Thought Signature regression (Gemini 3 Flash)
# -------------------------------------------------------------------
# Gemini 3 Flash thinking models require a thought_signature in
# functionCall parts for multi-turn tool-calling conversations.  If ADK
# strips the thought_signature when reconstructing message history, the
# model returns a 400 error.  This eval exercises a consecutive
# fetch_context -> create_thing -> update_thing tool chain to reproduce
# the failure.

_REASONING_THOUGHT_SIGNATURE = EvalSet(
    eval_set_id="reasoning-thought-signature-tool-chain",
    name="Reasoning Agent — Thought Signature Tool Chain",
    description=(
        "Regression dataset: consecutive tool calls that trigger the "
        "Gemini 3 Flash thought_signature requirement.  Exercises "
        "fetch_context -> create_thing -> update_thing in sequence."
    ),
    eval_cases=[
        # Consecutive tool chain: fetch -> create -> update
        EvalCase(
            eval_id="thought-signature-tool-chain",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Create a new project called "
                            "'Home renovation' and immediately "
                            "set it to high priority with a note "
                            "about getting contractor quotes"
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Created home renovation project "
                                "and set it to high priority with "
                                "contractor quote note."
                            ),
                            questions_for_user=[
                                "What's your budget for "
                                "the renovation?",
                            ],
                            priority_question=(
                                "What's your budget for "
                                "the renovation?"
                            ),
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "home renovation",
                                    "renovation project",
                                    "contractor",
                                ]),
                            }),
                            _fc("create_thing", {
                                "title": "Home renovation",
                                "type_hint": "project",
                                "priority": 3,
                                "open_questions_json": json.dumps([
                                    "What is the budget?",
                                    "Which rooms to renovate?",
                                ]),
                            }),
                            _fc("update_thing", {
                                "thing_id": "eval-thing-0001",
                                "priority": 1,
                                "data_json": json.dumps({
                                    "notes": (
                                        "Get contractor quotes "
                                        "before starting"
                                    ),
                                }),
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _empty_ctx()),
                            _fr("create_thing", {
                                "id": "eval-thing-0001",
                                "title": "Home renovation",
                                "type_hint": "project",
                            }),
                            _fr("update_thing", {
                                "id": "eval-thing-0001",
                                "title": "Home renovation",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Multi-turn: create two things then link them
        EvalCase(
            eval_id="thought-signature-create-and-link",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "I have a meeting with the plumber "
                            "on Friday about the bathroom remodel. "
                            "Track both the plumber contact and "
                            "the meeting."
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Created plumber contact and "
                                "meeting, linked them together."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "plumber",
                                    "bathroom remodel",
                                    "meeting",
                                ]),
                            }),
                            _fc("create_thing", {
                                "title": "Plumber",
                                "type_hint": "person",
                                "surface": False,
                            }),
                            _fc("create_thing", {
                                "title": (
                                    "Meeting with plumber about "
                                    "bathroom remodel"
                                ),
                                "type_hint": "event",
                                "data_json": json.dumps({
                                    "date": "2026-03-27",
                                    "notes": "Bathroom remodel",
                                }),
                            }),
                            _fc("create_relationship", {
                                "from_thing_id": "eval-thing-0001",
                                "to_thing_id": "eval-thing-0002",
                                "relationship_type": "involves",
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _empty_ctx()),
                            _fr("create_thing", {
                                "id": "eval-thing-0001",
                                "title": "Plumber",
                                "type_hint": "person",
                            }),
                            _fr("create_thing", {
                                "id": "eval-thing-0002",
                                "title": (
                                    "Meeting with plumber about "
                                    "bathroom remodel"
                                ),
                                "type_hint": "event",
                            }),
                            _fr("create_relationship", {
                                "from_thing_id": "eval-thing-0001",
                                "to_thing_id": "eval-thing-0002",
                                "relationship_type": "involves",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Sequential: fetch context with results, then create + update
        EvalCase(
            eval_id="thought-signature-fetch-create-update-sequence",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Add a 'Get paint samples' task to my "
                            "home renovation project and mark the "
                            "existing 'Choose wall colors' task done",
                            things_json=json.dumps([
                                {
                                    "id": "thing-500",
                                    "title": "Home renovation",
                                    "type_hint": "project",
                                    "active": 1,
                                },
                                {
                                    "id": "thing-501",
                                    "title": "Choose wall colors",
                                    "type_hint": "task",
                                    "active": 1,
                                },
                            ]),
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Created paint samples task, marked "
                                "wall colors task done, linked new "
                                "task to renovation project."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "home renovation",
                                    "paint samples",
                                    "wall colors",
                                ]),
                            }),
                            _fc("create_thing", {
                                "title": "Get paint samples",
                                "type_hint": "task",
                                "priority": 2,
                            }),
                            _fc("update_thing", {
                                "thing_id": "thing-501",
                                "active": False,
                            }),
                            _fc("create_relationship", {
                                "from_thing_id": "thing-500",
                                "to_thing_id": "eval-thing-0001",
                                "relationship_type": "subtask",
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _things_ctx(
                                {
                                    "id": "thing-500",
                                    "title": "Home renovation",
                                },
                                {
                                    "id": "thing-501",
                                    "title": "Choose wall colors",
                                },
                            )),
                            _fr("create_thing", {
                                "id": "eval-thing-0001",
                                "title": "Get paint samples",
                                "type_hint": "task",
                            }),
                            _fr("update_thing", {
                                "id": "thing-501",
                                "active": False,
                            }),
                            _fr("create_relationship", {
                                "from_thing_id": "thing-500",
                                "to_thing_id": "eval-thing-0001",
                                "relationship_type": "subtask",
                            }),
                        ],
                    ),
                ),
            ],
        ),
    ],
)


# -------------------------------------------------------------------
# Writer
# -------------------------------------------------------------------


def _write(eval_set: EvalSet, path: pathlib.Path) -> None:
    path.write_text(eval_set.model_dump_json(indent=2) + "\n")
    print(f"  wrote {path.relative_to(HERE.parent)}")


def main() -> None:
    reasoning_dir = HERE / "reasoning_agent"
    context_dir = HERE / "context_agent"

    print("Generating golden datasets …")
    _write(_REASONING_CREATE, reasoning_dir / "create_thing.test.json")
    _write(_REASONING_UPDATE, reasoning_dir / "update_thing.test.json")
    _write(_REASONING_DELETE, reasoning_dir / "delete_thing.test.json")
    _write(_REASONING_MERGE, reasoning_dir / "merge_things.test.json")
    _write(
        _REASONING_MULTISTEP, reasoning_dir / "multi_step.test.json"
    )
    _write(
        _REASONING_PREFERENCES,
        reasoning_dir / "preference_detection.test.json",
    )
    _write(
        _REASONING_THOUGHT_SIGNATURE,
        reasoning_dir / "thought_signature_tool_chain.test.json",
    )
    _write(_CONTEXT_SEARCH, context_dir / "search_params.test.json")
    print("Done.")


if __name__ == "__main__":
    main()
