"""Model comparison runner for eval suites.

Runs the same golden datasets across multiple models and compares pass rates
to identify the cheapest model per pipeline stage that meets quality thresholds.

Usage (standalone):
    python -m eval._comparison_runner

Usage (via pytest):
    RUN_EVALS=1 RUN_MODEL_COMPARISON=1 pytest backend/tests/test_eval_model_comparison.py -v

Output: a markdown table + JSON report showing model × eval_case × score.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from google.adk.evaluation.evaluation_generator import EvaluationGenerator
from google.adk.evaluation.simulation.user_simulator_provider import UserSimulatorProvider
from google.adk.evaluation.trajectory_evaluator import get_all_tool_calls

EVAL_ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Model catalogue — costs in USD per 1M tokens (input / output)
# Update as pricing changes. These are approximate list prices.
# ---------------------------------------------------------------------------

MODELS: dict[str, dict[str, float]] = {
    "google/gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "google/gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "google/gemini-2.5-flash-lite": {"input": 0.075, "output": 0.30},
    "google/gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "google/gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
}

# Models to compare per pipeline stage.
STAGE_MODELS: dict[str, list[str]] = {
    "reasoning": [
        "google/gemini-2.5-pro",
        "google/gemini-2.5-flash",
        "google/gemini-2.5-flash-lite",
    ],
    "context": [
        "google/gemini-2.5-flash",
        "google/gemini-2.5-flash-lite",
        "google/gemini-2.0-flash-lite",
    ],
}

# Eval test files per stage.
STAGE_TEST_FILES: dict[str, list[Path]] = {
    "reasoning": [
        EVAL_ROOT / "reasoning_agent" / "create_thing.test.json",
        EVAL_ROOT / "reasoning_agent" / "update_thing.test.json",
        EVAL_ROOT / "reasoning_agent" / "delete_thing.test.json",
        EVAL_ROOT / "reasoning_agent" / "merge_things.test.json",
        EVAL_ROOT / "reasoning_agent" / "multi_step.test.json",
        EVAL_ROOT / "reasoning_agent" / "preference_detection.test.json",
    ],
    "context": [
        EVAL_ROOT / "context_agent" / "search_params.test.json",
    ],
}

# Quality threshold: fraction of eval cases that must pass.
PASS_THRESHOLD = 0.6

# Number of runs per eval case (for variance estimation).
RUNS_PER_CASE = 3


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    eval_id: str
    passes: int
    total_runs: int

    @property
    def pass_rate(self) -> float:
        return self.passes / self.total_runs if self.total_runs else 0.0

    @property
    def passed(self) -> bool:
        return self.pass_rate >= 0.5  # majority vote


@dataclass
class ModelResult:
    stage: str
    model_name: str
    test_file: str
    case_results: list[CaseResult] = field(default_factory=list)

    @property
    def overall_pass_rate(self) -> float:
        if not self.case_results:
            return 0.0
        return sum(1 for c in self.case_results if c.passed) / len(self.case_results)

    @property
    def meets_threshold(self) -> bool:
        return self.overall_pass_rate >= PASS_THRESHOLD


# ---------------------------------------------------------------------------
# Helpers (shared with test_evals.py logic)
# ---------------------------------------------------------------------------


def _load_eval_cases(test_file: str | Path):
    from google.adk.evaluation.eval_case import EvalCase

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


async def _run_single_case(agent, case) -> bool:
    user_sim = UserSimulatorProvider().provide(case)
    invocations = await EvaluationGenerator._generate_inferences_from_root_agent(
        root_agent=agent,
        user_simulator=user_sim,
    )
    if not invocations:
        return False

    for actual_inv, expected_inv in zip(invocations, case.conversation):
        actual_tools = get_all_tool_calls(actual_inv.intermediate_data)
        expected_tools = get_all_tool_calls(expected_inv.intermediate_data)
        actual_names = [tc.name for tc in actual_tools if tc.name]
        expected_names = [tc.name for tc in expected_tools if tc.name]

        if not _tool_names_in_order(actual_names, expected_names):
            return False

    return True


async def _run_context_case_json_valid(agent, case) -> bool:
    """Context agent just needs to output valid JSON with search_queries or filter_params."""
    user_sim = UserSimulatorProvider().provide(case)
    invocations = await EvaluationGenerator._generate_inferences_from_root_agent(
        root_agent=agent,
        user_simulator=user_sim,
    )
    if not invocations:
        return False
    inv = invocations[0]
    if not inv.final_response or not inv.final_response.parts:
        return False
    text = inv.final_response.parts[0].text
    if not text:
        return False
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()
    try:
        parsed = json.loads(clean)
        return "search_queries" in parsed or "filter_params" in parsed
    except (json.JSONDecodeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Core comparison runner
# ---------------------------------------------------------------------------


def _build_agent(stage: str, model_name: str):
    if stage == "reasoning":
        from eval.reasoning_agent.agent import build_agent
    else:
        from eval.context_agent.agent import build_agent
    return build_agent(model_name)


async def run_model_on_test_file(
    stage: str,
    model_name: str,
    test_file: Path,
    runs_per_case: int = RUNS_PER_CASE,
) -> ModelResult:
    """Run all eval cases in test_file against model_name, repeated runs_per_case times."""
    agent = _build_agent(stage, model_name)
    cases = _load_eval_cases(test_file)
    result = ModelResult(stage=stage, model_name=model_name, test_file=str(test_file.name))

    for case in cases:
        passes = 0
        for _ in range(runs_per_case):
            if stage == "reasoning":
                passed = await _run_single_case(agent, case)
            else:
                passed = await _run_context_case_json_valid(agent, case)
            if passed:
                passes += 1
        result.case_results.append(
            CaseResult(eval_id=case.eval_id, passes=passes, total_runs=runs_per_case)
        )

    return result


async def run_comparison(
    stage: str,
    models: list[str] | None = None,
    runs_per_case: int = RUNS_PER_CASE,
) -> list[ModelResult]:
    """Run the full comparison for a pipeline stage across all (or specified) models."""
    models_to_test = models or STAGE_MODELS.get(stage, [])
    test_files = STAGE_TEST_FILES.get(stage, [])
    results: list[ModelResult] = []

    for model_name in models_to_test:
        for test_file in test_files:
            if not test_file.exists():
                continue
            result = await run_model_on_test_file(stage, model_name, test_file, runs_per_case)
            results.append(result)

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _cost_label(model_name: str) -> str:
    costs = MODELS.get(model_name)
    if not costs:
        return "unknown"
    return f"${costs['input']:.3f}/${costs['output']:.3f}"


def build_markdown_report(all_results: list[ModelResult]) -> str:
    """Generate a markdown comparison table from results."""
    lines: list[str] = ["# Model Comparison Report\n"]

    stages = sorted({r.stage for r in all_results})
    for stage in stages:
        stage_results = [r for r in all_results if r.stage == stage]
        lines.append(f"## Stage: {stage}\n")
        lines.append(
            "| Model | Cost (in/out per 1M) | Test File | Pass Rate | Meets Threshold |"
        )
        lines.append("|-------|---------------------|-----------|-----------|-----------------|")

        for r in stage_results:
            pct = f"{r.overall_pass_rate:.0%}"
            ok = "✅" if r.meets_threshold else "❌"
            cost = _cost_label(r.model_name)
            lines.append(f"| {r.model_name} | {cost} | {r.test_file} | {pct} | {ok} |")

        # Recommendation: cheapest model that meets threshold across all test files
        lines.append("")
        by_model: dict[str, list[ModelResult]] = {}
        for r in stage_results:
            by_model.setdefault(r.model_name, []).append(r)

        passing_models = [
            m for m, rs in by_model.items() if all(r.meets_threshold for r in rs)
        ]
        if passing_models:
            def _cost_sort_key(m: str) -> float:
                c = MODELS.get(m, {})
                return c.get("input", 999) + c.get("output", 999)

            cheapest = min(passing_models, key=_cost_sort_key)
            lines.append(f"> **Recommendation ({stage}):** Use `{cheapest}` — cheapest model that passes all thresholds.")
        else:
            lines.append(f"> **Recommendation ({stage}):** No model met the threshold. Consider lowering threshold or tuning prompts.")
        lines.append("")

    return "\n".join(lines)


def build_json_report(all_results: list[ModelResult]) -> list[dict[str, Any]]:
    """Serialize results to a list of dicts for JSON output."""
    report = []
    for r in all_results:
        report.append(
            {
                "stage": r.stage,
                "model": r.model_name,
                "cost_per_1m": MODELS.get(r.model_name, {}),
                "test_file": r.test_file,
                "overall_pass_rate": round(r.overall_pass_rate, 4),
                "meets_threshold": r.meets_threshold,
                "cases": [
                    {
                        "eval_id": c.eval_id,
                        "pass_rate": round(c.pass_rate, 4),
                        "passes": c.passes,
                        "total_runs": c.total_runs,
                    }
                    for c in r.case_results
                ],
            }
        )
    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run model comparison evals")
    parser.add_argument(
        "--stage",
        choices=["reasoning", "context", "all"],
        default="all",
        help="Pipeline stage to compare (default: all)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=RUNS_PER_CASE,
        help=f"Number of runs per eval case for variance estimation (default: {RUNS_PER_CASE})",
    )
    parser.add_argument(
        "--output",
        choices=["markdown", "json", "both"],
        default="both",
        help="Output format (default: both)",
    )
    parser.add_argument(
        "--out-dir",
        default=".",
        help="Directory to write report files (default: current dir)",
    )
    args = parser.parse_args()

    stages = ["reasoning", "context"] if args.stage == "all" else [args.stage]
    all_results: list[ModelResult] = []
    for stage in stages:
        print(f"\nRunning {stage} stage comparisons...")
        results = await run_comparison(stage, runs_per_case=args.runs)
        all_results.extend(results)
        for r in results:
            print(f"  {r.model_name} / {r.test_file}: {r.overall_pass_rate:.0%}", end="")
            print(" ✅" if r.meets_threshold else " ❌")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.output in ("markdown", "both"):
        md = build_markdown_report(all_results)
        md_path = out_dir / "model_comparison_report.md"
        md_path.write_text(md)
        print(f"\nMarkdown report: {md_path}")
        print(md)

    if args.output in ("json", "both"):
        report = build_json_report(all_results)
        json_path = out_dir / "model_comparison_report.json"
        json_path.write_text(json.dumps(report, indent=2))
        print(f"JSON report: {json_path}")


if __name__ == "__main__":
    asyncio.run(_main())
