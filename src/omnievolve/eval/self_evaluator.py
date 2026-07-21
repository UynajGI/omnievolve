"""轨道 B：自评估器 Facade.

设计文档 5.2 节指定此文件路径。
实际实现位于 telemetry.py，本模块提供 re-export 以满足设计文档路径约定。
"""

from omnievolve.eval.telemetry import (
    HealthOutput,
    HealthPolicy,
    SelfEvaluator,
    TelemetryAggregator,
)

__all__ = ["HealthOutput", "HealthPolicy", "SelfEvaluator", "TelemetryAggregator"]
