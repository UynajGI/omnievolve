"""#71 Occam's Circuit 评估器（OmniEvolve TaskEvaluator）。

评估流程（两步沙箱命令）：
    1. main.py          —— 候选（被进化的电路综合策略），读 train/test_inputs，写出 circuit.txt
    2. verify_circuit.py —— 验证器，在 train/test 上模拟电路、与真值比对，输出评分 JSON

评分（对齐题面排行榜：精度优先、门数次之）：
    score  = 0.7 * test_acc + 0.3 * max(0, 1 - gates / GATE_CAP)
    passed = train_acc == 1.0（拟合训练集）且 test_acc >= 0.99（能泛化）

不可作弊：test 输出由验证器持有并比对，候选只见 train + test_inputs；
记忆 train 的电路 test_acc 会很低，无法靠记忆得高分。

隔离说明：test_outputs.csv 挂载到 /verifier_data/（非 /workspace/），
在 docker 沙箱中候选无法访问。trusted_subprocess 模式无文件隔离（已知限制，
仅用于开发调试；正式评估须切 docker/monty 后端）。
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


class OccamCircuitEvaluator:
    """Occam's Circuit 评估器。"""

    version_id = "occam-circuit@1.0.0"

    # 评估实例（practice 真值公开；mystery 需官方 release 数据）
    INSTANCE = "practice-add-n4"
    GATE_CAP = 150.0  # 门数满分参考（越少越好）

    def _ds(self, name: str) -> str:
        return os.path.join(_WORKSPACE, "datasets", self.INSTANCE, name)

    def build_plan(
        self, candidate: CandidateArtifact, context: EvaluationContext
    ) -> EvaluationPlan:
        return EvaluationPlan(
            commands=[
                CommandSpec(argv=[sys.executable, "main.py"], timeout_sec=40.0),
                CommandSpec(argv=[sys.executable, "verify_circuit.py"], timeout_sec=30.0),
            ],
            mounts=[
                MountSpec(source=os.path.join(_WORKSPACE, "verify_circuit.py"), target="/workspace/verify_circuit.py"),
                MountSpec(source=self._ds("train.csv"), target="/workspace/train.csv"),
                MountSpec(source=self._ds("test_inputs.csv"), target="/workspace/test_inputs.csv"),
                # test_outputs 挂载到 /verifier_data/（非 /workspace/），docker 模式下候选不可见
                MountSpec(source=self._ds("test_outputs.csv"), target="/verifier_data/test_outputs.csv"),
            ],
            expected_outputs=["circuit.txt", "verify_result.json"],
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
            if isinstance(obj, dict) and "test_acc" in obj:
                verify = obj
                break

        if verify is None or not verify.get("valid", False):
            reason = verify.get("error", "no verifier output") if verify else "no verifier output"
            return EvalOutput(score=0.0, metrics={}, passed=False, failure_reason=reason)

        test_acc = float(verify["test_acc"])
        train_acc = float(verify["train_acc"])
        gates = int(verify["gates"])
        gate_term = max(0.0, 1.0 - gates / self.GATE_CAP)
        score = 0.7 * test_acc + 0.3 * gate_term
        passed = train_acc == 1.0 and test_acc >= 0.99

        return EvalOutput(
            score=score,
            metrics={
                "test_acc": test_acc,
                "train_acc": train_acc,
                "bit_acc": verify.get("bit_acc", 0.0),
                "gates": gates,
                "gate_term": gate_term,
                "execution_time_ms": result.execution_time_ms,
            },
            passed=passed,
            confidence=0.95,
        )

    def get_baseline(self) -> float:
        """基线分数：种子在 practice-add 上约 0.95（test_acc=1.0, ~23 门）。"""
        return 0.7
