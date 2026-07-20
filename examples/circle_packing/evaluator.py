"""Circle Packing 评估器.

评估圆打包方案的质量：最小半径越大越好。
"""

from __future__ import annotations

import sys

from omnievolve.eval.task_evaluator import (
    CandidateArtifact,
    CommandSpec,
    EvalOutput,
    EvaluationContext,
    EvaluationPlan,
)


class CirclePackingEvaluator:
    """评估圆打包方案."""

    version_id = "circle-packing@1.0.0"

    def build_plan(
        self, candidate: CandidateArtifact, context: EvaluationContext
    ) -> EvaluationPlan:
        return EvaluationPlan(
            commands=[
                CommandSpec(
                    argv=[sys.executable, "-c", candidate_source],
                    timeout_sec=5.0,
                )
            ],
        )

    def parse_result(self, result, context: EvaluationContext) -> EvalOutput:
        if result.return_codes and result.return_codes[0] == 0:
            try:
                score = float(result.stdout.strip().split("\n")[-1])
            except (ValueError, IndexError):
                score = 0.0
            return EvalOutput(
                score=max(0.0, score),
                metrics={"fitness": score},
                passed=score > 0,
            )
        return EvalOutput(score=0.0, metrics={}, passed=False)

    def get_baseline(self) -> float:
        return 0.0


# 在沙箱中执行的 eval 代码
candidate_source = """
import math


def pack_circles(num_circles, positions, radii):
    min_radius = float("inf")
    for i in range(num_circles):
        x_i, y_i = positions[i]
        r_max = min(x_i, 1.0 - x_i, y_i, 1.0 - y_i)
        min_radius = min(min_radius, r_max)
        for j in range(i + 1, num_circles):
            x_j, y_j = positions[j]
            dist = math.hypot(x_i - x_j, y_i - y_j)
            min_radius = min(min_radius, dist - radii[j])
    return -min_radius


def solve():
    n = 12
    radius = 0.08
    positions = [
        (0.2, 0.2), (0.5, 0.2), (0.8, 0.2),
        (0.2, 0.5), (0.5, 0.5), (0.8, 0.5),
        (0.2, 0.8), (0.5, 0.8), (0.8, 0.8),
        (0.35, 0.35), (0.65, 0.35), (0.5, 0.65),
    ]
    radii = [radius] * n
    return pack_circles(n, positions, radii)


if __name__ == "__main__":
    print(solve())
"""
