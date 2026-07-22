"""轨道 B：自评估器 Protocol 定义 + 默认实现 re-export.

设计文档 §5.2: TelemetryAggregator / HealthPolicy / MetaPlanner / SelfEvaluator
应为 Protocol，允许用户 duck-typing 替换。

具体实现位于 telemetry.py，本模块定义 Protocol 并 re-export 默认实现。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from omnievolve.eval.telemetry import (
    AlertLevel,
    HealthOutput,
    HealthPolicy as DefaultHealthPolicy,
    SelfEvaluator as DefaultSelfEvaluator,
    TelemetryAggregator as DefaultTelemetryAggregator,
)

# ---------------------------------------------------------------------------
# Protocol 定义（设计文档 §5.2）
# ---------------------------------------------------------------------------


@runtime_checkable
class TelemetryAggregatorProtocol(Protocol):
    """遥测聚合器 Protocol.

    计算客观、可复现指标。
    """

    def aggregate(
        self,
        experiment_id: str,
        generation_start: int,
        generation_end: int,
    ) -> Any:
        """聚合指定窗口内的遥测指标."""
        ...


@runtime_checkable
class HealthPolicyProtocol(Protocol):
    """健康策略 Protocol.

    规则与统计判定。
    """

    def assess(
        self,
        metrics: Any,
        *,
        experiment_id: str | None = None,
        generation_start: int = 0,
        generation_end: int = 0,
        search_policy_id: str = "default",
    ) -> HealthOutput:
        """评估健康度."""
        ...


@runtime_checkable
class SelfEvaluatorProtocol(Protocol):
    """自评估器 Protocol — 轨道 B Facade.

    用户可实现此接口替换默认自评估逻辑。
    """

    def assess(
        self,
        experiment_id: str,
        generation_start: int,
        generation_end: int,
    ) -> HealthOutput:
        """评估健康度."""
        ...


# ---------------------------------------------------------------------------
# Re-export 默认实现（向后兼容）
# ---------------------------------------------------------------------------

TelemetryAggregator = DefaultTelemetryAggregator
HealthPolicy = DefaultHealthPolicy
SelfEvaluator = DefaultSelfEvaluator

__all__ = [
    # Protocols
    "TelemetryAggregatorProtocol",
    "HealthPolicyProtocol",
    "SelfEvaluatorProtocol",
    # 默认实现
    "TelemetryAggregator",
    "HealthPolicy",
    "SelfEvaluator",
    # 数据类型
    "HealthOutput",
    "AlertLevel",
]
