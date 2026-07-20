"""Heilbronn Triangle 评估器.

评估 11 个点在等边三角形内的最小三角形面积。
score = min_area_normalized / BENCHMARK。
"""

from __future__ import annotations

import json
import sys

from omnievolve.eval.task_evaluator import (
    CandidateArtifact,
    CommandSpec,
    EvalOutput,
    EvaluationContext,
    EvaluationPlan,
)


class HeilbronnEvaluator:
    """评估 Heilbronn 三角形点排列质量."""

    version_id = "heilbronn-triangle@1.0.0"

    def build_plan(
        self, candidate: CandidateArtifact, context: EvaluationContext
    ) -> EvaluationPlan:
        return EvaluationPlan(
            commands=[
                CommandSpec(
                    argv=[sys.executable, "main.py"],
                    timeout_sec=10.0,
                    env={
                        "OPENBLAS_NUM_THREADS": "1",
                        "OMP_NUM_THREADS": "1",
                    },
                )
            ],
        )

    def parse_result(self, result, context: EvaluationContext) -> EvalOutput:
        if not result.return_codes or result.return_codes[0] != 0:
            return EvalOutput(
                score=0.0,
                metrics={"error": "sandbox execution failed"},
                passed=False,
            )

        try:
            data = json.loads(result.stdout.strip().split("\n")[-1])
        except (json.JSONDecodeError, IndexError, ValueError):
            return EvalOutput(
                score=0.0,
                metrics={"error": "failed to parse output"},
                passed=False,
            )

        score = data.get("combined_score", 0.0)
        min_area = data.get("min_area_normalized", 0.0)

        return EvalOutput(
            score=score,
            metrics={
                "combined_score": score,
                "min_area_normalized": min_area,
            },
            passed=True,
        )

    def get_baseline(self) -> float:
        return 0.0
