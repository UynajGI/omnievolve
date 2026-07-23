"""流水线计时仪表化.

从 ShinkaEvolve pipeline_timing.py 移植。
记录各阶段耗时，写入 candidate metadata。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any


class PipelineTimer:
    """流水线计时器 — 上下文管理器."""

    def __init__(self) -> None:
        self._timings: dict[str, float] = {}
        self._current: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str):
        """计时上下文管理器.

        Usage:
            timer = PipelineTimer()
            with timer.stage("sampling"):
                # do sampling
            with timer.stage("evaluation"):
                # do evaluation
        """
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self._timings[name] = self._timings.get(name, 0.0) + elapsed

    @property
    def timings(self) -> dict[str, float]:
        """获取所有计时数据."""
        return dict(self._timings)

    def reset(self) -> None:
        """重置计时器."""
        self._timings.clear()

    def total(self) -> float:
        """总耗时."""
        return sum(self._timings.values())

    def to_dict(self) -> dict[str, float]:
        """转换为 metadata dict 格式.

        Key 命名与 ShinkaEvolve 对齐: {stage}_seconds
        """
        return {f"{k}_seconds": v for k, v in self._timings.items()}


def with_pipeline_timing(metadata: dict[str, Any] | None = None, **timings: float) -> dict[str, Any]:
    """合并计时到 metadata dict.

    Args:
        metadata: 原有 metadata（可为 None）
        **timings: 计时键值对 (sampling=1.5, evaluation=3.2)

    Returns:
        合并后的 metadata dict
    """
    result = dict(metadata) if metadata else {}
    for key, value in timings.items():
        result[f"{key}_seconds"] = value
    return result


def summarize_timing(records: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """聚合多候选的计时数据.

    Args:
        records: 候选 metadata 列表

    Returns:
        {stage: {mean, median, min, max, std}}
    """
    import statistics

    stage_times: dict[str, list[float]] = {}

    for record in records:
        for key, value in record.items():
            if key.endswith("_seconds") and isinstance(value, (int, float)):
                stage = key.replace("_seconds", "")
                if stage not in stage_times:
                    stage_times[stage] = []
                stage_times[stage].append(float(value))

    summary: dict[str, dict[str, float]] = {}
    for stage, times in stage_times.items():
        if times:
            summary[stage] = {
                "mean": statistics.mean(times),
                "median": statistics.median(times),
                "min": min(times),
                "max": max(times),
                "std": statistics.stdev(times) if len(times) > 1 else 0.0,
                "count": len(times),
            }

    return summary
