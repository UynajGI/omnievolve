"""EvaluationRun 状态机与 Repository.

S3-06: 实现 EvaluationRun 状态机
- queued -> running -> completed/failed
- 随机种子、重复次数、统计字段

S3-07: 实现随机种子、重复次数与统计字段
S3-08: 实现正确性门与性能评分解耦
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from omnievolve.storage.db import Database
from omnievolve.storage.repositories.base import generate_id, now_iso

logger = logging.getLogger(__name__)


class EvaluationRunStatus(str, Enum):
    """EvaluationRun 状态."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class EvaluationRun:
    """评估运行记录."""

    id: str
    experiment_id: str
    candidate_id: str
    evaluator_version_id: str
    environment_version_id: str
    seed: int | None = None
    split_name: str = "default"
    attempt: int = 1
    status: EvaluationRunStatus = EvaluationRunStatus.QUEUED
    passed: bool | None = None
    primary_score: float | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    execution_time_ms: float | None = None
    memory_peak_kb: int | None = None
    cpu_time_ms: float | None = None
    stdout_hash: str | None = None
    stderr_hash: str | None = None
    result_hash: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "experiment_id": self.experiment_id,
            "candidate_id": self.candidate_id,
            "evaluator_version_id": self.evaluator_version_id,
            "environment_version_id": self.environment_version_id,
            "seed": self.seed,
            "split_name": self.split_name,
            "attempt": self.attempt,
            "status": self.status.value,
            "passed": 1 if self.passed else 0 if self.passed is not None else None,
            "primary_score": self.primary_score,
            "metrics": json.dumps(self.metrics) if self.metrics else None,
            "execution_time_ms": self.execution_time_ms,
            "memory_peak_kb": self.memory_peak_kb,
            "cpu_time_ms": self.cpu_time_ms,
            "stdout_hash": self.stdout_hash,
            "stderr_hash": self.stderr_hash,
            "result_hash": self.result_hash,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_row(cls, row: Any) -> EvaluationRun:
        """从数据库 Row 创建."""
        return cls(
            id=row["id"],
            experiment_id=row["experiment_id"],
            candidate_id=row["candidate_id"],
            evaluator_version_id=row["evaluator_version_id"],
            environment_version_id=row["environment_version_id"],
            seed=row["seed"],
            split_name=row["split_name"],
            attempt=row["attempt"],
            status=EvaluationRunStatus(row["status"]),
            passed=bool(row["passed"]) if row["passed"] is not None else None,
            primary_score=row["primary_score"],
            metrics=json.loads(row["metrics"]) if row["metrics"] else {},
            execution_time_ms=row["execution_time_ms"],
            memory_peak_kb=row["memory_peak_kb"],
            cpu_time_ms=row["cpu_time_ms"],
            stdout_hash=row["stdout_hash"],
            stderr_hash=row["stderr_hash"],
            result_hash=row["result_hash"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )


class EvaluationRunRepository:
    """EvaluationRun Repository.

    管理评估运行的生命周期。
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        experiment_id: str,
        candidate_id: str,
        evaluator_version_id: str,
        environment_version_id: str,
        *,
        seed: int | None = None,
        split_name: str = "default",
        attempt: int = 1,
    ) -> EvaluationRun:
        """创建评估运行.

        使用幂等键：(candidate_id, evaluator_version_id, environment_version_id, seed, split_name, attempt)
        """
        run_id = generate_id()

        run = EvaluationRun(
            id=run_id,
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            evaluator_version_id=evaluator_version_id,
            environment_version_id=environment_version_id,
            seed=seed,
            split_name=split_name,
            attempt=attempt,
        )

        try:
            self._db.execute(
                """
                INSERT INTO evaluation_run
                    (id, experiment_id, candidate_id, evaluator_version_id,
                     environment_version_id, seed, split_name, attempt, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.experiment_id,
                    run.candidate_id,
                    run.evaluator_version_id,
                    run.environment_version_id,
                    run.seed,
                    run.split_name,
                    run.attempt,
                    run.status.value,
                ),
            )
        except Exception:
            # 可能是唯一约束冲突（幂等键已存在）
            existing = self.get_by_idempotent_key(
                candidate_id,
                evaluator_version_id,
                environment_version_id,
                seed,
                split_name,
                attempt,
            )
            if existing:
                return existing
            raise

        return run

    def get(self, run_id: str) -> EvaluationRun | None:
        """根据 ID 获取."""
        row = self._db.fetchone("SELECT * FROM evaluation_run WHERE id = ?", (run_id,))
        if row is None:
            return None
        return EvaluationRun.from_row(row)

    def get_by_idempotent_key(
        self,
        candidate_id: str,
        evaluator_version_id: str,
        environment_version_id: str,
        seed: int | None,
        split_name: str,
        attempt: int,
    ) -> EvaluationRun | None:
        """根据幂等键获取."""
        row = self._db.fetchone(
            """
            SELECT * FROM evaluation_run
            WHERE candidate_id = ? AND evaluator_version_id = ? AND environment_version_id = ?
              AND seed IS ? AND split_name = ? AND attempt = ?
            """,
            (
                candidate_id,
                evaluator_version_id,
                environment_version_id,
                seed,
                split_name,
                attempt,
            ),
        )
        if row is None:
            return None
        return EvaluationRun.from_row(row)

    def start(self, run_id: str) -> bool:
        """标记为运行中."""
        cursor = self._db.execute(
            """
            UPDATE evaluation_run
            SET status = ?, started_at = ?
            WHERE id = ? AND status = ?
            """,
            (
                EvaluationRunStatus.RUNNING.value,
                now_iso(),
                run_id,
                EvaluationRunStatus.QUEUED.value,
            ),
        )
        return cursor.rowcount > 0

    def complete(
        self,
        run_id: str,
        *,
        passed: bool,
        primary_score: float,
        metrics: dict[str, float] | None = None,
        execution_time_ms: float | None = None,
        memory_peak_kb: int | None = None,
        cpu_time_ms: float | None = None,
        stdout_hash: str | None = None,
        stderr_hash: str | None = None,
        result_hash: str | None = None,
    ) -> bool:
        """标记为完成."""
        cursor = self._db.execute(
            """
            UPDATE evaluation_run
            SET status = ?, passed = ?, primary_score = ?, metrics = ?,
                execution_time_ms = ?, memory_peak_kb = ?, cpu_time_ms = ?,
                stdout_hash = ?, stderr_hash = ?, result_hash = ?, finished_at = ?
            WHERE id = ? AND status = ?
            """,
            (
                EvaluationRunStatus.COMPLETED.value,
                1 if passed else 0,
                primary_score,
                json.dumps(metrics) if metrics else None,
                execution_time_ms,
                memory_peak_kb,
                cpu_time_ms,
                stdout_hash,
                stderr_hash,
                result_hash,
                now_iso(),
                run_id,
                EvaluationRunStatus.RUNNING.value,
            ),
        )
        return cursor.rowcount > 0

    def fail(self, run_id: str, error: str | None = None) -> bool:
        """标记为失败."""
        cursor = self._db.execute(
            """
            UPDATE evaluation_run
            SET status = ?, finished_at = ?
            WHERE id = ? AND status IN (?, ?)
            """,
            (
                EvaluationRunStatus.FAILED.value,
                now_iso(),
                run_id,
                EvaluationRunStatus.QUEUED.value,
                EvaluationRunStatus.RUNNING.value,
            ),
        )
        return cursor.rowcount > 0

    def list_by_candidate(self, candidate_id: str, limit: int = 100) -> list[EvaluationRun]:
        """列出候选的所有评估运行."""
        rows = self._db.fetchall(
            """
            SELECT * FROM evaluation_run
            WHERE candidate_id = ?
            ORDER BY id
            LIMIT ?
            """,
            (candidate_id, limit),
        )
        return [EvaluationRun.from_row(row) for row in rows]

    def list_by_experiment(
        self,
        experiment_id: str,
        status: EvaluationRunStatus | None = None,
        limit: int = 100,
    ) -> list[EvaluationRun]:
        """列出实验的评估运行."""
        if status:
            rows = self._db.fetchall(
                """
                SELECT * FROM evaluation_run
                WHERE experiment_id = ? AND status = ?
                ORDER BY id
                LIMIT ?
                """,
                (experiment_id, status.value, limit),
            )
        else:
            rows = self._db.fetchall(
                """
                SELECT * FROM evaluation_run
                WHERE experiment_id = ?
                ORDER BY id
                LIMIT ?
                """,
                (experiment_id, limit),
            )
        return [EvaluationRun.from_row(row) for row in rows]

    def get_best_score(
        self,
        experiment_id: str,
        evaluator_version_id: str,
        environment_version_id: str,
    ) -> float | None:
        """获取最佳分数."""
        row = self._db.fetchone(
            """
            SELECT MAX(primary_score) as best
            FROM evaluation_run
            WHERE experiment_id = ? AND evaluator_version_id = ? AND environment_version_id = ?
              AND status = ? AND passed = 1
            """,
            (
                experiment_id,
                evaluator_version_id,
                environment_version_id,
                EvaluationRunStatus.COMPLETED.value,
            ),
        )
        return row["best"] if row and row["best"] is not None else None
