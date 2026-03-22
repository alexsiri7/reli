"""Pytest integration for ADK eval suites.

Runs the golden-dataset evaluation for the reasoning and context agents
via ``AgentEvaluator``. These tests require a live LLM endpoint
(REQUESTY_API_KEY) and are opt-in via the ``--run-evals`` flag or the
``RUN_EVALS=1`` environment variable.

Usage:
    # Run all evals
    RUN_EVALS=1 pytest backend/tests/test_evals.py -x -v

    # Run only reasoning agent evals
    RUN_EVALS=1 pytest backend/tests/test_evals.py -x -v -k reasoning

    # Run only context agent evals
    RUN_EVALS=1 pytest backend/tests/test_evals.py -x -v -k context
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Evals hit a real LLM — skip by default unless opted in.
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_EVALS", "0") not in ("1", "true", "yes"),
    reason="Evals require RUN_EVALS=1 and a live LLM endpoint",
)

EVAL_ROOT = Path(__file__).resolve().parent.parent.parent / "eval"


@pytest.mark.asyncio
async def test_reasoning_agent_create_thing() -> None:
    """Eval: reasoning agent — create thing scenarios."""
    from google.adk.evaluation import AgentEvaluator

    await AgentEvaluator.evaluate(
        agent_module="eval.reasoning_agent.agent",
        eval_dataset_file_path_or_dir=str(EVAL_ROOT / "reasoning_agent" / "create_thing.test.json"),
        num_runs=1,
    )


@pytest.mark.asyncio
async def test_reasoning_agent_update_thing() -> None:
    """Eval: reasoning agent — update thing scenarios."""
    from google.adk.evaluation import AgentEvaluator

    await AgentEvaluator.evaluate(
        agent_module="eval.reasoning_agent.agent",
        eval_dataset_file_path_or_dir=str(EVAL_ROOT / "reasoning_agent" / "update_thing.test.json"),
        num_runs=1,
    )


@pytest.mark.asyncio
async def test_reasoning_agent_delete_thing() -> None:
    """Eval: reasoning agent — delete thing scenarios."""
    from google.adk.evaluation import AgentEvaluator

    await AgentEvaluator.evaluate(
        agent_module="eval.reasoning_agent.agent",
        eval_dataset_file_path_or_dir=str(EVAL_ROOT / "reasoning_agent" / "delete_thing.test.json"),
        num_runs=1,
    )


@pytest.mark.asyncio
async def test_reasoning_agent_merge_things() -> None:
    """Eval: reasoning agent — merge things scenarios."""
    from google.adk.evaluation import AgentEvaluator

    await AgentEvaluator.evaluate(
        agent_module="eval.reasoning_agent.agent",
        eval_dataset_file_path_or_dir=str(EVAL_ROOT / "reasoning_agent" / "merge_things.test.json"),
        num_runs=1,
    )


@pytest.mark.asyncio
async def test_reasoning_agent_multi_step() -> None:
    """Eval: reasoning agent — multi-step scenarios."""
    from google.adk.evaluation import AgentEvaluator

    await AgentEvaluator.evaluate(
        agent_module="eval.reasoning_agent.agent",
        eval_dataset_file_path_or_dir=str(EVAL_ROOT / "reasoning_agent" / "multi_step.test.json"),
        num_runs=1,
    )


@pytest.mark.asyncio
async def test_reasoning_agent_all() -> None:
    """Eval: reasoning agent — all scenarios (directory scan)."""
    from google.adk.evaluation import AgentEvaluator

    await AgentEvaluator.evaluate(
        agent_module="eval.reasoning_agent.agent",
        eval_dataset_file_path_or_dir=str(EVAL_ROOT / "reasoning_agent"),
        num_runs=1,
    )


@pytest.mark.asyncio
async def test_context_agent_search_params() -> None:
    """Eval: context agent — search param generation."""
    from google.adk.evaluation import AgentEvaluator

    await AgentEvaluator.evaluate(
        agent_module="eval.context_agent.agent",
        eval_dataset_file_path_or_dir=str(EVAL_ROOT / "context_agent" / "search_params.test.json"),
        num_runs=1,
    )


@pytest.mark.asyncio
async def test_preference_detection_explicit() -> None:
    """Eval: preference detection — explicit preference statements."""
    from google.adk.evaluation import AgentEvaluator

    await AgentEvaluator.evaluate(
        agent_module="eval.preference_detection.agent",
        eval_dataset_file_path_or_dir=str(EVAL_ROOT / "preference_detection" / "explicit_preferences.test.json"),
        num_runs=1,
    )


@pytest.mark.asyncio
async def test_preference_detection_inferred() -> None:
    """Eval: preference detection — inferred behavioral patterns."""
    from google.adk.evaluation import AgentEvaluator

    await AgentEvaluator.evaluate(
        agent_module="eval.preference_detection.agent",
        eval_dataset_file_path_or_dir=str(EVAL_ROOT / "preference_detection" / "inferred_preferences.test.json"),
        num_runs=1,
    )


@pytest.mark.asyncio
async def test_preference_detection_all() -> None:
    """Eval: preference detection — all scenarios (directory scan)."""
    from google.adk.evaluation import AgentEvaluator

    await AgentEvaluator.evaluate(
        agent_module="eval.preference_detection.agent",
        eval_dataset_file_path_or_dir=str(EVAL_ROOT / "preference_detection"),
        num_runs=1,
    )
