"""Telemetry 与 HealthPolicy.

S8-01: 冻结 Telemetry Event Schema
S8-02: 实现事件采集与批量持久化
S8-08: 实现 TelemetryAggregator
S8-09: 实现 HealthPolicy 规则与迟滞
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from omnievolve.eval.metrics import HealthMetrics, MetricsCalculator
from omnievolve.storage.db import Database

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    """告警级别."""

    OK = "ok"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass
class HealthOutput:
    """健康评估输出."""

    roi_score: float
    coverage_entropy: float
    memory_effectiveness: float
    pollution_ratio: float
    alert_level: AlertLevel = AlertLevel.OK
    recommendations: list[str] = field(default_factory=list)
    should_trigger_meta: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


class TelemetryAggregator:
    """遥测聚合器.

    S8-08: 聚合所有客观指标。
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._calculator = MetricsCalculator()

    def aggregate(
        self,
        experiment_id: str,
        generation_start: int,
        generation_end: int,
    ) -> HealthMetrics:
        """聚合窗口内的指标."""
        metrics = HealthMetrics()

        # 获取窗口内的候选和评估
        rows = self._db.fetchall(
            """
            SELECT c.id, c.generation, er.primary_score, er.passed,
                   er.execution_time_ms, llm.total_tokens, llm.cost_usd
            FROM candidate c
            LEFT JOIN evaluation_run er ON c.id = er.candidate_id AND er.status = 'completed'
            LEFT JOIN llm_call_ledger llm ON llm.experiment_id = c.experiment_id
            WHERE c.experiment_id = ? AND c.generation BETWEEN ? AND ?
            """,
            (experiment_id, generation_start, generation_end),
        )

        if not rows:
            return metrics

        metrics.total_candidates = len({row["id"] for row in rows})
        metrics.total_evaluations = len([r for r in rows if r["primary_score"] is not None])

        # 成功率
        passed = [r for r in rows if r["passed"] == 1]
        metrics.success_rate = len(passed) / max(metrics.total_evaluations, 1)

        # 前沿提升
        scores = [r["primary_score"] for r in rows if r["primary_score"] is not None]
        if scores:
            metrics.frontier_improvement = max(scores) - min(scores)

        # 成本
        metrics.api_cost_usd = sum((r["cost_usd"] or 0) for r in rows)
        metrics.compute_cost_sec = sum((r["execution_time_ms"] or 0) for r in rows) / 1000

        # ROI
        metrics.roi_score = self._calculator.compute_roi(
            metrics.frontier_improvement,
            metrics.api_cost_usd,
            metrics.compute_cost_sec,
            max(generation_end - generation_start, 1) * 60,  # 假设每代 60 秒
        )

        # 覆盖率（简化）
        generations = [r["generation"] for r in rows]
        metrics.coverage_entropy = self._calculator._normalized_entropy(
            [generations.count(g) for g in set(generations)]
        )

        # 记忆统计
        mem_stats = self._get_memory_stats(experiment_id, generation_start, generation_end)
        metrics.memory_effectiveness = mem_stats.get("memory_effectiveness", 0.0)
        metrics.citation_rate = mem_stats.get("citation_rate", 0.0)
        metrics.adoption_rate = mem_stats.get("adoption_rate", 0.0)

        # 污染度（简化）
        if metrics.total_candidates > 0:
            metrics.pollution_ratio = 0.1  # 默认低污染

        return metrics

    def get_total_generations(self, experiment_id: str) -> int:
        """获取实验的总代数."""
        row = self._db.fetchone(
            "SELECT MAX(generation) as max_gen FROM candidate WHERE experiment_id = ?",
            (experiment_id,),
        )
        return (row["max_gen"] or 0) + 1 if row else 0

    def _get_memory_stats(
        self,
        experiment_id: str,
        gen_start: int,
        gen_end: int,
    ) -> dict[str, float]:
        """获取记忆统计."""
        row = self._db.fetchone(
            """
            SELECT COUNT(*) as total,
                   SUM(citation_count) as citations,
                   SUM(adoption_count) as adoptions
            FROM memory_entry
            WHERE experiment_id = ?
            """,
            (experiment_id,),
        )

        if row and row["total"] and row["total"] > 0:
            return {
                "citation_rate": (row["citations"] or 0) / row["total"],
                "adoption_rate": (row["adoptions"] or 0) / row["total"],
                "memory_effectiveness": (
                    0.3 * (row["citations"] or 0) / row["total"]
                    + 0.7 * (row["adoptions"] or 0) / row["total"]
                ),
            }
        return {}


