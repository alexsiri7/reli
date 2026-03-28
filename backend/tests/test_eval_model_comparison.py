"""Model comparison eval tests — parametrized across models per pipeline stage.

Runs the same golden datasets across multiple models to identify the cheapest
model per stage that meets quality thresholds.

Usage:
    # Run all model comparison evals
    RUN_EVALS=1 RUN_MODEL_COMPARISON=1 pytest backend/tests/test_eval_model_comparison.py -v

    # Run only reasoning stage
    RUN_EVALS=1 RUN_MODEL_COMPARISON=1 pytest backend/tests/test_eval_model_comparison.py -v -k reasoning

    # Run only context stage
    RUN_EVALS=1 RUN_MODEL_COMPARISON=1 pytest backend/tests/test_eval_model_comparison.py -v -k context

Each test is parametrized by (model_name, test_file) so results appear as
individual rows in pytest output, enabling easy comparison.

Results are also written to model_comparison_report.{md,json} in the
project root when all tests complete (via a session-scoped fixture).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from eval._comparison_runner import (
    PASS_THRESHOLD,
    RUNS_PER_CASE,
    STAGE_MODELS,
    STAGE_TEST_FILES,
    CaseResult,
    ModelResult,
    build_json_report,
    build_markdown_report,
    run_model_on_test_file,
)

# Skip unless both EVALS and model comparison are opted in.
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_EVALS", "0") not in ("1", "true", "yes")
    or os.environ.get("RUN_MODEL_COMPARISON", "0") not in ("1", "true", "yes"),
    reason="Model comparison requires RUN_EVALS=1 RUN_MODEL_COMPARISON=1",
)

EVAL_ROOT = Path(__file__).resolve().parent.parent.parent / "eval"

# ---------------------------------------------------------------------------
# Parametrize helpers
# ---------------------------------------------------------------------------


def _reasoning_params() -> list[tuple[str, Path]]:
    """(model_name, test_file) pairs for the reasoning stage."""
    models = STAGE_MODELS.get("reasoning", [])
    files = [f for f in STAGE_TEST_FILES.get("reasoning", []) if f.exists()]
    return [(m, f) for m in models for f in files]


def _context_params() -> list[tuple[str, Path]]:
    """(model_name, test_file) pairs for the context stage."""
    models = STAGE_MODELS.get("context", [])
    files = [f for f in STAGE_TEST_FILES.get("context", []) if f.exists()]
    return [(m, f) for m in models for f in files]


def _param_id(model_name: str, test_file: Path) -> str:
    return f"{model_name.split('/')[-1]}/{test_file.stem}"


# ---------------------------------------------------------------------------
# Session-level result accumulator for report generation
# ---------------------------------------------------------------------------


_session_results: list[ModelResult] = []


@pytest.fixture(scope="session", autouse=True)
def write_comparison_report(request):
    """Write markdown and JSON reports after the session completes."""
    yield
    if not _session_results:
        return
    project_root = Path(__file__).resolve().parent.parent.parent
    md = build_markdown_report(_session_results)
    (project_root / "model_comparison_report.md").write_text(md)
    report = build_json_report(_session_results)
    (project_root / "model_comparison_report.json").write_text(json.dumps(report, indent=2))
    print(f"\n\nModel comparison reports written to {project_root}/model_comparison_report.*")
    print(md)


# ---------------------------------------------------------------------------
# Reasoning agent tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_name,test_file",
    _reasoning_params(),
    ids=[_param_id(m, f) for m, f in _reasoning_params()],
)
async def test_reasoning_model_comparison(model_name: str, test_file: Path) -> None:
    """Reasoning agent: compare pass rate for a model against a golden dataset."""
    result = await run_model_on_test_file(
        stage="reasoning",
        model_name=model_name,
        test_file=test_file,
        runs_per_case=RUNS_PER_CASE,
    )
    _session_results.append(result)

    total = len(result.case_results)
    passing = sum(1 for c in result.case_results if c.passed)
    failures = [c for c in result.case_results if not c.passed]

    failure_details = "\n  ".join(
        f"{c.eval_id}: {c.passes}/{c.total_runs} runs passed" for c in failures
    )
    assert result.overall_pass_rate >= PASS_THRESHOLD, (
        f"Model {model_name} on {test_file.name}: "
        f"{passing}/{total} cases passed ({result.overall_pass_rate:.0%}), "
        f"threshold {PASS_THRESHOLD:.0%}.\n"
        f"Failures:\n  {failure_details}"
    )


# ---------------------------------------------------------------------------
# Context agent tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_name,test_file",
    _context_params(),
    ids=[_param_id(m, f) for m, f in _context_params()],
)
async def test_context_model_comparison(model_name: str, test_file: Path) -> None:
    """Context agent: compare JSON output validity for a model against a golden dataset."""
    result = await run_model_on_test_file(
        stage="context",
        model_name=model_name,
        test_file=test_file,
        runs_per_case=RUNS_PER_CASE,
    )
    _session_results.append(result)

    total = len(result.case_results)
    passing = sum(1 for c in result.case_results if c.passed)
    failures = [c for c in result.case_results if not c.passed]

    failure_details = "\n  ".join(
        f"{c.eval_id}: {c.passes}/{c.total_runs} runs passed" for c in failures
    )
    assert result.overall_pass_rate >= PASS_THRESHOLD, (
        f"Model {model_name} on {test_file.name}: "
        f"{passing}/{total} cases passed ({result.overall_pass_rate:.0%}), "
        f"threshold {PASS_THRESHOLD:.0%}.\n"
        f"Failures:\n  {failure_details}"
    )
