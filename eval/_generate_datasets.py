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
# Preference Detection — Explicit preferences
# -------------------------------------------------------------------

# User entity (always first in Relevant Things for possessive patterns)
_USER_THING = json.dumps([{
    "id": "user-001",
    "title": "User",
    "type_hint": "person",
}])

# Existing preference to test dedup / update
_EXISTING_PREFS = json.dumps([
    {
        "id": "user-001",
        "title": "User",
        "type_hint": "person",
    },
    {
        "id": "pref-100",
        "title": "Prefers afternoon meetings",
        "type_hint": "preference",
        "data": '{"category": "scheduling", "detail": "Prefers meetings in the afternoon"}',
        "active": 1,
    },
])

_PREF_EXPLICIT = EvalSet(
    eval_set_id="preference-explicit",
    name="Preference Detection — Explicit Statements",
    description=(
        "Golden dataset: detecting explicit preference statements "
        "and storing them as preference Things"
    ),
    eval_cases=[
        # Simple negative preference
        EvalCase(
            eval_id="explicit-dislike-morning-meetings",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "I hate morning meetings, they ruin my focus",
                            things_json=_USER_THING,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Detected scheduling preference: "
                                "user dislikes morning meetings."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "morning meetings",
                                    "meeting preference",
                                    "scheduling preference",
                                ]),
                            }),
                            _fc("create_thing", {
                                "title": "Dislikes morning meetings",
                                "type_hint": "preference",
                                "surface": False,
                                "data_json": json.dumps({
                                    "category": "scheduling",
                                    "detail": (
                                        "Hates morning meetings — "
                                        "they ruin focus"
                                    ),
                                    "sentiment": "negative",
                                }),
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _empty_ctx()),
                            _fr("create_thing", {
                                "id": "eval-pref-0001",
                                "title": "Dislikes morning meetings",
                                "type_hint": "preference",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Positive preference with action implication
        EvalCase(
            eval_id="explicit-prefer-email-over-calls",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "I much prefer email over phone calls "
                            "for work communication",
                            things_json=_USER_THING,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Detected communication preference: "
                                "user prefers email over phone calls."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "email", "phone calls",
                                    "communication preference",
                                ]),
                            }),
                            _fc("create_thing", {
                                "title": "Prefers email over phone calls",
                                "type_hint": "preference",
                                "surface": False,
                                "data_json": json.dumps({
                                    "category": "communication",
                                    "detail": (
                                        "Prefers email over phone calls "
                                        "for work communication"
                                    ),
                                    "sentiment": "positive",
                                }),
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _empty_ctx()),
                            _fr("create_thing", {
                                "id": "eval-pref-0002",
                                "title": (
                                    "Prefers email over phone calls"
                                ),
                                "type_hint": "preference",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Preference embedded in a task request
        EvalCase(
            eval_id="explicit-preference-in-task",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Schedule my workout for 6am — "
                            "I always exercise before work",
                            things_json=_USER_THING,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Created workout task and noted "
                                "early-morning exercise preference."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "workout", "exercise",
                                    "morning routine",
                                ]),
                            }),
                            _fc("create_thing", {
                                "title": "Workout",
                                "type_hint": "task",
                                "data_json": json.dumps({
                                    "time": "06:00",
                                    "notes": "Before work",
                                }),
                            }),
                            _fc("create_thing", {
                                "title": "Exercises before work",
                                "type_hint": "preference",
                                "surface": False,
                                "data_json": json.dumps({
                                    "category": "routine",
                                    "detail": (
                                        "Always exercises before work, "
                                        "prefers 6am"
                                    ),
                                }),
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _empty_ctx()),
                            _fr("create_thing", {
                                "id": "eval-pref-0003",
                                "title": "Workout",
                                "type_hint": "task",
                            }),
                            _fr("create_thing", {
                                "id": "eval-pref-0004",
                                "title": "Exercises before work",
                                "type_hint": "preference",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Update existing preference (dedup)
        EvalCase(
            eval_id="explicit-update-existing-preference",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Actually, I'm fine with morning meetings "
                            "now — just not before 9am",
                            things_json=_EXISTING_PREFS,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Updated scheduling preference: "
                                "morning meetings OK after 9am."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "morning meetings",
                                    "meeting preference",
                                ]),
                            }),
                            _fc("update_thing", {
                                "thing_id": "pref-100",
                                "title": "No meetings before 9am",
                                "data_json": json.dumps({
                                    "category": "scheduling",
                                    "detail": (
                                        "OK with morning meetings "
                                        "but not before 9am"
                                    ),
                                }),
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _things_ctx({
                                "id": "pref-100",
                                "title": "Prefers afternoon meetings",
                            })),
                            _fr("update_thing", {
                                "id": "pref-100",
                                "title": "No meetings before 9am",
                            }),
                        ],
                    ),
                ),
            ],
        ),
    ],
)

