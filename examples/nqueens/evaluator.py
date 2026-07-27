"""#34 N-queens 评估器（OmniEvolve TaskEvaluator）。

评估流程（两步沙箱命令）：
    1. main.py         —— 候选代码（被进化的 TN 收缩策略），写出 candidate_result.json
    2. verify_nq.py    —— 验证器，用 OEIS 精确值比对候选输出的 Q(N)

评分（正确性门 + 效率奖励）：
    valid = 候选输出 Q(N) 为整数 且 N 在验证范围内
    exact = Q_candidate == Q_exact（OEIS 参考）
    score = 1.0 (exact match) 或 0.5 * (1 - |log10(Q_cand/Q_exact)|) (近似)
    passed = exact match 且 N >= TARGET_N

不可作弊：Q(N) 的精确值由验证器从内置 OEIS 参考比对，候选无法伪造。
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

# 目标 N（当前评估实例）
TARGET_N = 8


class NQueensEvaluator:
    """N-queens TN 收缩评估器。"""

    version_id = "nqueens@1.0.0"

    def build_plan(
        self, candidate: CandidateArtifact, context: EvaluationContext
    ) -> EvaluationPlan:
        return EvaluationPlan(
            commands=[
                CommandSpec(
                    argv=[sys.executable, "main.py"],
                    timeout_sec=100.0,
                    env={
                        "OPENBLAS_NUM_THREADS": "1",
                        "OMP_NUM_THREADS": "1",
                        "MKL_NUM_THREADS": "1",
                        "NQUEENS_N": str(TARGET_N),
                    },
                ),
                CommandSpec(
                    argv=[sys.executable, "verify_nq.py"],
                    timeout_sec=10.0,
                ),
            ],
            mounts=[
                MountSpec(source=os.path.join(_WORKSPACE, "verify_nq.py"), target="/workspace/verify_nq.py"),
                MountSpec(source=os.path.join(_WORKSPACE, "oeis_ref.py"), target="/workspace/oeis_ref.py"),
                MountSpec(source=os.path.join(_WORKSPACE, "tn_construct.py"), target="/workspace/tn_construct.py"),
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
            if isinstance(obj, dict) and "q_computed" in obj:
                verify = obj
                break

        if verify is None:
            return EvalOutput(score=0.0, metrics={}, passed=False, failure_reason="no verifier output")

        if not verify.get("valid", False):
            return EvalOutput(
                score=0.0,
                metrics={},
                passed=False,
                failure_reason=verify.get("error", "invalid result"),
            )

        exact = verify.get("exact", False)
        score = float(verify.get("score", 0.0))
        passed = exact and verify.get("n", 0) >= TARGET_N

        return EvalOutput(
            score=score,
            metrics={
                "q_computed": float(verify["q_computed"]),
                "q_exact": float(verify.get("q_exact", 0)),
                "n": float(verify.get("n", 0)),
                "exact_match": float(exact),
                "wall_time_sec": float(verify.get("wall_time_sec", 0)),
                "execution_time_ms": result.execution_time_ms,
            },
            passed=passed,
            confidence=0.99,
        )

    def get_baseline(self) -> float:
        """基线：N=8 精确收缩成功（score 1.0）。"""
        return 1.0
