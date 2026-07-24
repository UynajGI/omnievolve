"""量化策略领域插件.

提供 A 股量化策略优化场景的领域提示和评估增强。

TODO(延后): 实现完整的 enrich_evaluation（多窗口 IC 稳定性、过拟合检测、
            交易成本建模）和回测数据管道集成。
"""

from __future__ import annotations

from typing import Any

from omnievolve.eval.task_evaluator import CandidateArtifact, EvalOutput
from omnievolve.plugins.base import BasePlugin


class QuantPlugin(BasePlugin):
    """A 股量化策略领域插件.

    领域提示涵盖：
    - 多窗口回测防过拟合
    - 因子组合（非独立假设）
    - 组合构建器与择时模型协同
    - 交易成本与滑点建模
    """

    name = "quant"
    version = "0.1.0"

    DOMAIN_HINTS = [
        "防过拟合：使用多窗口 walk-forward 验证，而非单一训练/测试分割",
        "因子组合 1+1>2：不要独立评估单因子，需要测试组合效应",
        "组合构建器与择时模型协同：择时模型单独差(0.3)可能配合特定组合器达到 0.9",
        "交易成本建模：佣金+印花税+滑点，alpha 必须超过成本才有意义",
        "回测偏差：survivorship bias / look-ahead bias / data snooping 必须显式排除",
        "样本外检验：IC/RankIC 衰减分析，避免 regime 过拟合",
    ]

    RAG_CORPUS = [
        {
            "topic": "MCGS search tree",
            "content": (
                "量化进化搜索是结构化、组合性、约束性的——"
                "不同于通用 ML 进化的平坦均匀代价。所有探索步骤必须是 "
                "MCTS 的树边，不能贪心序列化收敛再切换。"
            ),
        },
        {
            "topic": "overfitting detection",
            "content": (
                "多窗口回测中，过拟合信号：训练 IC > 0.1 但测试 IC < 0.02；"
                "排名相关性低于 0.7 跨窗口。触发记忆有效性消融。"
            ),
        },
    ]

    def get_domain_hints(self, task_description: str) -> list[str]:
        """返回量化策略优化提示."""
        if any(
            kw in task_description.lower()
            for kw in ("quant", "strategy", "factor", "backtest", "alpha")
        ):
            return self.DOMAIN_HINTS
        return []

    def get_rag_corpus(self) -> list[dict] | None:
        """返回量化领域 RAG 语料."""
        return self.RAG_CORPUS

    def enrich_evaluation(
        self,
        candidate: CandidateArtifact,
        output: EvalOutput,
    ) -> dict[str, Any]:
        """补充量化特定评估指标."""
        enriched: dict[str, Any] = {}
        if "ic" in output.metrics:
            enriched["ic_rank_stability"] = output.metrics["ic"] > 0.03
        if "max_drawdown" in output.metrics:
            enriched["drawdown_warning"] = output.metrics["max_drawdown"] < -0.2
        return enriched
