"""Circle Packing 评估器.

评估圆打包方案的质量：最小半径越大越好。

候选代码由 Sandbox 写入 main.py，评估器运行 python main.py 并解析输出。
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
                    argv=[sys.executable, "main.py"],
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
                score=score,
                metrics={"fitness": score},
                passed=True,  # 执行成功即为通过，负分由进化自然优化
            )
        return EvalOutput(score=0.0, metrics={}, passed=False)

    def get_baseline(self) -> float:
        return 0.0