# -------------------------------------------------------------------
# Preference Detection — Inferred from behavioral patterns
# -------------------------------------------------------------------

# Things showing a behavioral pattern — user always defers tasks with
# specific characteristics.
_REPEATED_DEFER = json.dumps([
    {
        "id": "user-001",
        "title": "User",
        "type_hint": "person",
    },
    {
        "id": "thing-700",
        "title": "Clean garage",
        "type_hint": "task",
        "priority": 3,
        "active": 1,
        "data": json.dumps({
            "deferred_count": 3,
            "last_deferred": "2026-03-15",
        }),
    },
])

# Things showing a pattern of always setting high priority on health items
_HEALTH_PATTERN = json.dumps([
    {
        "id": "user-001",
        "title": "User",
        "type_hint": "person",
    },
    {
        "id": "thing-800",
        "title": "Annual physical",
        "type_hint": "task",
        "priority": 1,
        "active": 1,
    },
    {
        "id": "thing-801",
        "title": "Dentist checkup",
        "type_hint": "task",
        "priority": 1,
        "active": 0,
    },
    {
        "id": "thing-802",
        "title": "Eye exam",
        "type_hint": "task",
        "priority": 1,
        "active": 0,
    },
])

# Conversation history showing a consistent time-of-day pattern
_EVENING_PATTERN_THINGS = json.dumps([
    {
        "id": "user-001",
        "title": "User",
        "type_hint": "person",
    },
])

