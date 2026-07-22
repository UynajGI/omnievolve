"""评估器模板 — 实现你的 TaskEvaluator.

OmniEvolve 评估器职责：
1. build_plan(): 声明如何在沙箱中评估候选代码（命令、挂载、超时）
2. parse_result(): 解析沙箱执行结果，返回分数和通过/失败

关键原则:
- 评估器只"声明"评估计划，不直接执行候选代码
- 所有执行由 Sandbox 完成（隔离环境）
- 评估语义不可被 Meta-Agent 修改（设计文档 §5.1.1）

使用方式:
    omnievolve run initial_code.py -e evaluator:MyEvaluator --trusted
"""

from __future__ import annotations

import json
import os
import re
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

# 评估器所在目录（用于挂载测试文件）
_WORKSPACE = os.path.dirname(os.path.abspath(__file__))


class MyEvaluator:
    """模板评估器 — 替换为你的任务逻辑.

    评估流程:
    1. 正确性门: 运行 pytest 测试（必须全部通过）
    2. 性能评分: 运行 benchmark，基于加速比打分

    分数公式:
        score = 0.5 (通过测试即得) + 0.5 * min(speedup / TARGET_SPEEDUP, 1.0)

    修改指南:
    - 修改 TARGET_SPEEDUP 调整满分难度
    - 修改 commands 添加/删除评估步骤
    - 修改 parse_result 中的分数公式
    """

    # 评估器版本（修改评估逻辑时必须更新）
    version_id = "my-evaluator@1.0.0"

    # 满分对应的加速比（相对于基线实现）
    TARGET_SPEEDUP = 5.0

    def build_plan(
        self,
        candidate: CandidateArtifact,
        context: EvaluationContext,
    ) -> EvaluationPlan:
        """构建评估计划 — 声明沙箱中要执行的命令.

        候选代码会被自动放置到 /workspace/solution.py。
        你只需要声明要运行什么命令、挂载什么辅助文件。
        """
        return EvaluationPlan(
            commands=[
                # 步骤 1: 正确性测试
                CommandSpec(
                    argv=[sys.executable, "-m", "pytest", "test_solution.py", "-v", "--tb=short"],
                    timeout_sec=15.0,
                ),
                # 步骤 2: 性能基准测试
                CommandSpec(
                    argv=[sys.executable, "benchmark.py"],
                    timeout_sec=10.0,
                ),
            ],
            mounts=[
                # 挂载测试文件和 benchmark 到沙箱
                MountSpec(
                    source=os.path.join(_WORKSPACE, "test_solution.py"),
                    target="/workspace/test_solution.py",
                ),
                MountSpec(
                    source=os.path.join(_WORKSPACE, "benchmark.py"),
                    target="/workspace/benchmark.py",
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
        """解析沙箱执行结果 → 分数.

        返回:
            EvalOutput(score=0.0~1.0, passed=bool, metrics=dict)
        """
        # 超时 → 直接失败
        if result.timed_out:
            return EvalOutput(
                score=0.0,
                metrics={},
                passed=False,
                failure_reason="Execution timeout",
            )

        # 正确性门: 第一个命令（pytest）必须返回 0
        if not result.return_codes or result.return_codes[0] != 0:
            return EvalOutput(
                score=0.0,
                metrics={},
                passed=False,
                failure_reason=result.stderr[-500:] if result.stderr else "Tests failed",
            )

        # 从 benchmark 输出解析性能指标
        speedup = 1.0
        try:
            match = re.search(r'\{"speedup":\s*([\d.]+)', result.stdout)
            if match:
                speedup = float(match.group(1))
        except (ValueError, IndexError):
            pass

        # 分数公式: 通过测试得 0.5 + 性能奖励最多 0.5
        score = 0.5 + 0.5 * min(speedup / self.TARGET_SPEEDUP, 1.0)

        return EvalOutput(
            score=score,
            metrics={
                "speedup": speedup,
                "execution_time_ms": result.execution_time_ms,
            },
            passed=True,
            confidence=0.9,
        )

    def get_baseline(self) -> float:
        """基线分数 — 初始代码的预期分数."""
        return 0.5
