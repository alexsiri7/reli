"""Pytest integration for ADK eval suites.

Runs the golden-dataset evaluation for the reasoning, context, and response agents.
These tests require a live LLM endpoint (REQUESTY_API_KEY) and are opt-in
via the ``RUN_EVALS=1`` environment variable.

Uses a custom ToolNameTrajectoryEvaluator that matches tool names only
(ignores args), since non-deterministic models produce varying arguments
between runs while consistently calling the correct tools.

Response agent evals use LLM-as-judge with rubric criteria since the
response agent produces free-text output rather than tool calls.

Usage:
    # Run all evals
    RUN_EVALS=1 pytest backend/tests/test_evals.py -x -v

    # Run only reasoning agent evals
    RUN_EVALS=1 pytest backend/tests/test_evals.py -x -v -k reasoning

    # Run only context agent evals
    RUN_EVALS=1 pytest backend/tests/test_evals.py -x -v -k context

    # Run only response agent evals
    RUN_EVALS=1 pytest backend/tests/test_evals.py -x -v -k response
"""

from __future__ import annotations

import importlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Optional

import litellm
import pytest

from google.adk.agents import LlmAgent
from google.adk.evaluation.eval_case import EvalCase
from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus
from google.adk.evaluation.evaluation_generator import EvaluationGenerator
from google.adk.evaluation.simulation.user_simulator_provider import UserSimulatorProvider
from google.adk.evaluation.trajectory_evaluator import get_all_tool_calls
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

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
        # Strip markdown code fences if present
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()
        parsed = json.loads(clean)
        assert "search_queries" in parsed or "filter_params" in parsed, (
            f"{case.eval_id}: response missing search_queries or filter_params: {text[:200]}"
        )


# ── Response agent evals ─────────────────────────────────────────────────────
#
# The response agent is a text-only LlmAgent (no tool calls).  We evaluate its
# output with LLM-as-judge: for each case we run the agent, then ask a judge
# LLM whether the response satisfies rubric criteria.

_response_session_service = InMemorySessionService()


def _load_response_eval_cases(test_file: str) -> list[dict[str, Any]]:
    """Load response agent eval cases from a custom JSON file."""
    with open(test_file) as f:
        raw = json.load(f)
    return raw.get("eval_cases", [])


def _format_response_input(inp: dict[str, Any]) -> str:
    """Format agent input from case input fields (mirrors _build_user_prompt)."""
    return (
        f"<user_message>\n{inp['user_message']}\n</user_message>\n\n"
        f"<reasoning_summary>\n{inp['reasoning_summary']}\n</reasoning_summary>\n\n"
        f"Applied changes: {json.dumps(inp['applied_changes'])}\n\n"
        f"Questions for user (if any): {json.dumps(inp.get('questions_for_user', []))}\n\n"
        f"Priority question (ask THIS one): {json.dumps(inp.get('priority_question', ''))}\n\n"
        f"Briefing mode: {json.dumps(inp.get('briefing_mode', False))}"
    )


async def _run_response_agent(agent: LlmAgent, user_prompt: str) -> str:
    """Run the response agent with a pre-formatted prompt; return text response."""
    runner = Runner(
        agent=agent,
        app_name="reli_response_eval",
        session_service=_response_session_service,
    )
    session = await _response_session_service.create_session(
        app_name="reli_response_eval",
        user_id="eval",
        session_id=str(uuid.uuid4()),
    )
    user_content = genai_types.Content(
        role="user",
        parts=[genai_types.Part.from_text(text=user_prompt)],
    )
    text_parts: list[str] = []
    async for event in runner.run_async(
        user_id="eval",
        session_id=session.id,
        new_message=user_content,
    ):
        if event.content and event.content.parts and not event.partial:
            for part in event.content.parts:
                if part.text:
                    text_parts.append(part.text)
    return "".join(text_parts)