_PREF_INFERRED = EvalSet(
    eval_set_id="preference-inferred",
    name="Preference Detection — Inferred from Behavior",
    description=(
        "Golden dataset: inferring preferences from behavioral patterns "
        "(repeated deferrals, consistent prioritization, time patterns)"
    ),
    eval_cases=[
        # Infer avoidance from repeated deferrals
        EvalCase(
            eval_id="inferred-repeated-deferral",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Push the garage cleaning to next week again",
                            things_json=_REPEATED_DEFER,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Deferred garage cleaning again "
                                "(4th time). Noted recurring "
                                "deferral pattern."
                            ),
                            questions_for_user=[
                                "You've deferred this task several "
                                "times — would you like to break it "
                                "into smaller steps, or remove it "
                                "entirely?"
                            ],
                            priority_question=(
                                "You've deferred this task several "
                                "times — would you like to break it "
                                "into smaller steps, or remove it "
                                "entirely?"
                            ),
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "garage cleaning", "clean garage",
                                ]),
                            }),
                            _fc("update_thing", {
                                "thing_id": "thing-700",
                                "data_json": json.dumps({
                                    "deferred_count": 4,
                                    "last_deferred": "2026-03-22",
                                }),
                                "checkin_date": "2026-03-29",
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _things_ctx({
                                "id": "thing-700",
                                "title": "Clean garage",
                            })),
                            _fr("update_thing", {
                                "id": "thing-700",
                                "title": "Clean garage",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Infer priority pattern from health-related items
        EvalCase(
            eval_id="inferred-health-priority-pattern",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "I need to book a dermatologist appointment",
                            things_json=_HEALTH_PATTERN,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Created dermatologist task with "
                                "high priority, matching user's "
                                "pattern of prioritizing health "
                                "appointments."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "dermatologist",
                                    "doctor appointment",
                                    "health",
                                ]),
                            }),
                            _fc("create_thing", {
                                "title": "Book dermatologist appointment",
                                "type_hint": "task",
                                "priority": 1,
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _things_ctx(
                                {
                                    "id": "thing-800",
                                    "title": "Annual physical",
                                    "priority": 1,
                                },
                                {
                                    "id": "thing-801",
                                    "title": "Dentist checkup",
                                    "priority": 1,
                                },
                                {
                                    "id": "thing-802",
                                    "title": "Eye exam",
                                    "priority": 1,
                                },
                            )),
                            _fr("create_thing", {
                                "id": "eval-pref-0010",
                                "title": (
                                    "Book dermatologist appointment"
                                ),
                                "type_hint": "task",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Infer time-of-day preference from conversation pattern
        EvalCase(
            eval_id="inferred-evening-planner",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "Add 'review tomorrow's agenda' to my "
                            "evening routine — I always plan the "
                            "next day at night",
                            things_json=_EVENING_PATTERN_THINGS,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Created evening routine task and "
                                "noted planning preference."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "evening routine",
                                    "tomorrow agenda",
                                    "planning",
                                ]),
                            }),
                            _fc("create_thing", {
                                "title": "Review tomorrow's agenda",
                                "type_hint": "task",
                                "data_json": json.dumps({
                                    "notes": "Evening routine task",
                                    "recurring": "daily",
                                    "time": "evening",
                                }),
                            }),
                            _fc("create_thing", {
                                "title": "Plans next day in the evening",
                                "type_hint": "preference",
                                "surface": False,
                                "data_json": json.dumps({
                                    "category": "routine",
                                    "detail": (
                                        "Always plans the next day "
                                        "at night"
                                    ),
                                }),
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _empty_ctx()),
                            _fr("create_thing", {
                                "id": "eval-pref-0011",
                                "title": "Review tomorrow's agenda",
                                "type_hint": "task",
                            }),
                            _fr("create_thing", {
                                "id": "eval-pref-0012",
                                "title": (
                                    "Plans next day in the evening"
                                ),
                                "type_hint": "preference",
                            }),
                        ],
                    ),
                ),
            ],
        ),
        # Infer work style from delegation language
        EvalCase(
            eval_id="inferred-delegation-preference",
            conversation=[
                Invocation(
                    invocation_id="inv-1",
                    user_content=_user(
                        _reasoning_prompt(
                            "I need to handle the client presentation "
                            "myself — I never let anyone else do "
                            "client-facing work",
                            things_json=_EVENING_PATTERN_THINGS,
                        )
                    ),
                    final_response=_model(
                        _final_json(
                            reasoning_summary=(
                                "Created presentation task and "
                                "noted preference for handling "
                                "client-facing work personally."
                            )
                        )
                    ),
                    intermediate_data=IntermediateData(
                        tool_uses=[
                            _fc("fetch_context", {
                                "search_queries_json": json.dumps([
                                    "client presentation",
                                    "client-facing",
                                    "presentation",
                                ]),
                            }),
                            _fc("create_thing", {
                                "title": "Client presentation",
                                "type_hint": "task",
                                "priority": 2,
                            }),
                            _fc("create_thing", {
                                "title": (
                                    "Handles client-facing work "
                                    "personally"
                                ),
                                "type_hint": "preference",
                                "surface": False,
                                "data_json": json.dumps({
                                    "category": "work_style",
                                    "detail": (
                                        "Never delegates client-facing "
                                        "work — prefers to handle it "
                                        "personally"
                                    ),
                                }),
                            }),
                        ],
                        tool_responses=[
                            _fr("fetch_context", _empty_ctx()),
                            _fr("create_thing", {
                                "id": "eval-pref-0013",
                                "title": "Client presentation",
                                "type_hint": "task",
                            }),
                            _fr("create_thing", {
                                "id": "eval-pref-0014",
                                "title": (
                                    "Handles client-facing work "
                                    "personally"
                                ),
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
# Writer
# -------------------------------------------------------------------


def _write(eval_set: EvalSet, path: pathlib.Path) -> None:
    path.write_text(eval_set.model_dump_json(indent=2) + "\n")
    print(f"  wrote {path.relative_to(HERE.parent)}")


def main() -> None:
    reasoning_dir = HERE / "reasoning_agent"
    context_dir = HERE / "context_agent"
    preference_dir = HERE / "preference_detection"
    preference_dir.mkdir(exist_ok=True)

    print("Generating golden datasets …")
    _write(_REASONING_CREATE, reasoning_dir / "create_thing.test.json")
    _write(_REASONING_UPDATE, reasoning_dir / "update_thing.test.json")
    _write(_REASONING_DELETE, reasoning_dir / "delete_thing.test.json")
    _write(_REASONING_MERGE, reasoning_dir / "merge_things.test.json")
    _write(
        _REASONING_MULTISTEP, reasoning_dir / "multi_step.test.json"
    )
    _write(_CONTEXT_SEARCH, context_dir / "search_params.test.json")
    _write(
        _PREF_EXPLICIT,
        preference_dir / "explicit_preferences.test.json",
    )
    _write(
        _PREF_INFERRED,
        preference_dir / "inferred_preferences.test.json",
    )
    print("Done.")


if __name__ == "__main__":
    main()
