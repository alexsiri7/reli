"""Custom trajectory evaluator that matches tool names only (ignores args).

ADK's built-in TrajectoryEvaluator compares both tool names AND args exactly,
which is too strict for non-deterministic models where args vary between runs.
This evaluator only checks that the expected tool names appear in the actual
tool calls, in order, allowing extra calls in between.
"""

from __future__ import annotations

from typing import Optional

from google.adk.evaluation.eval_case import Invocation
from google.adk.evaluation.evaluator import EvaluationResult, Evaluator, PerInvocationResult
from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus
from google.adk.evaluation.trajectory_evaluator import get_all_tool_calls
from google.genai import types as genai_types


class ToolNameTrajectoryEvaluator(Evaluator):
    """Evaluates that expected tool names appear in actual calls, in order."""

    def __init__(self, threshold: float = 0.8, eval_metric: Optional[EvalMetric] = None):
        self._threshold = eval_metric.threshold if eval_metric else threshold

    def evaluate_invocations(
        self,
        actual_invocations: list[Invocation],
        expected_invocations: Optional[list[Invocation]] = None,
        **kwargs,
    ) -> EvaluationResult:
        if expected_invocations is None:
            raise ValueError("expected_invocations is needed by this metric.")

        total_score = 0.0
        per_invocation_results = []

        for actual, expected in zip(actual_invocations, expected_invocations):
            actual_names = [tc.name for tc in get_all_tool_calls(actual.intermediate_data)]
            expected_names = [tc.name for tc in get_all_tool_calls(expected.intermediate_data)]

            score = self._names_in_order(actual_names, expected_names)
            status = EvalStatus.PASSED if score >= self._threshold else EvalStatus.FAILED

            per_invocation_results.append(
                PerInvocationResult(
                    actual_invocation=actual,
                    expected_invocation=expected,
                    score=score,
                    eval_status=status,
                )
            )
            total_score += score

        if per_invocation_results:
            overall = total_score / len(per_invocation_results)
            return EvaluationResult(
                overall_score=overall,
                overall_eval_status=EvalStatus.PASSED if overall >= self._threshold else EvalStatus.FAILED,
                per_invocation_results=per_invocation_results,
            )
        return EvaluationResult()

    @staticmethod
    def _names_in_order(actual: list[str], expected: list[str]) -> float:
        """Check that all expected names appear in actual, in order. Extra calls are OK."""
        if not expected:
            return 1.0
        if not actual:
            return 0.0

        expected_iter = iter(expected)
        current = next(expected_iter)
        for name in actual:
            if name == current:
                try:
                    current = next(expected_iter)
                except StopIteration:
                    return 1.0
        return 0.0
