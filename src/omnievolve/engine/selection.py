"""父代选择策略.

S4-09: 实现最小 ParentSelector（best/tournament/random）
SA-01: ShinkaEvolve power law + weighted 采样
P1-2: 探索-利用软切换 (MLEvolve select_with_soft_switch)
"""

from __future__ import annotations

import math
import random
from typing import Any

from omnievolve.storage.db import Database


class ParentSelector:
    """父代选择器.

    支持策略: best, tournament, random, power_law, weighted
    """

    def __init__(
        self,
        db: Database,
        *,
        strategy: str = "tournament",
        tournament_size: int = 3,
        power_law_alpha: float = 1.0,
        weighted_lambda: float = 10.0,
    ) -> None:
        """初始化.

        Args:
            strategy: 选择策略 (best/tournament/random/power_law/weighted)
            tournament_size: 锦标赛大小
            power_law_alpha: power law 强度（0=uniform, ∞=hill-climb）
            weighted_lambda: weighted 选择压力
        """
        self._db = db
        self._strategy = strategy
        self._tournament_size = tournament_size
        self._power_law_alpha = power_law_alpha
        self._weighted_lambda = weighted_lambda

    def __repr__(self) -> str:
        return (
            f"ParentSelector(strategy={self._strategy!r}, "
            f"tourn_size={self._tournament_size}, "
            f"pow_law_a={self._power_law_alpha:.1f})"
        )

    def select(
        self,
        experiment_id: str,
        evaluator_version_id: str,
        environment_version_id: str,
        count: int = 1,
        exclude_ids: list[str] | None = None,
    ) -> list[str]:
        """选择父代."""
        candidates = self._get_scored_candidates(
            experiment_id, evaluator_version_id, environment_version_id, exclude_ids
        )

        if not candidates:
            return []

        if self._strategy == "best":
            return self._select_best(candidates, count)
        elif self._strategy == "tournament":
            return self._select_tournament(candidates, count)
        elif self._strategy == "power_law":
            return self._select_power_law(candidates, count)
        elif self._strategy == "weighted":
            return self._select_weighted(candidates, count)
        else:  # random
            return self._select_random(candidates, count)

    def _get_scored_candidates(
        self,
        experiment_id: str,
        evaluator_version_id: str,
        environment_version_id: str,
        exclude_ids: list[str] | None,
    ) -> list[tuple[str, float]]:
        """获取有分数的候选."""
        sql = """
            SELECT c.id, MAX(er.primary_score) as score
            FROM candidate c
            JOIN evaluation_run er ON c.id = er.candidate_id
            WHERE c.experiment_id = ?
              AND er.evaluator_version_id = ?
              AND er.environment_version_id = ?
              AND er.status = 'completed'
              AND er.passed = 1
        """
        params: list[Any] = [experiment_id, evaluator_version_id, environment_version_id]

        if exclude_ids:
            placeholders = ",".join(["?"] * len(exclude_ids))
            sql += f" AND c.id NOT IN ({placeholders})"
            params.extend(exclude_ids)

        sql += " GROUP BY c.id"

        rows = self._db.fetchall(sql, tuple(params))
        return [(row["id"], row["score"]) for row in rows if row["score"] is not None]

    def _select_best(self, candidates: list[tuple[str, float]], count: int) -> list[str]:
        """选择最佳."""
        sorted_candidates = sorted(candidates, key=lambda x: x[1], reverse=True)
        return [c[0] for c in sorted_candidates[:count]]

    def _select_tournament(self, candidates: list[tuple[str, float]], count: int) -> list[str]:
        """锦标赛选择."""
        selected = []
        for _ in range(count):
            # 随机选择 tournament_size 个候选
            tournament = random.sample(candidates, min(self._tournament_size, len(candidates)))
            # 选择其中最好的
            winner = max(tournament, key=lambda x: x[1])
            selected.append(winner[0])
        return selected

    def _select_random(self, candidates: list[tuple[str, float]], count: int) -> list[str]:
        """随机选择."""
        selected = random.sample(candidates, min(count, len(candidates)))
        return [c[0] for c in selected]

    def _select_power_law(self, candidates: list[tuple[str, float]], count: int) -> list[str]:
        """Power law 采样.

        ShinkaEvolve: P(i) = rank_i^(-α) / Σ rank_j^(-α)
        α=0 → uniform, α→∞ → hill-climbing
        """
        # 按分数降序排列（rank 1 = 最高分）
        sorted_cands = sorted(candidates, key=lambda x: x[1], reverse=True)
        n = len(sorted_cands)
        ranks = list(range(1, n + 1))
        weights = [r ** (-self._power_law_alpha) for r in ranks]
        total = sum(weights)
        probs = [w / total for w in weights]

        selected: list[int] = []
        # 不放回采样
        available = list(range(n))
        for _ in range(min(count, n)):
            cum = 0.0
            r = random.random()
            for idx in available:
                cum += probs[idx]
                if r <= cum:
                    selected.append(idx)
                    available.remove(idx)
                    # 重新归一化
                    remaining_probs = [probs[i] for i in available]
                    rsum = sum(remaining_probs)
                    probs = [p / rsum if i in available else 0.0 for i, p in enumerate(probs)]
                    break

        return [sorted_cands[i][0] for i in selected]

    def _select_weighted(self, candidates: list[tuple[str, float]], count: int) -> list[str]:
        """Weighted 采样 — 平衡性能与新颖性.

        ShinkaEvolve:
          s_i = sigmoid(λ·(F(P_i) - median))
          h_i = 1 / (1 + offspring_count_i)
          P(i) ∝ s_i · h_i
        """
        sorted_cands = sorted(candidates, key=lambda x: x[1])
        scores = [c[1] for c in sorted_cands]
        n = len(scores)
        median = scores[n // 2] if n % 2 else (scores[n // 2 - 1] + scores[n // 2]) / 2

        # 获取 offspring count
        ids = [c[0] for c in sorted_cands]
        offspring: dict[str, int] = {}
        if ids:
            placeholders = ",".join(["?"] * len(ids))
            rows = self._db.fetchall(
                f"""
                SELECT candidate_id, offspring_count
                FROM candidate_search_state
                WHERE candidate_id IN ({placeholders})
                """,
                tuple(ids),
            )
            offspring = {r["candidate_id"]: (r["offspring_count"] or 0) for r in rows}

        def sigmoid(x: float) -> float:
            return 1.0 / (1.0 + math.exp(-x))

        weights = []
        for cid, score in sorted_cands:
            s_i = sigmoid(self._weighted_lambda * (score - median))
            h_i = 1.0 / (1.0 + offspring.get(cid, 0))
            weights.append(s_i * h_i)

        total = sum(weights)
        probs = [w / total for w in weights] if total > 0 else [1.0 / n] * n

        # 不放回采样
        selected: list[int] = []
        available = list(range(n))
        for _ in range(min(count, n)):
            cum = 0.0
            r = random.random()
            for idx in available:
                cum += probs[idx]
                if r <= cum:
                    selected.append(idx)
                    available.remove(idx)
                    # 重新归一化
                    remaining = [probs[i] for i in available]
                    rsum = sum(remaining)
                    probs = [p / rsum if i in available else 0.0 for i, p in enumerate(probs)]
                    break

        return [sorted_cands[i][0] for i in selected]


class ExplorationSelector(ParentSelector):
    """探索性选择器.

    优先选择低访问次数但有潜力的节点。
    """

    def select(
        self,
        experiment_id: str,
        evaluator_version_id: str,
        environment_version_id: str,
        count: int = 1,
        exclude_ids: list[str] | None = None,
    ) -> list[str]:
        """选择低访问次数的候选."""
        candidates = self._get_scored_candidates(
            experiment_id, evaluator_version_id, environment_version_id, exclude_ids
        )

        if not candidates:
            return []

        # 获取访问次数
        candidate_ids = [c[0] for c in candidates]
        placeholders = ",".join(["?"] * len(candidate_ids))
        rows = self._db.fetchall(
            f"""
            SELECT candidate_id, visit_count
            FROM candidate_search_state
            WHERE candidate_id IN ({placeholders})
            """,
            tuple(candidate_ids),
        )
        visit_counts = {row["candidate_id"]: row["visit_count"] for row in rows}

        # 按访问次数升序排序
        sorted_candidates = sorted(
            candidates,
            key=lambda x: visit_counts.get(x[0], 0),
        )

        return [c[0] for c in sorted_candidates[:count]]


def compute_exploration_weight(
    progress_ratio: float,
    *,
    w_start: float = 1.0,
    w_end: float = 0.2,
    switch_start: float = 0.5,
    switch_end: float = 0.7,
) -> float:
    """P1-2: 计算探索权重 w(t).

    在 [switch_start, switch_end] 区间内从 w_start 线性衰减到 w_end。
    - progress < switch_start: w = w_start（全探索）
    - progress > switch_end: w = w_end（偏利用）

    Args:
        progress_ratio: 当前进度 0.0~1.0
        w_start: 初始探索权重
        w_end: 最终探索权重
        switch_start: 衰减起始点
        switch_end: 衰减结束点

    Returns:
        探索概率 w(t) ∈ [w_end, w_start]
    """
    if progress_ratio <= switch_start:
        return w_start
    if progress_ratio >= switch_end:
        return w_end
    # 线性插值
    t = (progress_ratio - switch_start) / (switch_end - switch_start)
    return w_start - (w_start - w_end) * t


def select_top_k_exploitation(
    candidates: list[tuple[str, float]],
    *,
    k: int = 5,
) -> str:
    """P1-2: Top-K 加权随机利用.

    从全局最高分 top-K 中，按 1/rank 加权随机选择一个。

    Args:
        candidates: [(candidate_id, score), ...]
        k: Top-K 窗口大小

    Returns:
        选中的 candidate_id
    """
    if not candidates:
        return ""

    # 取 top-K
    sorted_cands = sorted(candidates, key=lambda x: x[1], reverse=True)
    top_k = sorted_cands[:k]

    # 1/rank 加权
    weights = [1.0 / (i + 1) for i in range(len(top_k))]
    total = sum(weights)
    probs = [w / total for w in weights]

    # 加权随机选择
    r = random.random()
    cum = 0.0
    for i, prob in enumerate(probs):
        cum += prob
        if r <= cum:
            return top_k[i][0]
    return top_k[-1][0]  # fallback