async def _llm_judge(
    response: str,
    rubric: list[str],
    judge_model: str = "google/gemini-2.0-flash-001",
) -> tuple[float, list[bool], str]:
    """Use an LLM to evaluate a response against rubric criteria.

    Returns (score 0–1, per-criterion pass list, summary note).
    Uses Requesty routing via LiteLLM (same as the rest of the eval suite).
    """
    from backend.llm import REQUESTY_API_KEY, REQUESTY_BASE_URL

    criteria_text = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(rubric))
    prompt = f"""You are a strict evaluator. For each criterion below, determine whether the response PASSES (true) or FAILS (false).

Response to evaluate:
---
{response}
---

Criteria:
{criteria_text}

Output ONLY valid JSON in this exact format (no markdown, no explanation):
{{"results": [true_or_false, ...], "score": 0.0_to_1.0, "note": "one-line summary"}}

Where:
- "results" has one boolean per criterion (in order)
- "score" is the fraction of criteria that passed (0.0 to 1.0)
- "note" briefly explains any failures"""

    completion = await litellm.acompletion(
        model=f"openai/{judge_model}",
        messages=[{"role": "user", "content": prompt}],
        api_key=REQUESTY_API_KEY,
        api_base=REQUESTY_BASE_URL,
    )
    raw = completion.choices[0].message.content.strip()
    # Strip markdown fences if the judge wrapped in them
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    data = json.loads(raw)
    results: list[bool] = [bool(r) for r in data.get("results", [])]
    score: float = float(data.get("score", sum(results) / len(results) if results else 0.0))
    note: str = data.get("note", "")
    return score, results, note


async def _run_response_agent_eval(
    test_file: str,
    threshold: float = 0.7,
    max_retries: int = 2,
) -> None:
    """Run all response agent eval cases and assert rubric scores meet threshold.

    Each case builds a fresh agent (with case-specific personality patterns),
    runs it against the canned input, and evaluates the output with LLM-as-judge.
    """
    import importlib

    agent_mod = importlib.import_module("eval.response_agent.agent")
    cases = _load_response_eval_cases(test_file)

    total_score = 0.0
    failures: list[str] = []

    for case in cases:
        eval_id = case["eval_id"]
        inp = case["input"]
        rubric = case["rubric"]
        personality_patterns = inp.get("personality_patterns", [])

        agent = agent_mod.build_agent(personality_patterns=personality_patterns)
        user_prompt = _format_response_input(inp)

        best_score = 0.0
        best_note = ""
        for attempt in range(max_retries):
            response = await _run_response_agent(agent, user_prompt)
            score, results, note = await _llm_judge(response, rubric)
            if score > best_score:
                best_score = score
                best_note = note
            if score >= threshold:
                break

        if best_score >= threshold:
            total_score += 1.0
        else:
            failures.append(f"{eval_id}: score={best_score:.2f} — {best_note}")

    avg_score = total_score / len(cases) if cases else 0.0
    if failures:
        details = "\n  ".join(failures)
        assert avg_score >= threshold, (
            f"Response agent eval score {avg_score:.2f} below threshold {threshold}.\n"
            f"Failures:\n  {details}"
        )


@pytest.mark.asyncio
async def test_response_agent_tone_personality() -> None:
    """Eval: response agent — tone and personality consistency.

    Covers default personality (creation confirmation, celebration),
    no-emoji preference, concise preference, and briefing mode.
    """
    await _run_response_agent_eval(
        test_file=str(EVAL_ROOT / "response_agent" / "tone_personality.test.json"),
        threshold=0.7,
    )


@pytest.mark.asyncio
async def test_response_agent_thing_references() -> None:
    """Eval: response agent — Thing reference accuracy in JSON block."""
    await _run_response_agent_eval(
        test_file=str(EVAL_ROOT / "response_agent" / "thing_references.test.json"),
        threshold=0.7,
    )


@pytest.mark.asyncio
async def test_response_agent_question_quality() -> None:
    """Eval: response agent — priority question ask/hold judgment."""
    await _run_response_agent_eval(
        test_file=str(EVAL_ROOT / "response_agent" / "question_quality.test.json"),
        threshold=0.7,
    )
