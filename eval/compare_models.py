"""Multi-model eval comparison script.

Runs the existing golden-dataset eval suites across a configurable list of
models per pipeline stage, repeats each case multiple times for variance, and
outputs a markdown comparison table plus a JSON report.

Usage:
    # Default (flash + flash-lite), 3 runs per case
    python -m eval.compare_models

    # Include gemini-2.5-pro (expensive)
    python -m eval.compare_models --include-pro

    # Quick sanity check
    python -m eval.compare_models --runs 1 --output /tmp/quick_compare.json

    # Dry run — just print config and exit
    python -m eval.compare_models --dry-run
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.evaluation.eval_case import EvalCase
from google.adk.evaluation.evaluation_generator import EvaluationGenerator
from google.adk.evaluation.simulation.user_simulator_provider import UserSimulatorProvider
from google.adk.evaluation.trajectory_evaluator import get_all_tool_calls
from google.genai import types as genai_types

from backend.agents import CONTEXT_AGENT_SYSTEM
from backend.reasoning_agent import REASONING_AGENT_TOOL_SYSTEM
from eval._eval_model import make_eval_model

# ---------------------------------------------------------------------------
# Stub tools — same as eval/reasoning_agent/agent.py
# ---------------------------------------------------------------------------

_NEXT_ID = 0


def _fresh_id() -> str:
    global _NEXT_ID
    _NEXT_ID += 1
    return f"eval-thing-{_NEXT_ID:04d}"


def fetch_context(
    search_queries_json: str = "[]",
    fetch_ids_json: str = "[]",
    active_only: bool = True,
    type_hint: str = "",
) -> dict[str, Any]:
    """Search the Things database for relevant context (eval stub)."""
    return {"things": [], "relationships": [], "count": 0}


def create_thing(
    title: str,
    type_hint: str = "",
    priority: int = 3,
    checkin_date: str = "",
    surface: bool = True,
    data_json: str = "{}",
    open_questions_json: str = "[]",
) -> dict[str, Any]:
    """Create a new Thing in the database (eval stub)."""
    return {"id": _fresh_id(), "title": title, "type_hint": type_hint}


def update_thing(
    thing_id: str,
    title: str = "",
    active: bool | None = None,
    checkin_date: str = "",
    priority: int | None = None,
    type_hint: str = "",
    surface: bool | None = None,
    data_json: str = "",
    open_questions_json: str = "",
) -> dict[str, Any]:
    """Update an existing Thing's fields (eval stub)."""
    return {"id": thing_id, "title": title or "updated"}


def delete_thing(thing_id: str) -> dict[str, Any]:
    """Delete a Thing by ID (eval stub)."""
    return {"deleted": thing_id}


def merge_things(
    keep_id: str,
    remove_id: str,
    merged_data_json: str = "{}",
) -> dict[str, Any]:
    """Merge a duplicate Thing into a primary Thing (eval stub)."""
    return {"keep_id": keep_id, "remove_id": remove_id}


def create_relationship(
    from_thing_id: str,
    to_thing_id: str,
    relationship_type: str,
) -> dict[str, Any]:
    """Create a typed relationship link between two Things (eval stub)."""
    return {
        "from_thing_id": from_thing_id,
        "to_thing_id": to_thing_id,
        "relationship_type": relationship_type,
    }


def chat_history(
    n: int = 10,
    search_query: str = "",
) -> dict[str, Any]:
    """Retrieve older messages from the current conversation (eval stub)."""
    return {"messages": [], "count": 0}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODELS_TO_TEST: dict[str, list[str]] = {
    "reasoning": [
        "google/gemini-2.5-flash",
        "google/gemini-2.5-flash-lite",
        "google/gemini-2.5-pro",  # expensive — only with --include-pro
    ],
    "context": [
        "google/gemini-2.5-flash-lite",
        "google/gemini-2.5-flash",
    ],
}

EVAL_ROOT = Path(__file__).resolve().parent

REASONING_TEST_FILES: list[str] = [
    str(EVAL_ROOT / "reasoning_agent" / f)
    for f in [
        "create_thing.test.json",
        "update_thing.test.json",
        "delete_thing.test.json",
        "merge_things.test.json",
        "multi_step.test.json",
        "preference_detection.test.json",
        "priority_question_gaps.test.json",
        "personality_adaptation.test.json",
        "thought_signature_tool_chain.test.json",
    ]
]

CONTEXT_TEST_FILES: list[str] = [
    str(EVAL_ROOT / "context_agent" / "search_params.test.json"),
]

# Hardcoded pricing (USD per 1M tokens) as of May 2026.
COST_PER_1M: dict[str, dict[str, float]] = {
    "google/gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "google/gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "google/gemini-2.5-pro": {"input": 3.50, "output": 10.50},
}