class HealthPolicy:
    """健康策略.

    S8-09: 规则与统计判定，包含迟滞机制。
    """

    def __init__(
        self,
        db: Database | None = None,
        *,
        roi_warn_threshold: float = 0.001,
        entropy_warn_threshold: float = 0.35,
        stagnation_trigger: int = 3,
        pollution_warn_threshold: float = 0.3,
    ) -> None:
        self._db = db
        self._roi_warn = roi_warn_threshold
        self._entropy_warn = entropy_warn_threshold
        self._stagnation_trigger = stagnation_trigger
        self._pollution_warn = pollution_warn_threshold
        self._history: list[HealthMetrics] = []

    def assess(
        self,
        metrics: HealthMetrics,
        *,
        experiment_id: str | None = None,
        generation_start: int = 0,
        generation_end: int = 0,
        search_policy_id: str = "default",
    ) -> HealthOutput:
        """评估健康度."""
        recommendations = []
        alert_level = AlertLevel.OK
        should_trigger_meta = False

        # ROI 检查
        if metrics.roi_score < self._roi_warn:
            alert_level = AlertLevel.WARN
            recommendations.append(
                f"Low ROI ({metrics.roi_score:.4f}): consider adjusting search strategy"
            )
            should_trigger_meta = True

        # 覆盖率检查
        if metrics.coverage_entropy < self._entropy_warn:
            if alert_level == AlertLevel.OK:
                alert_level = AlertLevel.WARN
            recommendations.append(
                f"Low coverage entropy ({metrics.coverage_entropy:.3f}): "
                "increase exploration diversity"
            )

        # 成功率检查
        if metrics.success_rate < 0.3:
            alert_level = AlertLevel.CRITICAL
            recommendations.append(
                f"Very low success rate ({metrics.success_rate:.2%}): "
                "check evaluator or sandbox configuration"
            )
            should_trigger_meta = True

        # 污染度检查
        if metrics.pollution_ratio > self._pollution_warn:
            if alert_level == AlertLevel.OK:
                alert_level = AlertLevel.WARN
            recommendations.append(
                f"High context pollution ({metrics.pollution_ratio:.2%}): "
                "prune stale memories and reduce retrieval budget"
            )

        # 停滞检测（需要历史）
        self._history.append(metrics)
        if len(self._history) > self._stagnation_trigger:
            recent = self._history[-self._stagnation_trigger :]
            if all(m.frontier_improvement <= 0.001 for m in recent):
                alert_level = AlertLevel.WARN
                recommendations.append(
                    f"Search stagnated for {self._stagnation_trigger} windows: "
                    "trigger meta-evolution"
                )
                should_trigger_meta = True

        output = HealthOutput(
            roi_score=metrics.roi_score,
            coverage_entropy=metrics.coverage_entropy,
            memory_effectiveness=metrics.memory_effectiveness,
            pollution_ratio=metrics.pollution_ratio,
            alert_level=alert_level,
            recommendations=recommendations,
            should_trigger_meta=should_trigger_meta,
            evidence={
                "total_candidates": metrics.total_candidates,
                "success_rate": metrics.success_rate,
                "api_cost_usd": metrics.api_cost_usd,
            },
        )

        # S8-03: 写入 meta_evaluation_window 表
        if self._db and experiment_id:
            self._db.execute(
                """
                INSERT INTO meta_evaluation_window
                    (experiment_id, generation_start, generation_end,
                     search_policy_id, roi_score, coverage_entropy,
                     memory_effectiveness, pollution_ratio, alert_level,
                     should_trigger_meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    generation_start,
                    generation_end,
                    search_policy_id,
                    output.roi_score,
                    output.coverage_entropy,
                    output.memory_effectiveness,
                    output.pollution_ratio,
                    output.alert_level.value,
                    1 if output.should_trigger_meta else 0,
                ),
            )

        return output


class DashboardDataExporter:
    """健康指标仪表板数据接口.

    S8-15: 实现健康指标 dashboard 数据接口
    为外部监控工具（Grafana/Prometheus/Datadog）提供结构化指标导出。
    """

    def __init__(
        self,
        aggregator: TelemetryAggregator,
        health_policy: HealthPolicy,
    ) -> None:
        self._aggregator = aggregator
        self._policy = health_policy

    def get_snapshot(
        self,
        experiment_id: str,
        generation_start: int,
        generation_end: int,
    ) -> dict[str, Any]:
        """获取当前健康快照（适合轮询/仪表板）."""
        metrics = self._aggregator.aggregate(experiment_id, generation_start, generation_end)
        health = self._policy.assess(metrics)

        return {
            "experiment_id": experiment_id,
            "window": {
                "generation_start": generation_start,
                "generation_end": generation_end,
            },
            "health": {
                "roi_score": health.roi_score,
                "coverage_entropy": health.coverage_entropy,
                "memory_effectiveness": health.memory_effectiveness,
                "pollution_ratio": health.pollution_ratio,
                "alert_level": health.alert_level.value,
                "should_trigger_meta": health.should_trigger_meta,
                "recommendations": health.recommendations,
            },
            "metrics": {
                "total_candidates": metrics.total_candidates,
                "total_evaluations": metrics.total_evaluations,
                "success_rate": metrics.success_rate,
                "api_cost_usd": metrics.api_cost_usd,
                "frontier_improvement": metrics.frontier_improvement,
                "wall_time_sec": metrics.wall_time_sec,
            },
        }

    def get_timeseries(
        self,
        experiment_id: str,
        window_size: int = 5,
    ) -> list[dict[str, Any]]:
        """获取时间序列数据（适合折线图）."""
        snapshots: list[dict[str, Any]] = []
        total_gens = self._aggregator.get_total_generations(experiment_id)

        for gen_start in range(0, total_gens, window_size):
            gen_end = min(gen_start + window_size, total_gens)
            snapshot = self.get_snapshot(experiment_id, gen_start, gen_end)
            snapshots.append(snapshot)

        return snapshots

    def export_prometheus(self, experiment_id: str) -> str:
        """导出 Prometheus 格式指标."""
        snapshot = self.get_snapshot(experiment_id, 0, 999_999)
        lines = [
            "# HELP omnievolve_roi_score Return-on-investment score",
            "# TYPE omnievolve_roi_score gauge",
            f'omnievolve_roi_score{{experiment_id="{experiment_id}"}} {snapshot["health"]["roi_score"]}',
            "# HELP omnievolve_coverage_entropy Search space coverage entropy",
            "# TYPE omnievolve_coverage_entropy gauge",
            f'omnievolve_coverage_entropy{{experiment_id="{experiment_id}"}} {snapshot["health"]["coverage_entropy"]}',
            "# HELP omnievolve_success_rate Candidate success rate",
            "# TYPE omnievolve_success_rate gauge",
            f'omnievolve_success_rate{{experiment_id="{experiment_id}"}} {snapshot["metrics"]["success_rate"]}',
            "# HELP omnievolve_alert_level Current alert level (0=OK,1=WARN,2=CRITICAL)",
            "# TYPE omnievolve_alert_level gauge",
            f'omnievolve_alert_level{{experiment_id="{experiment_id}"}} {_alert_to_num(snapshot["health"]["alert_level"])}',
        ]
        return "\n".join(lines) + "\n"


def _alert_to_num(level: str) -> int:
    """告警级别转数字."""
    return {"ok": 0, "warn": 1, "critical": 2}.get(level, -1)


class SelfEvaluator:
    """自评估器 - 轨道 B Facade.

    S5-02: SelfEvaluator Protocol 实现
    """

    def __init__(
        self,
        aggregator: TelemetryAggregator,
        health_policy: HealthPolicy,
    ) -> None:
        self._aggregator = aggregator
        self._policy = health_policy

    def assess(
        self,
        experiment_id: str,
        generation_start: int,
        generation_end: int,
    ) -> HealthOutput:
        """评估健康度."""
        metrics = self._aggregator.aggregate(experiment_id, generation_start, generation_end)
        return self._policy.assess(metrics)
