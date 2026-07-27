"""#78 ORBIT-Q 评估器（OmniEvolve TaskEvaluator）。

评估流程（两步沙箱命令）：
    1. main.py          —— 候选代码（被进化的 TensorCircuit-NG 解法），写出 candidate_result.json
    2. task_wrapper.py  —— 验证器，运行 functional check + 测量 wall-time

评分（functional 门 + 加速比）：
    score = functional_pass * clip(ref_time / wall_time, 0, 1)
    passed = functional_pass 且 wall_time < ref_time

环境依赖（重型）：tensorcircuit-ng + JAX + ORBIT-Q 仓库。
当前为桩实现——functional check 信任候选自报（待集成官方验证器）。

不可作弊（完整实现后）：functional check 由官方验证器独立运行，
wall-time 由验证器测量，候选无法伪造。
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


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class OrbitQEvaluator:
    """ORBIT-Q TensorCircuit-NG 加速评估器。"""

    version_id = "orbit-q@1.0.0"

    def build_plan(
        self, candidate: CandidateArtifact, context: EvaluationContext
    ) -> EvaluationPlan:
        return EvaluationPlan(
            commands=[
                CommandSpec(
                    argv=[sys.executable, "main.py"],
                    timeout_sec=180.0,  # 量子电路模拟可能较慢
                    env={
                        "JAX_PLATFORM_NAME": "cpu",  # 默认 CPU；GPU 环境可改
                    },
                ),
                CommandSpec(
                    argv=[sys.executable, "task_wrapper.py"],
                    timeout_sec=30.0,
                ),
            ],
            mounts=[
                MountSpec(source=os.path.join(_WORKSPACE, "task_wrapper.py"), target="/workspace/task_wrapper.py"),
            ],
            expected_outputs=["candidate_result.json", "verify_result.json"],
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

        verify = None
        for line in reversed(result.stdout.strip().splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "functional_pass" in obj:
                verify = obj
                break

        if verify is None:
            return EvalOutput(score=0.0, metrics={}, passed=False, failure_reason="no verifier output")

        if not verify.get("valid", False):
            return EvalOutput(
                score=0.0, metrics={}, passed=False,
                failure_reason=verify.get("error", "invalid result"),
            )

        functional_pass = verify.get("functional_pass", False)
        wall_time = float(verify.get("wall_time_sec", 0.0))
        ref_time = float(verify.get("ref_time_sec", 1.0))

        if functional_pass and wall_time > 0:
            speedup = ref_time / wall_time
            score = _clip(speedup, 0.0, 1.0)
        else:
            speedup = 0.0
            score = 0.0

        passed = functional_pass and wall_time < ref_time

        return EvalOutput(
            score=score,
            metrics={
                "functional_pass": float(functional_pass),
                "wall_time_sec": wall_time,
                "ref_time_sec": ref_time,
                "speedup": speedup,
                "execution_time_ms": result.execution_time_ms,
            },
            passed=passed,
            confidence=0.90,  # 桩实现，待官方验证器集成后提升
        )

    def get_baseline(self) -> float:
        """基线：与专家解法持平（speedup=1.0 → score=1.0）。"""
        return 1.0
