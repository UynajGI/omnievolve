"""Sort optimization evaluator.

演示如何为 OmniEvolve 实现一个 TaskEvaluator：
候选代码是一个排序函数，评估器运行 pytest 检查正确性 + benchmark 性能。
"""

from __future__ import annotations

import re

from omnievolve.eval.task_evaluator import (
    CandidateArtifact,
    CommandSpec,
    EvalOutput,
    EvaluationContext,
    EvaluationPlan,
    SandboxExecutionResult,
)


class SortEvaluator:
    """排序优化评估器.

    评估流程：
    1. 正确性门（必须通过所有测试）
    2. 性能评分（基于执行时间，越快越高）

    score = 0.5 * correctness + 0.5 * speedup_ratio
    """

    version_id = "sort-evaluator@1.0.0"

    def build_plan(
        self,
        candidate: CandidateArtifact,
        context: EvaluationContext,
    ) -> EvaluationPlan:
        """构建评估计划."""
        return EvaluationPlan(
            commands=[
                CommandSpec(
                    argv=["python", "-m", "pytest", "test_sort.py", "-v", "--tb=short"],
                    timeout_sec=10.0,
                ),
                CommandSpec(
                    argv=["python", "benchmark.py"],
                    timeout_sec=5.0,
                ),
            ],
            expected_outputs=["benchmark_result.json"],
            network_access=False,
        )

    def parse_result(
        self,
        result: SandboxExecutionResult,
        context: EvaluationContext,
    ) -> EvalOutput:
        """解析沙箱执行结果."""
        # 正确性门
        if result.timed_out:
            return EvalOutput(
                score=0.0,
                metrics={},
                passed=False,
                failure_reason="Timeout",
            )

        if not result.return_codes or result.return_codes[0] != 0:
            return EvalOutput(
                score=0.0,
                metrics={},
                passed=False,
                failure_reason=result.stderr[-500:] if result.stderr else "Tests failed",
            )

        # 从 benchmark 输出解析性能

        speedup = 1.0
        try:
            match = re.search(r'\{"speedup":\s*([\d.]+)', result.stdout)
            if match:
                speedup = float(match.group(1))
        except (ValueError, IndexError):
            pass

        score = 0.5 + 0.5 * min(speedup / 10.0, 1.0)  # 10x speedup = full score

        return EvalOutput(
            score=score,
            metrics={"speedup": speedup, "execution_time_ms": result.execution_time_ms},
            passed=True,
            confidence=0.9,
        )

    def get_baseline(self) -> float:
        """基线分数（Python 内置 sort）."""
        return 0.5