# Thresholds from test_config.json files.
THRESHOLDS: dict[str, float] = {
    "reasoning": 0.8,
    "context": 0.6,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_eval_cases(test_file: str) -> list[EvalCase]:
    with open(test_file) as f:
        raw = json.load(f)
    return [EvalCase(**c) for c in raw.get("eval_cases", [])]


def _tool_names_in_order(actual_names: list[str], expected_names: list[str]) -> bool:
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


# ---------------------------------------------------------------------------
# Agent builders
# ---------------------------------------------------------------------------


def _build_reasoning_agent(model_override: str) -> LlmAgent:
    model = make_eval_model("reasoning", model_override=model_override)
    return LlmAgent(
        name="reasoning_agent",
        description="Reasoning agent for Reli — decides storage changes via tool calls.",
        model=model,
        instruction=REASONING_AGENT_TOOL_SYSTEM,
        tools=[
            fetch_context,
            create_thing,
            update_thing,
            delete_thing,
            merge_things,
            create_relationship,
            chat_history,
        ],
    )


def _build_context_agent(model_override: str) -> LlmAgent:
    model = make_eval_model("context", model_override=model_override)
    return LlmAgent(
        name="context_agent",
        description="Generates search parameters to find relevant Things in the database.",
        model=model,
        instruction=CONTEXT_AGENT_SYSTEM,
        generate_content_config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )


# ---------------------------------------------------------------------------
# Case runners
# ---------------------------------------------------------------------------


async def _run_reasoning_case(agent: LlmAgent, case: EvalCase, max_retries: int = 3) -> float:
    """Run a single reasoning eval case. Returns 1.0 (pass) or 0.0 (fail)."""
    for _ in range(max_retries):
        user_sim = UserSimulatorProvider().provide(case)
        invocations = await EvaluationGenerator._generate_inferences_from_root_agent(
            root_agent=agent,
            user_simulator=user_sim,
        )
        if not invocations:
            continue

        for actual_inv, expected_inv in zip(invocations, case.conversation):
            actual_tools = get_all_tool_calls(actual_inv.intermediate_data)
            expected_tools = get_all_tool_calls(expected_inv.intermediate_data)
            actual_names = [tc.name for tc in actual_tools if tc.name]
            expected_names = [tc.name for tc in expected_tools if tc.name]
            if _tool_names_in_order(actual_names, expected_names):
                return 1.0
    return 0.0


async def _run_context_case(agent: LlmAgent, case: EvalCase, max_retries: int = 3) -> float:
    """Run a single context eval case. Returns 1.0 (pass) or 0.0 (fail)."""
    for _ in range(max_retries):
        user_sim = UserSimulatorProvider().provide(case)
        invocations = await EvaluationGenerator._generate_inferences_from_root_agent(
            root_agent=agent,
            user_simulator=user_sim,
        )
        if not invocations:
            continue
        inv = invocations[0]
        if not inv.final_response or not inv.final_response.parts:
            continue
        text = inv.final_response.parts[0].text
        if not text:
            continue
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()
        try:
            parsed = json.loads(clean)
        except json.JSONDecodeError:
            continue
        if "search_queries" in parsed or "filter_params" in parsed:
            return 1.0
    return 0.0


# ---------------------------------------------------------------------------
# Model evaluator
# ---------------------------------------------------------------------------


async def _evaluate_model(
    stage: str,
    model: str,
    test_files: list[str],
    runs: int = 3,
) -> dict[str, Any]:
    """Evaluate a single model across all test files for a stage.

    Each case is run *runs* times; per-run averages are aggregated into a
    mean and standard deviation.
    """
    if stage == "reasoning":
        agent = _build_reasoning_agent(model)
        run_case = _run_reasoning_case
    else:
        agent = _build_context_agent(model)
        run_case = _run_context_case

    all_cases: list[EvalCase] = []
    for tf in test_files:
        all_cases.extend(_load_eval_cases(tf))

    per_run_scores: list[float] = []
    for run_idx in range(runs):
        run_total = 0.0
        for case in all_cases:
            run_total += await run_case(agent, case, max_retries=1)
        per_run_scores.append(run_total / len(all_cases) if all_cases else 0.0)

    avg_score = statistics.mean(per_run_scores) if per_run_scores else 0.0
    variance = statistics.stdev(per_run_scores) if len(per_run_scores) > 1 else 0.0
    threshold = THRESHOLDS.get(stage, 0.7)

    return {
        "model": model,
        "stage": stage,
        "per_run_scores": per_run_scores,
        "avg_score": round(avg_score, 4),
        "stdev": round(variance, 4),
        "passes_threshold": avg_score >= threshold,
        "threshold": threshold,
        "total_cases": len(all_cases),
        "runs": runs,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _print_markdown_table(results: list[dict[str, Any]]) -> None:
    sorted_results = sorted(results, key=lambda r: (r["stage"], -r["avg_score"]))
    print()
    print("| Stage     | Model                          | Avg Score | \u00b1\u03c3   | Passes? | $/1M in |")
    print("|-----------|--------------------------------|-----------|------|---------|---------|")
    for r in sorted_results:
        cost = COST_PER_1M.get(r["model"])
        cost_str = f"${cost['input']:.2f}" if cost else "N/A"
        passes = "\u2713" if r["passes_threshold"] else "\u2717"
        row = (
            f"| {r['stage']:<9} | {r['model']:<30} "
            f"| {r['avg_score']:>9.2f} | {r['stdev']:.2f} "
            f"| {passes:<7} | {cost_str:>7} |"
        )
        print(row)
    print()


def _write_json_report(results: list[dict[str, Any]], path: Path) -> None:
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Report written to: {path}")


def _print_recommendation(results: list[dict[str, Any]]) -> None:
    stages = sorted(set(r["stage"] for r in results))
    print("RECOMMENDATION:")
    for stage in stages:
        stage_results = [r for r in results if r["stage"] == stage and r["passes_threshold"]]
        if not stage_results:
            print(f"  {stage} \u2192 no model passed threshold {THRESHOLDS.get(stage, 0.7)}")
            continue

        # Cheapest passing model (by input cost); break ties by highest score
        def _sort_key(r: dict[str, Any]) -> tuple[float, float]:
            cost = COST_PER_1M.get(r["model"], {}).get("input", float("inf"))
            return (cost, -r["avg_score"])

        best = min(stage_results, key=_sort_key)
        cost = COST_PER_1M.get(best["model"])
        cost_str = f"${cost['input']:.2f}/1M input" if cost else "N/A"
        print(
            f"  {stage} \u2192 {best['model']} "
            f"(score {best['avg_score']:.2f} \u2265 threshold {best['threshold']:.2f}, {cost_str})"
        )
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> dict[str, Any]:
    args: dict[str, Any] = {
        "include_pro": False,
        "runs": 3,
        "output": None,
        "dry_run": False,
        "help": False,
    }
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--help", "-h"):
            args["help"] = True
        elif arg == "--include-pro":
            args["include_pro"] = True
        elif arg == "--dry-run":
            args["dry_run"] = True
        elif arg == "--runs" and i + 1 < len(argv):
            i += 1
            args["runs"] = int(argv[i])
        elif arg == "--output" and i + 1 < len(argv):
            i += 1
            args["output"] = argv[i]
        i += 1
    return args


def _print_help() -> None:
    print(
        "Usage: python -m eval.compare_models [OPTIONS]\n"
        "\n"
        "Options:\n"
        "  --include-pro   Include gemini-2.5-pro (expensive)\n"
        "  --runs N        Number of runs per case (default: 3)\n"
        "  --output PATH   Path for JSON report (default: eval_comparison_YYYY-MM-DD.json)\n"
        "  --dry-run       Print configuration and exit\n"
        "  -h, --help      Show this help message\n"
    )


async def main() -> None:
    import os
    from datetime import date

    args = _parse_args(sys.argv[1:])

    if args["help"]:
        _print_help()
        return

    # Check for API credentials
    has_google = bool(os.environ.get("GOOGLE_API_KEY"))
    has_requesty = bool(os.environ.get("REQUESTY_API_KEY"))
    if not has_google and not has_requesty:
        print("ERROR: Set GOOGLE_API_KEY or REQUESTY_API_KEY to run evals.", file=sys.stderr)
        sys.exit(1)

    # Build model lists
    models_to_test = {
        stage: [m for m in models if args["include_pro"] or "pro" not in m] for stage, models in MODELS_TO_TEST.items()
    }

    runs = args["runs"]
    output_path = Path(args["output"]) if args["output"] else Path(f"eval_comparison_{date.today().isoformat()}.json")

    print("=== Multi-Model Eval Comparison ===")
    print(f"Runs per case: {runs}")
    print(f"API: {'Google AI Studio' if has_google else 'Requesty'}")
    for stage, models in models_to_test.items():
        print(f"  {stage}: {', '.join(models)}")
    print()

    if args["dry_run"]:
        print("(dry run — exiting)")
        return

    # Run evaluations
    results: list[dict[str, Any]] = []
    for stage, models in models_to_test.items():
        test_files = REASONING_TEST_FILES if stage == "reasoning" else CONTEXT_TEST_FILES
        for model in models:
            print(f"Evaluating {stage} / {model} ...", flush=True)
            result = await _evaluate_model(stage, model, test_files, runs=runs)
            results.append(result)
            print(f"  -> avg={result['avg_score']:.2f} stdev={result['stdev']:.2f}")

    _print_markdown_table(results)
    _write_json_report(results, output_path)
    _print_recommendation(results)


if __name__ == "__main__":
    asyncio.run(main())
