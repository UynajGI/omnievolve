"""系统健康指标 - ROI / 覆盖率 / 记忆有效性 / 污染度.

S8-04: 实现成本归一化 ROI
S8-05: 实现搜索覆盖率指标
S8-06: 实现记忆有效性指标
S8-07: 实现上下文污染指标
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class HealthMetrics:
    """健康指标."""

    # ROI
    roi_score: float = 0.0
    frontier_improvement: float = 0.0
    api_cost_usd: float = 0.0
    compute_cost_sec: float = 0.0
    wall_time_sec: float = 0.0

    # 覆盖率
    coverage_entropy: float = 0.0
    thought_cluster_entropy: float = 0.0
    knn_distance_distribution: float = 0.0
    ast_feature_coverage: float = 0.0
    branch_balance: float = 0.0

    # 记忆有效性
    memory_effectiveness: float = 0.0
    citation_rate: float = 0.0
    adoption_rate: float = 0.0
    duplicate_reduction: float = 0.0

    # 上下文污染度
    pollution_ratio: float = 0.0
    semantic_duplicate_ratio: float = 0.0
    unused_retrieval_ratio: float = 0.0
    stale_memory_ratio: float = 0.0

    # 补充指标
    total_candidates: int = 0
    total_evaluations: int = 0
    success_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "roi_score": self.roi_score,
            "frontier_improvement": self.frontier_improvement,
            "coverage_entropy": self.coverage_entropy,
            "memory_effectiveness": self.memory_effectiveness,
            "pollution_ratio": self.pollution_ratio,
            "total_candidates": self.total_candidates,
            "total_evaluations": self.total_evaluations,
            "success_rate": self.success_rate,
        }


class MetricsCalculator:
    """指标计算器."""

    def compute_roi(
        self,
        frontier_improvement: float,
        api_cost_usd: float,
        compute_cost_sec: float,
        wall_time_sec: float,
        *,
        weights: tuple[float, float, float] = (1.0, 0.1, 0.01),
    ) -> float:
        """计算成本归一化 ROI.

        S8-04:
        ROI = ΔHV / (λ1·C_API + λ2·C_compute + λ3·T_wall)

        Args:
            frontier_improvement: Pareto 前沿提升或 best-score improvement
            api_cost_usd: API 费用
            compute_cost_sec: 计算时间
            wall_time_sec: 墙钟时间
            weights: (λ1, λ2, λ3) 成本权重

        Returns:
            ROI 分数
        """
        lambda1, lambda2, lambda3 = weights
        total_cost = (
            lambda1 * max(api_cost_usd, 0.001)
            + lambda2 * max(compute_cost_sec, 0.001)
            + lambda3 * max(wall_time_sec, 0.001)
        )

        if total_cost <= 0:
            return 0.0

        return frontier_improvement / total_cost

    def compute_pareto_hypervolume(
        self,
        points: list[list[float]],
        reference_point: list[float] | None = None,
    ) -> float:
        """计算 Pareto 前沿 Hypervolume.

        用于多目标任务的 frontier improvement。
        """
        if not points:
            return 0.0

        points_array = np.array(points)
        if reference_point is None:
            reference_point = np.max(points_array, axis=0).tolist()

        # 简化的 hypervolume 计算（2D 精确，高维近似）
        if points_array.shape[1] == 2:
            return self._hypervolume_2d(points_array, np.array(reference_point))
        else:
            # Monte Carlo 近似
            return self._hypervolume_mc(points_array, np.array(reference_point))

    def _hypervolume_2d(self, points: np.ndarray, ref: np.ndarray) -> float:
        """2D Hypervolume 精确计算."""
        # 按 x 排序
        sorted_idx = np.argsort(points[:, 0])
        sorted_points = points[sorted_idx]

        hv = 0.0
        prev_y = ref[1]

        for point in sorted_points:
            if point[0] < ref[0] and point[1] < ref[1]:
                width = ref[0] - point[0]
                height = ref[1] - max(point[1], prev_y) if prev_y > point[1] else ref[1] - point[1]
                hv += width * height
                prev_y = min(prev_y, point[1])

        return max(hv, 0.0)

    def _hypervolume_mc(
        self,
        points: np.ndarray,
        ref: np.ndarray,
        num_samples: int = 10000,
    ) -> float:
        """Monte Carlo Hypervolume 近似."""
        # 简化：使用边界框体积的比率
        dominated = 0
        min_vals = np.min(points, axis=0)
        volume = np.prod(ref - min_vals)

        if volume <= 0:
            return 0.0

        # 随机采样
        samples = np.random.uniform(min_vals, ref, (num_samples, len(ref)))

        for sample in samples:
            if any(np.all(sample >= p) for p in points):
                dominated += 1

        return volume * dominated / num_samples

    def compute_coverage_entropy(
        self,
        thought_clusters: list[int],
        knn_distances: list[float],
        ast_features: list[str],
        branch_sizes: list[int],
        behavior_signatures: list[str] | None = None,
        mechanism_tags: list[str] | None = None,
    ) -> dict[str, float]:
        """计算搜索空间覆盖率.

        设计文档 §5.2.1 要求的 6 种信号:
        - thought_cluster_entropy: 思想簇分布的归一化熵
        - knn_distance_distribution: KNN 距离分布（变异系数）
        - ast_feature_coverage: AST 特征覆盖
        - behavior_signature_entropy: 行为签名多样性
        - mechanism_tag_coverage: 机制标签覆盖率
        - branch_balance: 分支平衡度
        """
        result = {}

        # 1. 思想簇归一化熵
        if thought_clusters:
            result["thought_cluster_entropy"] = self._normalized_entropy(thought_clusters)
        else:
            result["thought_cluster_entropy"] = 0.0

        # 2. KNN 距离分布（变异系数）
        if knn_distances and len(knn_distances) > 1:
            mean_dist = np.mean(knn_distances)
            std_dist = np.std(knn_distances)
            result["knn_distance_distribution"] = std_dist / mean_dist if mean_dist > 0 else 0.0
        else:
            result["knn_distance_distribution"] = 0.0

        # 3. AST 特征覆盖
        if ast_features:
            unique_features = len(set(ast_features))
            total_possible = 100  # 假设的可能特征数
            result["ast_feature_coverage"] = min(unique_features / total_possible, 1.0)
        else:
            result["ast_feature_coverage"] = 0.0

        # 4. 行为签名多样性（归一化熵）
        if behavior_signatures:
            from collections import Counter
            sig_counts = list(Counter(behavior_signatures).values())
            result["behavior_signature_entropy"] = self._normalized_entropy(sig_counts)
        else:
            result["behavior_signature_entropy"] = 0.0

        # 5. 机制标签覆盖率
        if mechanism_tags:
            unique_tags = len(set(mechanism_tags))
            # 归一化: 假设 50 种可能的机制标签
            result["mechanism_tag_coverage"] = min(unique_tags / 50.0, 1.0)
        else:
            result["mechanism_tag_coverage"] = 0.0

        # 6. 分支平衡度（归一化熵）
        if branch_sizes:
            result["branch_balance"] = self._normalized_entropy(branch_sizes)
        else:
            result["branch_balance"] = 0.0

        # 综合覆盖率（6 信号加权）
        result["coverage_entropy"] = (
            0.20 * result["thought_cluster_entropy"]
            + 0.15 * result["knn_distance_distribution"]
            + 0.20 * result["ast_feature_coverage"]
            + 0.15 * result["behavior_signature_entropy"]
            + 0.15 * result["mechanism_tag_coverage"]
            + 0.15 * result["branch_balance"]
        )

        return result

    def compute_memory_effectiveness(
        self,
        total_retrievals: int,
        citations: int,
        adoptions: int,
        duplicate_attempts_before: int,
        duplicate_attempts_after: int,
    ) -> dict[str, float]:
        """计算记忆有效性.

        S8-06:
        - citation_rate: 引用率
        - adoption_rate: 采用率
        - duplicate_reduction: 重复尝试减少率
        """
        result = {}

        result["citation_rate"] = citations / max(total_retrievals, 1)
        result["adoption_rate"] = adoptions / max(total_retrievals, 1)

        if duplicate_attempts_before > 0:
            result["duplicate_reduction"] = (
                duplicate_attempts_before - duplicate_attempts_after
            ) / duplicate_attempts_before
        else:
            result["duplicate_reduction"] = 0.0

        # 综合有效性
        result["memory_effectiveness"] = (
            0.3 * result["citation_rate"]
            + 0.4 * result["adoption_rate"]
            + 0.3 * max(result["duplicate_reduction"], 0)
        )

        return result

    def compute_pollution_ratio(
        self,
        total_context_items: int,
        semantic_duplicates: int,
        unused_retrievals: int,
        stale_memories: int,
    ) -> dict[str, float]:
        """计算上下文污染度.

        S8-07:
        - semantic_duplicate_ratio: 语义重复比例
        - unused_retrieval_ratio: 未使用检索比例
        - stale_memory_ratio: 过时记忆比例
        """
        result = {}

        total = max(total_context_items, 1)
        result["semantic_duplicate_ratio"] = semantic_duplicates / total
        result["unused_retrieval_ratio"] = unused_retrievals / total
        result["stale_memory_ratio"] = stale_memories / total

        # 综合污染度
        result["pollution_ratio"] = (
            0.4 * result["semantic_duplicate_ratio"]
            + 0.35 * result["unused_retrieval_ratio"]
            + 0.25 * result["stale_memory_ratio"]
        )

        return result

    def _normalized_entropy(self, counts: list[int]) -> float:
        """归一化 Shannon 熵."""
        total = sum(counts)
        if total <= 0:
            return 0.0

        probabilities = [c / total for c in counts if c > 0]
        if len(probabilities) <= 1:
            return 0.0

        entropy = -sum(p * math.log2(p) for p in probabilities)
        max_entropy = math.log2(len(probabilities))

        return entropy / max_entropy if max_entropy > 0 else 0.0
