"""MetricValue — 带方向元数据的指标包装器.

从 MLEvolve utils/metric.py 精简移植（去掉 numpy/dataclasses_json 依赖）。
支持 maximize/minimize 方向的安全比较。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import total_ordering
from typing import Any


@dataclass
@total_ordering
class MetricValue:
    """带方向的度量值类型.

    Args:
        value: 度量值（None 表示最差/无效）
        maximize: True=最大化（越大越好），False=最小化（越小越好）
    """

    value: float | None
    maximize: bool = True

    def __post_init__(self) -> None:
        if self.value is not None:
            self.value = float(self.value)

    def __gt__(self, other: Any) -> bool:
        """Return True if *self* represents a better metric than *other*."""
        if self.value is None:
            return False
        if not isinstance(other, MetricValue) or other.value is None:
            return True
        if self.value == other.value:
            return False
        comp = self.value > other.value
        return comp if self.maximize else not comp

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, MetricValue):
            return NotImplemented
        return self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)

    def __repr__(self) -> str:
        return str(self)

    def __str__(self) -> str:
        opt = "↑" if self.maximize else "↓"
        val = f"{self.value:.4f}" if self.value is not None else "NaN"
        return f"Metric{opt}({val})"

    @property
    def is_worst(self) -> bool:
        """True if the metric value is the worst possible value."""
        return self.value is None


@dataclass
@total_ordering
class WorstMetricValue(MetricValue):
    """最差度量值（用于错误情况）.

    永远比较为最差，不依赖方向。
    """

    value: None = None
