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
    """Run a single eval case. Returns (passed, detail).

    For multi-turn cases, all turns must pass. A turn with no expected
    tool calls passes if the agent produces a response (even without tools).
    """
    user_sim = UserSimulatorProvider().provide(case)
    invocations = await EvaluationGenerator._generate_inferences_from_root_agent(
        root_agent=agent,
        user_simulator=user_sim,
    )

    if not invocations:
        return False, f"{case.eval_id}: no invocations returned"

    expected_turns = len(case.conversation)
    if len(invocations) < expected_turns:
        return False, (
            f"{case.eval_id}: expected {expected_turns} turns, got {len(invocations)}"
        )

    for i, (actual_inv, expected_inv) in enumerate(zip(invocations, case.conversation)):
        actual_tools = get_all_tool_calls(actual_inv.intermediate_data)
        expected_tools = get_all_tool_calls(expected_inv.intermediate_data)

        actual_names: list[str] = [tc.name for tc in actual_tools if tc.name]
        expected_names: list[str] = [tc.name for tc in expected_tools if tc.name]

        # If no tools expected, the turn passes as long as it ran
        if not expected_names:
            continue

        if not _tool_names_in_order(actual_names, expected_names):
            return False, (
                f"{case.eval_id} turn {i + 1}: expected {expected_names}, got {actual_names}"
            )

    return True, f"{case.eval_id}: OK ({len(invocations)} turns)"


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


