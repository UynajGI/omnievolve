"""#127 Contract Cheaper 评估器（OmniEvolve TaskEvaluator）。

评估流程（两步沙箱命令）：
    1. main.py           —— 候选代码（被进化的收缩顺序搜索策略），写出 candidate_result.json
    2. cost_checker.py   —— 验证器，从候选收缩树独立重算 FLOPs / 峰值内存

评分（正确性门 + 性能分）：
    valid = 收缩树合法（步数正确、操作数可用、最终剩一个张量）
    perf  = clip(baseline_flops / cost_flops, 0, 1)
    score = 0.5 (valid 即得) + 0.5 * perf
    passed = valid 且 cost_flops < baseline_flops

不可作弊：FLOPs 由验证器从候选输出的收缩树 + 实例定义独立重算，
候选无法通过谎报代价获利。
"""

from __future__ import annotations

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

# 基线代价（greedy 收缩的 FLOPs，由 cost_checker 验证）
BASELINE_FLOPS = 59049  # grid3x3_d3 greedy


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class ContractCheaperEvaluator:
    """张量网络收缩代价优化评估器。"""

    version_id = "contract-cheaper@1.0.0"

    def build_plan(
        self, candidate: CandidateArtifact, context: EvaluationContext
    ) -> EvaluationPlan:
        return EvaluationPlan(
            commands=[
                # 步骤 1：候选搜索策略，写出 candidate_result.json
                CommandSpec(
                    argv=[sys.executable, "main.py"],
                    timeout_sec=50.0,
                    env={
                        "OPENBLAS_NUM_THREADS": "1",
                        "OMP_NUM_THREADS": "1",
                        "MKL_NUM_THREADS": "1",
                    },
                ),
                # 步骤 2：验证器独立重算代价
                CommandSpec(
                    argv=[sys.executable, "cost_checker.py", "instance.json"],
                    timeout_sec=10.0,
                ),
            ],
            mounts=[
                MountSpec(source=os.path.join(_WORKSPACE, "cost_checker.py"), target="/workspace/cost_checker.py"),
                MountSpec(source=os.path.join(_WORKSPACE, "instances", "grid3x3_d3.json"), target="/workspace/instance.json"),
            ],
            expected_outputs=["candidate_result.json"],
            network_access=False,
        )

    def parse_result(
        self, result: SandboxExecutionResult, context: EvaluationContext
    ) -> EvalOutput:
        if result.timed_out:
            return EvalOutput(score=0.0, metrics={}, passed=False, failure_reason="timeout")

        if not result.return_codes or result.return_codes[0] != 0:
            tail = (result.stderr or "")[-500:]
            return EvalOutput(score=0.0, metrics={}, passed=False, failure_reason=f"candidate failed: {tail}")

        # 从 stdout 末尾扫描验证器输出
        verify = None
        for line in reversed(result.stdout.strip().splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "flops" in obj:
                verify = obj
                break

        if verify is None:
            return EvalOutput(score=0.0, metrics={}, passed=False, failure_reason="no verifier output")

        if not verify.get("valid", False):
            return EvalOutput(
                score=0.0,
                metrics={},
                passed=False,
                failure_reason=verify.get("error", "invalid contraction tree"),
            )

        flops = int(verify["flops"])
        peak_mem = int(verify.get("peak_memory_bytes", 0))
        perf = _clip(BASELINE_FLOPS / max(flops, 1), 0.0, 1.0)
        score = 0.5 + 0.5 * perf
        passed = flops < BASELINE_FLOPS

        return EvalOutput(
            score=score,
            metrics={
                "flops": float(flops),
                "peak_memory_bytes": float(peak_mem),
                "baseline_flops": float(BASELINE_FLOPS),
                "speedup": BASELINE_FLOPS / max(flops, 1),
                "perf": perf,
                "execution_time_ms": result.execution_time_ms,
            },
            passed=passed,
            confidence=0.99,  # 精确整数算术，确定性验证
        )

    def get_baseline(self) -> float:
        """基线分数：greedy 收缩（score = 0.5 + 0.5 * 1.0 = 1.0 当 flops == baseline）。"""
        return 1.0
