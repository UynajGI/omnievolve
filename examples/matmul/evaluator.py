"""MatMul Tensor Decomposition 评估器.

评估候选代码找到的矩阵乘法张量分解 rank。
候选代码由 Sandbox 写入 main.py，输出 JSON 到 stdout。
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


class MatmulEvaluator:
    """评估 <2,4,5> 矩阵乘法张量分解质量.

    score = BENCHMARK / rank，rank 越低越好。
    """

    version_id = "matmul-tensor-decomp@1.0.0"
    BENCHMARK = 32.0  # Google AlphaEvolve 找到的最佳 rank

    def build_plan(
        self, candidate: CandidateArtifact, context: EvaluationContext
    ) -> EvaluationPlan:
        return EvaluationPlan(
            commands=[
                CommandSpec(
                    argv=[sys.executable, "main.py"],
                    timeout_sec=120.0,  # JAX 80k 步优化需要时间
                )
            ],
        )

    def parse_result(self, result, context: EvaluationContext) -> EvalOutput:
        # 检查执行是否成功
        if not result.return_codes or result.return_codes[0] != 0:
            return EvalOutput(
                score=0.0,
                metrics={"error": "sandbox execution failed"},
                passed=False,
            )

        # 解析 stdout JSON
        try:
            data = json.loads(result.stdout.strip().split("\n")[-1])
        except (json.JSONDecodeError, IndexError, ValueError):
            return EvalOutput(
                score=0.0,
                metrics={"error": "failed to parse output"},
                passed=False,
            )

        loss = data.get("loss", float("inf"))
        rank = data.get("rank", 999)
        combined_score = data.get("combined_score", 0.0)

        # loss 足够小才算通过
        success_threshold = 1e-4
        passed = loss < success_threshold

        return EvalOutput(
            score=combined_score,
            metrics={
                "loss": loss,
                "rank": rank,
                "combined_score": combined_score,
            },
            passed=passed,
        )

    def get_baseline(self) -> float:
        return 0.0