async def _run_no_action_eval(
    agent_module: str,
    test_file: str,
    threshold: float = 0.6,
    max_retries: int = 2,
) -> None:
    """Run eval cases that expect NO mutating tool calls.

    Read-only tools (fetch_context, chat_history) are allowed.
    """
    agent = _load_agent(agent_module)
    cases = _load_eval_cases(test_file)

    total_score = 0.0
    failures = []

    for case in cases:
        passed = False
        last_detail = ""
        for attempt in range(max_retries):
            user_sim = UserSimulatorProvider().provide(case)
            invocations = await EvaluationGenerator._generate_inferences_from_root_agent(
                root_agent=agent,
                user_simulator=user_sim,
            )
            if not invocations:
                last_detail = f"{case.eval_id}: no invocations returned"
                continue

            inv = invocations[0]
            actual_tools = get_all_tool_calls(inv.intermediate_data)
            mutating_tools = [
                tc.name for tc in actual_tools
                if tc.name and tc.name not in ("fetch_context", "chat_history")
            ]
            if not mutating_tools:
                passed = True
                last_detail = f"{case.eval_id}: OK (no mutating tool calls)"
                break
            else:
                last_detail = (
                    f"{case.eval_id}: expected no mutating tools, got {mutating_tools}"
                )

        if passed:
            total_score += 1.0
        else:
            failures.append(last_detail)

    avg_score = total_score / len(cases) if cases else 0.0

    if failures:
        failure_details = "\n  ".join(failures)
        assert avg_score >= threshold, (
            f"No-action eval score {avg_score:.2f} below threshold {threshold}.\n"
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
async def test_reasoning_agent_multi_turn() -> None:
    """Eval: reasoning agent — multi-turn conversation (catches thought_signature regressions)."""
    await _run_tool_name_eval(
        agent_module="eval.reasoning_agent.agent",
        test_file=str(EVAL_ROOT / "reasoning_agent" / "multi_turn.test.json"),
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


# ── Ambiguity handling evals ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_agent_ambiguity_handling() -> None:
    """Eval: reasoning agent — asks clarifying questions when intent is ambiguous."""
    await _run_tool_name_eval(
        agent_module="eval.reasoning_agent.agent",
        test_file=str(EVAL_ROOT / "reasoning_agent" / "ambiguity_handling.test.json"),
    )


# ── No-action evals ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_agent_no_action() -> None:
    """Eval: reasoning agent — does NOT create Things for greetings, thanks, off-topic."""
    await _run_no_action_eval(
        agent_module="eval.reasoning_agent.agent",
        test_file=str(EVAL_ROOT / "reasoning_agent" / "no_action.test.json"),
    )


# ── Temporal reasoning evals ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_agent_temporal_reasoning() -> None:
    """Eval: reasoning agent — relative dates and time-sensitive queries."""
    await _run_tool_name_eval(
        agent_module="eval.reasoning_agent.agent",
        test_file=str(EVAL_ROOT / "reasoning_agent" / "temporal_reasoning.test.json"),
    )


# ── Conflicting context evals ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_agent_conflicting_context() -> None:
    """Eval: reasoning agent — contradiction detection and safe overwrite."""
    await _run_tool_name_eval(
        agent_module="eval.reasoning_agent.agent",
        test_file=str(EVAL_ROOT / "reasoning_agent" / "conflicting_context.test.json"),
    )


# ── Bulk operations evals ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_agent_bulk_operations() -> None:
    """Eval: reasoning agent — batch updates, deletes, completions."""
    await _run_tool_name_eval(
        agent_module="eval.reasoning_agent.agent",
        test_file=str(EVAL_ROOT / "reasoning_agent" / "bulk_operations.test.json"),
    )


# ── Briefing mode evals ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_agent_briefing_mode() -> None:
    """Eval: reasoning agent — triggers briefing_mode for status questions."""
    await _run_tool_name_eval(
        agent_module="eval.reasoning_agent.agent",
        test_file=str(EVAL_ROOT / "reasoning_agent" / "briefing_mode.test.json"),
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


@pytest.mark.asyncio
async def test_context_agent_complex_queries() -> None:
    """Eval: context agent — complex/abstract query interpretation."""
    agent = _load_agent("eval.context_agent.agent")
    cases = _load_eval_cases(str(EVAL_ROOT / "context_agent" / "complex_queries.test.json"))

    for case in cases:
        user_sim = UserSimulatorProvider().provide(case)
        invocations = await EvaluationGenerator._generate_inferences_from_root_agent(
            root_agent=agent, user_simulator=user_sim,
        )
        assert invocations, f"{case.eval_id}: no invocations returned"
        inv = invocations[0]
        assert inv.final_response, f"{case.eval_id}: no final response"
        parts = inv.final_response.parts
        assert parts, f"{case.eval_id}: no parts in final response"
        text = parts[0].text
        assert text, f"{case.eval_id}: no text in final response"
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()
        parsed = json.loads(clean)
        assert "search_queries" in parsed, (
            f"{case.eval_id}: response missing search_queries: {text[:200]}"
        )
        assert len(parsed["search_queries"]) >= 1, (
            f"{case.eval_id}: expected at least one search query, got {parsed['search_queries']}"
        )


# ── Context agent semantic depth (LLM-as-judge) ─────────────────────────────

CONTEXT_JUDGE_SYSTEM = """\
You are an eval judge for a context retrieval agent. The agent generates search
parameters to find relevant items in a personal knowledge database.

Score the output on search quality. Respond with ONLY valid JSON:
{"pass": true/false, "score": 0.0-1.0, "reasoning": "Brief explanation"}

Key principles:
- SEMANTIC EXPANSION: "Book hotel to visit sister" should search for the sister
  entity AND hotel/travel, not just "hotel".
- RELEVANCE: Don't over-expand into tangentially related domains.
- COMPLETENESS: Multi-entity requests should search for all relevant entities.
"""


@pytest.mark.asyncio
async def test_context_agent_semantic_depth() -> None:
    """Eval: context agent — semantic expansion via LLM-as-judge."""
    import litellm

    from backend.agents import CONTEXT_AGENT_SYSTEM

    google_api_key = os.environ.get("GOOGLE_API_KEY")
    if not google_api_key:
        pytest.skip("GOOGLE_API_KEY required for semantic depth evals")

    gen_model = "gemini/gemini-3.1-flash-lite-preview"
    judge_model = "gemini/gemini-3-flash-preview"

    with open(EVAL_ROOT / "context_agent" / "semantic_depth.test.json") as f:
        data = json.load(f)
    cases = data.get("cases", [])
    total_score = 0.0
    failures = []

    for case in cases:
        user_msg = (
            "Today's date: 2026-03-28 (Saturday)\n\n"
            f"<user_message>\n{case['user_message']}\n</user_message>"
        )
        response = await litellm.acompletion(
            model=gen_model, api_key=google_api_key,
            messages=[
                {"role": "system", "content": CONTEXT_AGENT_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
        )
        raw_output = response.choices[0].message.content or "{}"
        clean = raw_output.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()
        try:
            agent_output = json.loads(clean)
        except json.JSONDecodeError:
            failures.append(f"{case['case_id']}: invalid JSON: {raw_output[:200]}")
            continue

        judge_prompt = json.dumps({
            "user_message": case["user_message"],
            "agent_output": agent_output,
            "evaluation_criteria": case["judge_criteria"],
            "case_description": case["description"],
        }, indent=2)
        judge_response = await litellm.acompletion(
            model=judge_model, api_key=google_api_key,
            messages=[
                {"role": "system", "content": CONTEXT_JUDGE_SYSTEM},
                {"role": "user", "content": judge_prompt},
            ],
            response_format={"type": "json_object"},
        )
        judge_raw = judge_response.choices[0].message.content or "{}"
        judge_clean = judge_raw.strip()
        if judge_clean.startswith("```"):
            judge_clean = judge_clean.split("\n", 1)[1] if "\n" in judge_clean else judge_clean[3:]
            if judge_clean.endswith("```"):
                judge_clean = judge_clean[:-3]
            judge_clean = judge_clean.strip()
        try:
            judge_result = json.loads(judge_clean)
        except json.JSONDecodeError:
            failures.append(f"{case['case_id']}: judge returned invalid JSON")
            continue

        if judge_result.get("pass", False):
            total_score += 1.0
        else:
            failures.append(f"{case['case_id']}: {judge_result.get('reasoning', 'no reasoning')}")

    avg_score = total_score / len(cases) if cases else 0.0
    if failures:
        failure_details = "\n  ".join(failures)
        assert avg_score >= 0.5, (
            f"Context semantic depth score {avg_score:.2f} below threshold 0.5.\n"
            f"Failures:\n  {failure_details}"
        )


# ── Preference sweep (LLM-as-judge) ─────────────────────────────────────────

JUDGE_SYSTEM = """\
You are an eval judge for a preference detection system. Score the output.
Respond with ONLY valid JSON:
{"pass": true/false, "score": 0.0-1.0, "reasoning": "Brief explanation"}

The system should: detect real patterns with evidence, NOT fabricate patterns,
assign calibrated confidence, reference existing preferences by ID when updating.
"""


def _format_interactions_for_eval(interactions, existing_preferences):
    """Format interactions into the same prompt format the real sweep uses."""
    lines = [f"Recent interactions ({len(interactions)} messages):", ""]
    for i, msg in enumerate(interactions):
        line = f"{i + 1}. [{msg['role']}] {msg['content']}"
        changes = msg.get("applied_changes")
        if changes:
            for key in ("created", "updated"):
                items = changes.get(key, [])
                if items:
                    titles = [c.get("title", "?") for c in items if isinstance(c, dict)]
                    line += f" [{key}: {', '.join(titles[:3])}]"
        lines.append(line)
    if existing_preferences:
        lines.append("")
        lines.append("Existing preferences:")
        for p in existing_preferences:
            conf = p["data"].get("confidence", 0.5)
            cat = p["data"].get("category", "unknown")
            lines.append(f"  - [{p['id']}] {p['title']} (confidence={conf}, category={cat})")
    return "\n".join(lines)


@pytest.mark.asyncio
async def test_preference_sweep_aggregation() -> None:
    """Eval: preference sweep — pattern detection quality via LLM-as-judge."""
    import litellm

    from backend.preference_sweep import PREFERENCE_AGGREGATION_SYSTEM

    google_api_key = os.environ.get("GOOGLE_API_KEY")
    if not google_api_key:
        pytest.skip("GOOGLE_API_KEY required for preference sweep evals")

    gen_model = "gemini/gemini-3-flash-preview"
    judge_model = "gemini/gemini-3-flash-preview"

    with open(EVAL_ROOT / "preference_sweep" / "preference_aggregation.test.json") as f:
        data = json.load(f)
    cases = data.get("cases", [])
    total_score = 0.0
    failures = []

    for case in cases:
        prompt = _format_interactions_for_eval(
            case["interactions"], case.get("existing_preferences", []),
        )
        response = await litellm.acompletion(
            model=gen_model, api_key=google_api_key,
            messages=[
                {"role": "system", "content": PREFERENCE_AGGREGATION_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        raw_output = response.choices[0].message.content or "{}"
        clean = raw_output.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()
        try:
            llm_output = json.loads(clean)
        except json.JSONDecodeError:
            failures.append(f"{case['case_id']}: invalid JSON: {raw_output[:200]}")
            continue

        judge_prompt = json.dumps({
            "interactions": case["interactions"],
            "existing_preferences": case.get("existing_preferences", []),
            "system_output": llm_output,
            "evaluation_criteria": case["judge_criteria"],
            "case_description": case["description"],
        }, indent=2)
        judge_response = await litellm.acompletion(
            model=judge_model, api_key=google_api_key,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": judge_prompt},
            ],
            response_format={"type": "json_object"},
        )
        judge_raw = judge_response.choices[0].message.content or "{}"
        judge_clean = judge_raw.strip()
        if judge_clean.startswith("```"):
            judge_clean = judge_clean.split("\n", 1)[1] if "\n" in judge_clean else judge_clean[3:]
            if judge_clean.endswith("```"):
                judge_clean = judge_clean[:-3]
            judge_clean = judge_clean.strip()
        try:
            judge_result = json.loads(judge_clean)
        except json.JSONDecodeError:
            failures.append(f"{case['case_id']}: judge returned invalid JSON")
            continue

        if judge_result.get("pass", False):
            total_score += 1.0
        else:
            failures.append(f"{case['case_id']}: {judge_result.get('reasoning', 'no reasoning')}")

    avg_score = total_score / len(cases) if cases else 0.0
    if failures:
        failure_details = "\n  ".join(failures)
        assert avg_score >= 0.6, (
            f"Preference sweep score {avg_score:.2f} below threshold 0.6.\n"
            f"Failures:\n  {failure_details}"
        )
