"""父代选择策略.

S4-09: 实现最小 ParentSelector（best/tournament/random）
"""

from __future__ import annotations

import random
from typing import Any

from omnievolve.storage.db import Database


class ParentSelector:
    """父代选择器."""

    def __init__(
        self,
        db: Database,
        *,
        strategy: str = "tournament",
        tournament_size: int = 3,
    ) -> None:
        """初始化.

        Args:
            strategy: 选择策略 (best/tournament/random)
            tournament_size: 锦标赛大小
        """
        self._db = db
        self._strategy = strategy
        self._tournament_size = tournament_size

    def select(
        self,
        experiment_id: str,
        evaluator_version_id: str,
        environment_version_id: str,
        count: int = 1,
        exclude_ids: list[str] | None = None,
    ) -> list[str]:
        """选择父代.

        Args:
            experiment_id: 实验 ID
            evaluator_version_id: 评估器版本 ID
            environment_version_id: 环境版本 ID
            count: 选择数量
            exclude_ids: 排除的候选 ID

        Returns:
            父代候选 ID 列表
        """
        # 获取有分数的候选
        candidates = self._get_scored_candidates(
            experiment_id, evaluator_version_id, environment_version_id, exclude_ids
        )

        if not candidates:
            return []

        if self._strategy == "best":
            return self._select_best(candidates, count)
        elif self._strategy == "tournament":
            return self._select_tournament(candidates, count)
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
