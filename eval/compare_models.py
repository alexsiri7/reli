"""Multi-model eval comparison script.

Runs the existing golden-dataset evals across multiple models, repeats each
run 3x for variance, and emits a markdown report showing score x model x
eval_case.

Usage:
    RUN_EVALS=1 python eval/compare_models.py
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from google.adk.evaluation.eval_case import EvalCase
from google.adk.evaluation.evaluation_generator import EvaluationGenerator
from google.adk.evaluation.simulation.user_simulator_provider import UserSimulatorProvider
from google.adk.evaluation.trajectory_evaluator import get_all_tool_calls

from eval.context_agent.agent import build_agent as build_context_agent
from eval.reasoning_agent.agent import build_agent as build_reasoning_agent

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RUNS_PER_COMBO = 3

MODEL_MATRIX: dict[str, list[str]] = {
    "reasoning": [
        "google/gemini-2.5-flash",
        "google/gemini-2.5-flash-lite",
        "google/gemini-2.5-pro",
    ],
    "context": [
        "google/gemini-2.5-flash-lite",
        "google/gemini-2.5-flash",
    ],
}

# USD per 1M tokens (public pricing as of 2026-05; update when pricing changes)
KNOWN_COSTS: dict[str, dict[str, float]] = {
    "google/gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "google/gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "google/gemini-2.5-pro": {"input": 1.25, "output": 10.00},
}

THRESHOLDS: dict[str, float] = {
    "reasoning": 0.60,
    "context": 1.00,
}

EVAL_ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Helpers (mirrored from backend/tests/test_evals.py)
# ---------------------------------------------------------------------------


def _load_eval_cases(test_file: str) -> list[EvalCase]:
    with open(test_file) as f:
        raw = json.load(f)
    return [EvalCase(**c) for c in raw.get("eval_cases", [])]


def _tool_names_in_order(actual_names: list[str], expected_names: list[str]) -> bool:
    """Return True if expected_names is an ordered subsequence of actual_names."""
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
# Eval runners
# ---------------------------------------------------------------------------


async def _run_single_reasoning_case(agent, case) -> bool:
    """Run one reasoning eval case, return True if passed."""
    user_sim = UserSimulatorProvider().provide(case)
    invocations = await EvaluationGenerator._generate_inferences_from_root_agent(
        root_agent=agent,
        user_simulator=user_sim,
    )
    if not invocations:
        return False
    for actual_inv, expected_inv in zip(invocations, case.conversation):
        actual_names = [tc.name for tc in get_all_tool_calls(actual_inv.intermediate_data) if tc.name]
        expected_names = [tc.name for tc in get_all_tool_calls(expected_inv.intermediate_data) if tc.name]
        if _tool_names_in_order(actual_names, expected_names):
            return True
        else:
            return False
    return False


async def run_reasoning_eval(model: str, dataset_path: str, runs: int = RUNS_PER_COMBO) -> tuple[float, float]:
    """Run reasoning eval for *model* on *dataset_path* N times.

    Returns (mean_pass_rate, std_dev).
    """
    cases = _load_eval_cases(dataset_path)
    if not cases:
        return 0.0, 0.0

    scores: list[float] = []
    for run_idx in range(runs):
        agent = build_reasoning_agent(model=model)
        passed = 0
        for case in cases:
            try:
                if await _run_single_reasoning_case(agent, case):
                    passed += 1
            except Exception:
                traceback.print_exc()
        scores.append(passed / len(cases))
        print(f"  run {run_idx + 1}/{runs}: {scores[-1]:.2f}")

    mean = sum(scores) / len(scores)
    std = math.sqrt(sum((s - mean) ** 2 for s in scores) / len(scores)) if len(scores) > 1 else 0.0
    return mean, std


async def run_context_eval(model: str, dataset_path: str, runs: int = RUNS_PER_COMBO) -> tuple[float, float]:
    """Run context eval for *model* N times. Checks JSON validity.

    Returns (mean_pass_rate, std_dev).
    """
    cases = _load_eval_cases(dataset_path)
    if not cases:
        return 0.0, 0.0

    scores: list[float] = []
    for run_idx in range(runs):
        agent = build_context_agent(model=model)
        passed = 0
        for case in cases:
            try:
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
                parsed = json.loads(clean)
                if "search_queries" in parsed or "filter_params" in parsed:
                    passed += 1
            except Exception:
                traceback.print_exc()
        scores.append(passed / len(cases))
        print(f"  run {run_idx + 1}/{runs}: {scores[-1]:.2f}")

    mean = sum(scores) / len(scores)
    std = math.sqrt(sum((s - mean) ** 2 for s in scores) / len(scores)) if len(scores) > 1 else 0.0
    return mean, std


# ---------------------------------------------------------------------------
# Discover datasets
# ---------------------------------------------------------------------------


def _discover_datasets() -> dict[str, list[Path]]:
    return {
        "reasoning": sorted((EVAL_ROOT / "reasoning_agent").glob("*.test.json")),
        "context": sorted((EVAL_ROOT / "context_agent").glob("*.test.json")),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


Row = tuple[str, str, str, float | None, float | None]  # (stage, model, dataset, mean, std) — None = run failed


def _format_report(rows: list[Row]) -> str:
    """Format eval results as a markdown report string."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [
        "## Model Comparison Results",
        "",
        f"Run: {now} | Runs per combo: {RUNS_PER_COMBO} | "
        f"Threshold: reasoning>={THRESHOLDS['reasoning']:.2f}, context>={THRESHOLDS['context']:.2f}",
        "",
    ]

    for stage in ("reasoning", "context"):
        stage_rows = [r for r in rows if r[0] == stage]
        if not stage_rows:
            continue
        lines.append(f"### {stage.title()} Agent")
        lines.append("")
        lines.append("| Model | Dataset | Mean Score | Std Dev | Pass? | Cost Input/1M | Cost Output/1M |")
        lines.append("|-------|---------|-----------|---------|-------|---------------|----------------|")
        for _, model, dataset, mean, std in stage_rows:
            cost = KNOWN_COSTS.get(model, {"input": "?", "output": "?"})
            threshold = THRESHOLDS[stage]
            mean_str = f"{mean:.2f}" if mean is not None else "ERROR"
            std_str = f"{std:.2f}" if std is not None else "—"
            if mean is None:
                pass_mark = "\u26a0 failed"
            elif mean >= threshold:
                pass_mark = "\u2713"
            else:
                pass_mark = "\u2717"
            ci = f"${cost['input']}" if isinstance(cost["input"], float) else "?"
            co = f"${cost['output']}" if isinstance(cost["output"], float) else "?"
            lines.append(f"| {model} | {dataset} | {mean_str} | {std_str} | {pass_mark} | {ci} | {co} |")
        lines.append("")

    # Recommendations
    lines.append("### Recommendation")
    lines.append("")
    for stage in ("reasoning", "context"):
        stage_rows = [r for r in rows if r[0] == stage]
        if not stage_rows:
            continue
        # Group by model, compute overall mean (skip failed runs with None mean)
        model_scores: dict[str, list[float]] = {}
        for _, model, _, mean, _ in stage_rows:
            if mean is not None:
                model_scores.setdefault(model, []).append(mean)
        best_model = None
        best_avg = -1.0
        threshold = THRESHOLDS[stage]
        for model, means in model_scores.items():
            avg = sum(means) / len(means)
            if avg >= threshold:
                # Prefer cheapest among passing models
                cost = KNOWN_COSTS.get(model, {}).get("input", float("inf"))
                if best_model is None or cost < KNOWN_COSTS.get(best_model, {}).get("input", float("inf")):
                    best_model = model
                    best_avg = avg
        if best_model:
            cost = KNOWN_COSTS.get(best_model, {"input": "?", "output": "?"})
            lines.append(
                f"**{stage.title()}**: `{best_model}` "
                f"(${cost['input']}/{cost['output']} per 1M) "
                f"\u2014 mean score {best_avg:.2f}, meets threshold {threshold:.2f}"
            )
        else:
            lines.append(f"**{stage.title()}**: No model met the {threshold:.2f} threshold")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    datasets = _discover_datasets()
    rows: list[Row] = []

    for stage, models in MODEL_MATRIX.items():
        stage_datasets = datasets.get(stage, [])
        if not stage_datasets:
            print(f"No datasets found for stage '{stage}', skipping")
            continue

        runner = run_reasoning_eval if stage == "reasoning" else run_context_eval

        for model in models:
            for ds_path in stage_datasets:
                ds_name = ds_path.stem.replace(".test", "")
                print(f"\n[{stage}] {model} / {ds_name}")
                try:
                    mean, std = await runner(model, str(ds_path))
                except Exception:
                    traceback.print_exc()
                    mean, std = None, None  # sentinel: run failed, not zero score
                rows.append((stage, model, ds_name, mean, std))

    report = _format_report(rows)
    print("\n" + report)


if __name__ == "__main__":
    # Opt-in guard (mirrors backend/tests/test_evals.py)
    if os.environ.get("RUN_EVALS", "0") not in ("1", "true", "yes"):
        print("Skipping model comparison — set RUN_EVALS=1 to run")
        sys.exit(0)
    asyncio.run(main())
