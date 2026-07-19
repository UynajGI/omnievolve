"""搜索参数调优器.

S9: 首版可用规则/Bandit
"""

from __future__ import annotations

import logging
import random
from typing import Any

logger = logging.getLogger(__name__)


class HyperparamTuner:
    """超参数调优器."""

    def __init__(
        self,
        *,
        method: str = "rule_based",  # rule_based / bandit / bayesian
        exploration: float = 0.1,
    ) -> None:
        self._method = method
        self._exploration = exploration

    def tune(
        self,
        current_params: dict[str, Any],
        performance_history: list[dict[str, float]],
    ) -> dict[str, Any]:
        """调优超参数.

        Args:
            current_params: 当前参数
            performance_history: 性能历史

        Returns:
            调整后的参数
        """
        if self._method == "rule_based":
            return self._rule_based_tune(current_params, performance_history)
        else:
            return self._random_tune(current_params)

    def _rule_based_tune(
        self,
        params: dict[str, Any],
        history: list[dict[str, float]],
    ) -> dict[str, Any]:
        """规则调优."""
        tuned = params.copy()

        if len(history) < 3:
            return tuned

        recent = history[-3:]
        avg_score = sum(h.get("score", 0) for h in recent) / len(recent)
        trend = recent[-1].get("score", 0) - recent[0].get("score", 0)

        # 如果趋势下降，增加探索
        if trend < 0:
            tuned["temperature"] = min(params.get("temperature", 0.7) + 0.1, 1.5)
            tuned["mutation_rate"] = min(params.get("mutation_rate", 0.3) + 0.05, 0.8)

        # 如果分数很高，减少探索（利用）
        elif avg_score > 0.8:
            tuned["temperature"] = max(params.get("temperature", 0.7) - 0.05, 0.1)

        return tuned

    def _random_tune(self, params: dict[str, Any]) -> dict[str, Any]:
        """随机调优."""
        tuned = params.copy()

        tunable = ["temperature", "mutation_rate", "crossover_rate", "novelty_threshold"]
        for param in tunable:
            if param in tuned and random.random() < self._exploration:
                if isinstance(tuned[param], float):
                    delta = random.uniform(-0.1, 0.1)
                    tuned[param] = max(0.0, min(1.0, tuned[param] + delta))

        return tuned
