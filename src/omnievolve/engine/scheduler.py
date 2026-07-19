"""进化调度器.

S4-07: 实现基础 Scheduler 队列
S4-11: 串联 Sandbox 与 TaskEvaluator
S4-12: 实现 best/elite archive 最小逻辑
S4-13: 实现 resume 与 orphan job recovery
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from omnievolve.eval.evaluation_run import EvaluationRunRepository
from omnievolve.storage.db import Database
from omnievolve.storage.job_store import JobStore
from omnievolve.storage.repositories.candidate_repo import CandidateRepository

logger = logging.getLogger(__name__)


@dataclass
class GenerationResult:
    """单代结果."""

    generation: int
    candidates_created: int
    candidates_evaluated: int
    best_score: float | None
    best_candidate_id: str | None
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvolutionResult:
    """进化结果."""

    best_candidate_id: str | None
    best_artifact_hash: str | None
    best_score: float | None
    total_generations: int
    total_candidates: int
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_compute_sec: float = 0.0


class Scheduler:
    """进化调度器.

    管理候选进化生命周期：
    - 任务分发与状态追踪
    - 评估串联
    - 断点恢复
    """

    def __init__(
        self,
        db: Database,
        *,
        experiment_id: str,
        evaluator_version_id: str,
        environment_version_id: str,
        search_policy_id: str = "default",
    ) -> None:
        self._db = db
        self._experiment_id = experiment_id
        self._evaluator_version_id = evaluator_version_id
        self._environment_version_id = environment_version_id
        self._search_policy_id = search_policy_id

        self._candidate_repo = CandidateRepository(db)
        self._job_store = JobStore(db)
        self._eval_repo = EvaluationRunRepository(db)

        self._current_generation = 0
        self._elite_archive: list[tuple[str, float]] = []

    @property
    def experiment_id(self) -> str:
        return self._experiment_id

    @property
    def current_generation(self) -> int:
        return self._current_generation

    def create_experiment(
        self,
        task_id: str,
        task_name: str,
        config_snapshot: dict[str, Any],
    ) -> str:
        """创建实验."""
        from omnievolve.storage.repositories.base import generate_id

        exp_id = generate_id()
        self._db.execute(
            """
            INSERT INTO experiment (id, task_id, task_name, status, config_snapshot)
            VALUES (?, ?, ?, ?, ?)
            """,
            (exp_id, task_id, task_name, "running", json.dumps(config_snapshot)),
        )
        self._experiment_id = exp_id
        return exp_id

    def submit_candidate(
        self,
        task_id: str,
        artifact_hash: str,
        *,
        generation: int | None = None,
        island_id: str | None = None,
        thought_id: str | None = None,
        parents: list[tuple[str, str]] | None = None,
    ) -> str:
        """提交候选.

        Args:
            task_id: 任务 ID
            artifact_hash: 代码 artifact 哈希
            generation: 代数（默认当前代）
            island_id: 岛屿 ID
            thought_id: 思想记录 ID
            parents: 父代列表 [(parent_id, relation_type), ...]

        Returns:
            候选 ID
        """
        if generation is None:
            generation = self._current_generation

        candidate = self._candidate_repo.create_candidate(
            experiment_id=self._experiment_id,
            task_id=task_id,
            generation=generation,
            artifact_hash=artifact_hash,
            search_policy_id=self._search_policy_id,
            island_id=island_id,
            thought_id=thought_id,
            parents=parents,
        )

        # 创建评估任务
        self._job_store.create_job(
            experiment_id=self._experiment_id,
            job_type="evaluate",
            payload={
                "candidate_id": candidate.id,
                "artifact_hash": artifact_hash,
            },
        )

        return candidate.id

    def create_evaluation_run(self, candidate_id: str, seed: int | None = None) -> str:
        """创建评估运行."""
        run = self._eval_repo.create(
            experiment_id=self._experiment_id,
            candidate_id=candidate_id,
            evaluator_version_id=self._evaluator_version_id,
            environment_version_id=self._environment_version_id,
            seed=seed,
        )
        return run.id

    def complete_evaluation(
        self,
        run_id: str,
        *,
        passed: bool,
        primary_score: float,
        metrics: dict[str, float] | None = None,
        execution_time_ms: float | None = None,
    ) -> None:
        """完成评估."""
        self._eval_repo.complete(
            run_id,
            passed=passed,
            primary_score=primary_score,
            metrics=metrics,
            execution_time_ms=execution_time_ms,
        )

        # 更新精英档案
        if passed:
            run = self._eval_repo.get(run_id)
            if run:
                self._update_elite_archive(run.candidate_id, primary_score)

    def advance_generation(self) -> int:
        """推进到下一代."""
        self._current_generation += 1
        return self._current_generation

    def get_best_candidate(self) -> tuple[str | None, float | None]:
        """获取最佳候选."""
        if self._elite_archive:
            best = max(self._elite_archive, key=lambda x: x[1])
            return best
        return None, None

    def get_elite_archive(self, top_k: int = 10) -> list[tuple[str, float]]:
        """获取精英档案."""
        sorted_archive = sorted(self._elite_archive, key=lambda x: x[1], reverse=True)
        return sorted_archive[:top_k]

    def recover(self) -> int:
        """恢复孤儿任务.

        S4-13: 实现 resume 与 orphan job recovery
        """
        return self._job_store.recover_orphan_jobs()

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息."""
        job_stats = self._job_store.get_stats(self._experiment_id)

        candidate_count = self._db.fetchone(
            "SELECT COUNT(*) as cnt FROM candidate WHERE experiment_id = ?",
            (self._experiment_id,),
        )

        eval_count = self._db.fetchone(
            "SELECT COUNT(*) as cnt FROM evaluation_run WHERE experiment_id = ?",
            (self._experiment_id,),
        )

        best_id, best_score = self.get_best_candidate()

        return {
            "experiment_id": self._experiment_id,
            "current_generation": self._current_generation,
            "candidates": candidate_count["cnt"] if candidate_count else 0,
            "evaluations": eval_count["cnt"] if eval_count else 0,
            "jobs": job_stats,
            "best_candidate_id": best_id,
            "best_score": best_score,
            "elite_archive_size": len(self._elite_archive),
        }

    def _update_elite_archive(self, candidate_id: str, score: float) -> None:
        """更新精英档案."""
        # 检查是否已存在
        for i, (cid, _) in enumerate(self._elite_archive):
            if cid == candidate_id:
                if score > self._elite_archive[i][1]:
                    self._elite_archive[i] = (candidate_id, score)
                return

        self._elite_archive.append((candidate_id, score))

        # 保持档案大小
        if len(self._elite_archive) > 100:
            self._elite_archive = sorted(self._elite_archive, key=lambda x: x[1], reverse=True)[
                :100
            ]

    def load_elite_archive(self) -> None:
        """从数据库加载精英档案."""
        rows = self._db.fetchall(
            """
            SELECT candidate_id, MAX(primary_score) as score
            FROM evaluation_run
            WHERE experiment_id = ?
              AND evaluator_version_id = ?
              AND environment_version_id = ?
              AND status = 'completed'
              AND passed = 1
            GROUP BY candidate_id
            ORDER BY score DESC
            LIMIT 100
            """,
            (
                self._experiment_id,
                self._evaluator_version_id,
                self._environment_version_id,
            ),
        )
        self._elite_archive = [(row["candidate_id"], row["score"]) for row in rows if row["score"]]
