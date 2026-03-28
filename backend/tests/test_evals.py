"""Pytest integration for ADK eval suites.

Runs the golden-dataset evaluation for the reasoning and context agents.
These tests require a live LLM endpoint (REQUESTY_API_KEY) and are opt-in
via the ``RUN_EVALS=1`` environment variable.

Uses a custom ToolNameTrajectoryEvaluator that matches tool names only
(ignores args), since non-deterministic models produce varying arguments
between runs while consistently calling the correct tools.

Usage:
    # Run all evals
    RUN_EVALS=1 pytest backend/tests/test_evals.py -x -v

    # Run only reasoning agent evals
    RUN_EVALS=1 pytest backend/tests/test_evals.py -x -v -k reasoning

    # Run only context agent evals
    RUN_EVALS=1 pytest backend/tests/test_evals.py -x -v -k context
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import Optional

import pytest

from google.adk.evaluation.eval_case import EvalCase
from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus
from google.adk.evaluation.evaluation_generator import EvaluationGenerator
from google.adk.evaluation.simulation.user_simulator_provider import UserSimulatorProvider
from google.adk.evaluation.trajectory_evaluator import get_all_tool_calls

# Evals hit a real LLM — skip by default unless opted in.
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_EVALS", "0") not in ("1", "true", "yes"),
    reason="Evals require RUN_EVALS=1 and a live LLM endpoint",
)

EVAL_ROOT = Path(__file__).resolve().parent.parent.parent / "eval"


def _load_agent(module_path: str):
    """Import the agent module and return root_agent."""
    mod = importlib.import_module(module_path)
    return mod.root_agent


def _load_eval_cases(test_file: str) -> list[EvalCase]:
    """Load eval cases from a .test.json file."""
    with open(test_file) as f:
        raw = json.load(f)
    return [EvalCase(**c) for c in raw.get("eval_cases", [])]


def _tool_names_in_order(actual_names: list[str], expected_names: list[str]) -> bool:
    """Check that all expected tool names appear in actual, in order. Extra calls OK."""
    if not expected_names:
        return True
    if not actual_names:
        return False
    expected_iter = iter(expected_names)
    current = next(expected_iter)
    for name in actual_names:
        if name == current:
            try:
                current = next(expected_iter)
            except StopIteration:
                return True
    return False


async def _run_single_case(agent, case) -> tuple[bool, str]:
    """Run a single eval case. Returns (passed, detail)."""
    user_sim = UserSimulatorProvider().provide(case)
    invocations = await EvaluationGenerator._generate_inferences_from_root_agent(
        root_agent=agent,
        user_simulator=user_sim,
    )

    if not invocations:
        return False, f"{case.eval_id}: no invocations returned"

    for actual_inv, expected_inv in zip(invocations, case.conversation):
        actual_tools = get_all_tool_calls(actual_inv.intermediate_data)
        expected_tools = get_all_tool_calls(expected_inv.intermediate_data)

        actual_names: list[str] = [tc.name for tc in actual_tools if tc.name]
        expected_names: list[str] = [tc.name for tc in expected_tools if tc.name]

        if _tool_names_in_order(actual_names, expected_names):
            return True, f"{case.eval_id}: OK ({actual_names})"
        else:
            return False, f"{case.eval_id}: expected {expected_names}, got {actual_names}"

    return False, f"{case.eval_id}: no conversation turns"


async def _run_tool_name_eval(
    agent_module: str,
    test_file: str,
    threshold: float = 0.6,
    max_retries: int = 2,
) -> None:
    """Run eval cases and assert tool name trajectories match (in order, ignoring args).

    Each case gets up to max_retries attempts — if it passes on any attempt,
    it counts as passed. This accounts for LLM non-determinism.
    """
    agent = _load_agent(agent_module)
    cases = _load_eval_cases(test_file)

    total_score = 0.0
    failures = []

    for case in cases:
        passed = False
        last_detail = ""
        for attempt in range(max_retries):
            passed, last_detail = await _run_single_case(agent, case)
            if passed:
                break

        if passed:
            total_score += 1.0
        else:
            failures.append(last_detail)

    avg_score = total_score / len(cases) if cases else 0.0

    if failures:
        failure_details = "\n  ".join(failures)
        assert avg_score >= threshold, (
            f"Tool name trajectory score {avg_score:.2f} below threshold {threshold}.\n"
            f"Failures:\n  {failure_details}"
        )


# ── Reasoning agent evals ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_agent_create_thing() -> None:
    """Eval: reasoning agent — create thing scenarios."""
    await _run_tool_name_eval(
        agent_module="eval.reasoning_agent.agent",
        test_file=str(EVAL_ROOT / "reasoning_agent" / "create_thing.test.json"),
    )


@pytest.mark.asyncio
async def test_reasoning_agent_update_thing() -> None:
    """Eval: reasoning agent — update thing scenarios."""
    await _run_tool_name_eval(
        agent_module="eval.reasoning_agent.agent",
        test_file=str(EVAL_ROOT / "reasoning_agent" / "update_thing.test.json"),
    )


@pytest.mark.asyncio
async def test_reasoning_agent_delete_thing() -> None:
    """Eval: reasoning agent — delete thing scenarios."""
    await _run_tool_name_eval(
        agent_module="eval.reasoning_agent.agent",
        test_file=str(EVAL_ROOT / "reasoning_agent" / "delete_thing.test.json"),
    )


@pytest.mark.asyncio
async def test_reasoning_agent_merge_things() -> None:
    """Eval: reasoning agent — merge things scenarios."""
    await _run_tool_name_eval(
        agent_module="eval.reasoning_agent.agent",
        test_file=str(EVAL_ROOT / "reasoning_agent" / "merge_things.test.json"),
    )


@pytest.mark.asyncio
async def test_reasoning_agent_multi_step() -> None:
    """Eval: reasoning agent — multi-step scenarios."""
    await _run_tool_name_eval(
        agent_module="eval.reasoning_agent.agent",
        test_file=str(EVAL_ROOT / "reasoning_agent" / "multi_step.test.json"),
    )


@pytest.mark.asyncio
async def test_reasoning_agent_preference_detection() -> None:
    """Eval: reasoning agent — preference detection scenarios."""
    await _run_tool_name_eval(
        agent_module="eval.reasoning_agent.agent",
        test_file=str(EVAL_ROOT / "reasoning_agent" / "preference_detection.test.json"),
    )


@pytest.mark.asyncio
async def test_reasoning_agent_personality_adaptation() -> None:
    """Eval: reasoning agent — personality adaptation."""
    await _run_tool_name_eval(
        agent_module="eval.reasoning_agent.agent",
        test_file=str(EVAL_ROOT / "reasoning_agent" / "personality_adaptation.test.json"),
    )


@pytest.mark.asyncio
async def test_reasoning_agent_thought_signature() -> None:
    """Eval: reasoning agent — thought_signature regression."""
    await _run_tool_name_eval(
        agent_module="eval.reasoning_agent.agent",
        test_file=str(EVAL_ROOT / "reasoning_agent" / "thought_signature_tool_chain.test.json"),
    )


# ── Context agent evals ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_agent_search_params() -> None:
    """Eval: context agent — search param generation.

    The context agent is a text-only agent (no tool calls), so we can't use
    tool trajectory matching. This test just verifies the agent produces
    valid JSON output.
    """
    agent = _load_agent("eval.context_agent.agent")
    cases = _load_eval_cases(str(EVAL_ROOT / "context_agent" / "search_params.test.json"))

    for case in cases:
        user_sim = UserSimulatorProvider().provide(case)
        invocations = await EvaluationGenerator._generate_inferences_from_root_agent(
            root_agent=agent,
            user_simulator=user_sim,
        )
        assert invocations, f"{case.eval_id}: no invocations returned"
        inv = invocations[0]
        assert inv.final_response, f"{case.eval_id}: no final response"
        parts = inv.final_response.parts
        assert parts, f"{case.eval_id}: no parts in final response"
        text = parts[0].text
        assert text, f"{case.eval_id}: no text in final response"
        # Context agent should output valid JSON with search_queries
        parsed = json.loads(text)
        assert "search_queries" in parsed or "filter_params" in parsed, (
            f"{case.eval_id}: response missing search_queries or filter_params: {text[:200]}"
        )
