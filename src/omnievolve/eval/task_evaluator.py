"""TaskEvaluator Protocol 与数据结构.

S3-01 ~ S3-02: 冻结 EvaluationPlan/EvalOutput/EvaluationContext
- TaskEvaluator Protocol (build_plan/parse_result/get_baseline)
- Evaluator 只能构造声明式 EvaluationPlan 和解析 Sandbox 结果
- 不能在宿主机直接运行候选代码
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# 复用 sandbox/base.py 中的数据结构
from omnievolve.sandbox.base import (
    CandidateArtifact,
    CommandSpec,
    EvaluationPlan,
    MountSpec,
    SandboxExecutionResult,
)


@dataclass(frozen=True)
class EvaluationContext:
    """评估上下文."""

    experiment_id: str
    evaluator_version_id: str
    environment_version_id: str
    seed: int | None = None
    split_name: str = "default"
    extra_context: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EvalOutput:
    """评估输出."""

    score: float
    metrics: dict[str, float]
    passed: bool
    failure_reason: str = ""
    confidence: float | None = None


@runtime_checkable
class TaskEvaluator(Protocol):
    """任务评估器协议.

    用户实现此接口。
    Evaluator 只能构造声明式 EvaluationPlan 和解析 Sandbox 结果，
    不能在宿主机直接运行候选代码。
    """

    @property
    def version_id(self) -> str:
        """评估器版本 ID."""
        ...

    def build_plan(
        self,
        candidate: CandidateArtifact,
        context: EvaluationContext,
    ) -> EvaluationPlan:
        """构建评估计划.

        Args:
            candidate: 候选 Artifact 信息
            context: 评估上下文

        Returns:
            声明式评估计划（命令、挂载、预期输出）
        """
        ...

    def parse_result(
        self,
        result: SandboxExecutionResult,
        context: EvaluationContext,
    ) -> EvalOutput:
        """解析沙箱执行结果.

        Args:
            result: 沙箱执行结果
            context: 评估上下文

        Returns:
            评估输出（分数、指标、通过/失败）
        """
        ...

    def get_baseline(self) -> float:
        """获取基线分数.

        Returns:
            基线分数（用于比较和归一化）
        """
        ...


# 导出常用类型
__all__ = [
    "CandidateArtifact",
    "CommandSpec",
    "EvaluationContext",
    "EvaluationPlan",
    "EvalOutput",
    "MountSpec",
    "SandboxExecutionResult",
    "TaskEvaluator",
]
