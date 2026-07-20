"""metrics.py 单元测试 — HealthMetrics + MetricsCalculator."""

from __future__ import annotations

import pytest

from omnievolve.eval.metrics import HealthMetrics, MetricsCalculator

pytestmark = pytest.mark.unit


class TestHealthMetrics:
    def test_defaults_are_zero(self):
        m = HealthMetrics()
        assert m.roi_score == 0.0
        assert m.total_candidates == 0

    def test_to_dict_contains_key_fields(self):
        m = HealthMetrics(roi_score=0.8, total_candidates=10)
        d = m.to_dict()
        assert d["roi_score"] == 0.8
        assert d["total_candidates"] == 10

    def test_to_dict_excludes_raw_costs(self):
        m = HealthMetrics(api_cost_usd=5.0)
        d = m.to_dict()
        assert "api_cost_usd" not in d  # 只导出汇总指标


class TestMetricsCalculatorROI:
    def test_roi_positive_improvement(self):
        calc = MetricsCalculator()
        roi = calc.compute_roi(
            frontier_improvement=10.0,
            api_cost_usd=1.0,
            compute_cost_sec=100.0,
            wall_time_sec=100.0,
        )
        assert roi > 0

    def test_roi_zero_improvement(self):
        calc = MetricsCalculator()
        roi = calc.compute_roi(
            frontier_improvement=0.0,
            api_cost_usd=1.0,
            compute_cost_sec=1.0,
            wall_time_sec=1.0,
        )
        assert roi == 0.0

    def test_roi_costs_avoid_division_by_zero(self):
        calc = MetricsCalculator()
        roi = calc.compute_roi(
            frontier_improvement=5.0,
            api_cost_usd=0.0,
            compute_cost_sec=0.0,
            wall_time_sec=0.0,
        )
        # 成本被 clamp 到 0.001，不应除零
        assert roi >= 0

    def test_roi_custom_weights(self):
        calc = MetricsCalculator()
        roi = calc.compute_roi(
            frontier_improvement=1.0,
            api_cost_usd=100.0,
            compute_cost_sec=1.0,
            wall_time_sec=1.0,
            weights=(0.0, 1.0, 0.0),
        )
        # 只有 compute 成本
        assert roi > 0


class TestMetricsCalculatorHypervolume:
    def test_hypervolume_empty(self):
        calc = MetricsCalculator()
        hv = calc.compute_pareto_hypervolume([])
        assert hv == 0.0

    def test_hypervolume_2d_two_points(self):
        calc = MetricsCalculator()
        hv = calc.compute_pareto_hypervolume(
            [[0.5, 1.5], [1.5, 0.5]],
            reference_point=[2.0, 2.0],
        )
        assert hv > 0

    def test_hypervolume_mc_approximation(self):
        calc = MetricsCalculator()
        hv = calc.compute_pareto_hypervolume(
            [[0.5, 1.0, 0.3], [0.8, 0.6, 0.9]],
            reference_point=[1.0, 1.0, 1.0],
        )
        assert hv >= 0


class TestMetricsCalculatorCoverage:
    def test_coverage_entropy_all_empty(self):
        calc = MetricsCalculator()
        result = calc.compute_coverage_entropy([], [], [], [])
        assert result["coverage_entropy"] == 0.0
        assert result["thought_cluster_entropy"] == 0.0

    def test_coverage_entropy_with_data(self):
        calc = MetricsCalculator()
        result = calc.compute_coverage_entropy(
            thought_clusters=[5, 3, 2],
            knn_distances=[1.0, 2.0, 3.0, 4.0],
            ast_features=["f1", "f2", "f3", "f4", "f1"],
            branch_sizes=[10, 10, 10],
        )
        assert result["coverage_entropy"] > 0
        assert result["thought_cluster_entropy"] > 0
        assert result["knn_distance_distribution"] > 0
        assert result["ast_feature_coverage"] > 0
        assert result["branch_balance"] >= 0

    def test_coverage_single_cluster(self):
        calc = MetricsCalculator()
        result = calc.compute_coverage_entropy(
            thought_clusters=[10],
            knn_distances=[1.0],
            ast_features=[],
            branch_sizes=[10],
        )
        # 单一聚类 → 归一化熵 = 0
        assert result["thought_cluster_entropy"] == 0.0

    def test_coverage_uniform_distribution(self):
        calc = MetricsCalculator()
        result = calc.compute_coverage_entropy(
            thought_clusters=[1, 1, 1, 1],
            knn_distances=[],
            ast_features=[],
            branch_sizes=[1, 1, 1, 1],
        )
        # 均匀分布 → 最大熵 → 归一化 = 1.0
        assert result["thought_cluster_entropy"] == pytest.approx(1.0)
        assert result["branch_balance"] == pytest.approx(1.0)

    def test_knn_single_distance(self):
        calc = MetricsCalculator()
        result = calc.compute_coverage_entropy(
            thought_clusters=[],
            knn_distances=[5.0],
            ast_features=[],
            branch_sizes=[],
        )
        assert result["knn_distance_distribution"] == 0.0


class TestMetricsCalculatorMemory:
    def test_memory_effectiveness_full(self):
        calc = MetricsCalculator()
        result = calc.compute_memory_effectiveness(
            total_retrievals=100,
            citations=80,
            adoptions=50,
            duplicate_attempts_before=20,
            duplicate_attempts_after=5,
        )
        assert result["citation_rate"] == 0.8
        assert result["adoption_rate"] == 0.5
        assert result["duplicate_reduction"] == 0.75
        assert result["memory_effectiveness"] > 0

    def test_memory_effectiveness_empty(self):
        calc = MetricsCalculator()
        result = calc.compute_memory_effectiveness(
            total_retrievals=0,
            citations=0,
            adoptions=0,
            duplicate_attempts_before=0,
            duplicate_attempts_after=0,
        )
        assert result["citation_rate"] == 0.0

    def test_memory_effectiveness_zero_duplicate_before(self):
        calc = MetricsCalculator()
        result = calc.compute_memory_effectiveness(
            total_retrievals=10,
            citations=5,
            adoptions=3,
            duplicate_attempts_before=0,
            duplicate_attempts_after=5,
        )
        assert result["duplicate_reduction"] == 0.0


class TestMetricsCalculatorPollution:
    def test_pollution_ratio_mixed(self):
        calc = MetricsCalculator()
        result = calc.compute_pollution_ratio(
            total_context_items=100,
            semantic_duplicates=20,
            unused_retrievals=30,
            stale_memories=10,
        )
        assert result["semantic_duplicate_ratio"] == 0.2
        assert result["unused_retrieval_ratio"] == 0.3
        assert result["stale_memory_ratio"] == 0.1
        assert 0 < result["pollution_ratio"] < 1

    def test_pollution_ratio_clean(self):
        calc = MetricsCalculator()
        result = calc.compute_pollution_ratio(
            total_context_items=100,
            semantic_duplicates=0,
            unused_retrievals=0,
            stale_memories=0,
        )
        assert result["pollution_ratio"] == 0.0

    def test_pollution_ratio_empty(self):
        calc = MetricsCalculator()
        result = calc.compute_pollution_ratio(
            total_context_items=0,
            semantic_duplicates=0,
            unused_retrievals=0,
            stale_memories=0,
        )
        assert result["pollution_ratio"] == 0.0
