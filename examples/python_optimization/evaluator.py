"""Sort optimization evaluator.

演示如何为 OmniEvolve 实现一个 TaskEvaluator：
候选代码是一个排序函数，评估器运行 pytest 检查正确性 + benchmark 性能。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

from omnievolve.eval.task_evaluator import (
    CandidateArtifact,
    CommandSpec,
    EvalOutput,
    EvaluationContext,
    EvaluationPlan,
    MountSpec,
    SandboxExecutionResult,
)

_WORKSPACE = os.path.dirname(os.path.abspath(__file__))


def _digest(filename: str) -> str:
    path = os.path.join(_WORKSPACE, filename)
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class SortEvaluator:
    """排序优化评估器.

    评估流程：
    1. 正确性门（必须通过所有测试）
    2. 性能评分（基于执行时间，越快越高）

    score = 0.5 * correctness + 0.5 * speedup_ratio
    """

    version_id = "sort-evaluator@1.1.0"

    def build_plan(
        self,
        candidate: CandidateArtifact,
        context: EvaluationContext,
    ) -> EvaluationPlan:
        """构建评估计划."""
        return EvaluationPlan(
            commands=[
                CommandSpec(
                    argv=[
                        sys.executable, "-m", "pytest", "test_sort.py",
                        "-v", "--tb=short", "-p", "no:anyio", "-p", "no:asyncio",
                    ],
                    timeout_sec=10.0,
                ),
                CommandSpec(
                    argv=[sys.executable, "benchmark.py"],
                    timeout_sec=5.0,
                ),
            ],
            mounts=[
                MountSpec(
                    source=os.path.join(_WORKSPACE, "test_sort.py"),
                    target="/workspace/test_sort.py",
                    visibility="hidden",
                    integrity_sha256=_digest("test_sort.py"),
                ),
                MountSpec(
                    source=os.path.join(_WORKSPACE, "benchmark.py"),
                    target="/workspace/benchmark.py",
                    visibility="hidden",
                    integrity_sha256=_digest("benchmark.py"),
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

        benchmark = {}
        for line in reversed(result.stdout.splitlines()):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and "speedup" in parsed:
                benchmark = parsed
                break
        if not benchmark:
            return EvalOutput(
                score=0.0,
                metrics={},
                passed=False,
                failure_reason="Benchmark produced no valid JSON result",
            )

        speedup = float(benchmark["speedup"])
        speedup_ci_low = float(benchmark.get("speedup_ci_low", speedup))
        speedup_ci_high = float(benchmark.get("speedup_ci_high", speedup))
        time_ms = float(benchmark.get("time_ms", result.execution_time_ms))
        repetitions = float(benchmark.get("repetitions", 1))

        # Score the conservative lower confidence bound so noisy one-off wins
        # cannot displace a reproducibly faster candidate.
        score = 0.5 + 0.5 * min(max(speedup_ci_low, 0.0) / 10.0, 1.0)
        interval_width = max(speedup_ci_high - speedup_ci_low, 0.0)
        relative_margin = interval_width / (2.0 * max(abs(speedup), 1e-12))
        confidence = 0.95 if repetitions >= 10 and relative_margin <= 0.25 else 0.8

        return EvalOutput(
            score=score,
            metrics={
                "speedup": speedup,
                "speedup_ci_low": speedup_ci_low,
                "speedup_ci_high": speedup_ci_high,
                "benchmark_time_ms": time_ms,
                "benchmark_repetitions": repetitions,
                "benchmark_relative_margin": relative_margin,
                "execution_time_ms": result.execution_time_ms,
            },
            passed=True,
            confidence=confidence,
        )

    def get_baseline(self) -> float:
        """基线分数（Python 内置 sort）."""
        return 0.5
