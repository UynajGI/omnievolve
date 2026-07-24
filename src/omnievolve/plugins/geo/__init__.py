"""地理空间计算领域插件.

提供地理空间算法优化场景的领域提示。

TODO(延后): 实现完整的 enrich_evaluation（坐标系误差检测、空间索引性能指标）
            和 get_rag_corpus（地理空间算法语料库）。
"""

from __future__ import annotations

from typing import Any

from omnievolve.eval.task_evaluator import CandidateArtifact, EvalOutput
from omnievolve.plugins.base import BasePlugin


class GeoPlugin(BasePlugin):
    """地理空间计算领域插件.

    领域提示涵盖：
    - 坐标系转换正确性（WGS84 / GCJ-02 / BD-09）
    - 空间索引（R-tree / GeoHash / H3）
    - 球面距离 vs 投影距离
    - 边界情况（极地、国际日期变更线）
    """

    name = "geo"
    version = "0.1.0"

    DOMAIN_HINTS = [
        "坐标系：中国数据默认 GCJ-02，国际数据 WGS84——混淆会产生系统性误差",
        "球面距离用 Haversine，大圆距离用 Vincenty；避免在小区域用平面投影距离",
        "空间索引：H3 对六边形网格效果最好，GeoHash 在极地有退化",
        "边界情况：跨国际日期变更线、极地区域、凹多边形必须测试",
        "数值精度：高纬度经度收敛，需要处理 wrap-around",
    ]

    def get_domain_hints(self, task_description: str) -> list[str]:
        """返回地理空间优化提示."""
        if any(
            kw in task_description.lower()
            for kw in ("geo", "map", "coordinate", "spatial", "location", "gis")
        ):
            return self.DOMAIN_HINTS
        return []

    def get_rag_corpus(self) -> list[dict] | None:
        return None

    def enrich_evaluation(
        self,
        candidate: CandidateArtifact,
        output: EvalOutput,
    ) -> dict[str, Any]:
        """补充地理空间特定指标."""
        return {}
