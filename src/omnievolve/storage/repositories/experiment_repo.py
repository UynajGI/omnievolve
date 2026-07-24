"""Experiment Repository.

S1-04: experiment/task/domain 作用域表
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from omnievolve.storage.db import Database
from omnievolve.storage.repositories.base import generate_id, now_iso
from omnievolve.utils import safe_json_loads


@dataclass
class Experiment:
    """实验."""

    id: str
    task_id: str
    task_name: str
    config_snapshot: dict[str, Any]
    domain_id: str | None = None
    status: str = "created"  # created/running/paused/completed/failed
    baseline_candidate_id: str | None = None
    champion_policy_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_compute_sec: float = 0.0


class ExperimentRepository:
    """实验 Repository."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        task_id: str,
        task_name: str,
        config_snapshot: dict[str, Any],
        *,
        domain_id: str | None = None,
    ) -> Experiment:
        """创建实验."""
        exp = Experiment(
            id=generate_id(),
            task_id=task_id,
            task_name=task_name,
            config_snapshot=config_snapshot,
            domain_id=domain_id,
            status="running",
            started_at=now_iso(),
        )

        self._db.execute(
            """
            INSERT INTO experiment
                (id, task_id, task_name, domain_id, status, config_snapshot, started_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exp.id,
                exp.task_id,
                exp.task_name,
                exp.domain_id,
                exp.status,
                json.dumps(exp.config_snapshot),
                exp.started_at,
            ),
        )

        return exp

    def get(self, experiment_id: str) -> Experiment | None:
        """获取实验."""
        row = self._db.fetchone("SELECT * FROM experiment WHERE id = ?", (experiment_id,))
        if row is None:
            return None
        return self._row_to_experiment(row)

    def update_status(
        self,
        experiment_id: str,
        status: str,
        *,
        finished: bool = False,
    ) -> bool:
        """更新状态."""
        if finished:
            cursor = self._db.execute(
                """
                UPDATE experiment
                SET status = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, now_iso(), experiment_id),
            )
        else:
            cursor = self._db.execute(
                "UPDATE experiment SET status = ? WHERE id = ?",
                (status, experiment_id),
            )
        return cursor.rowcount > 0

    def update_costs(
        self,
        experiment_id: str,
        *,
        tokens: int = 0,
        cost_usd: float = 0.0,
        compute_sec: float = 0.0,
    ) -> None:
        """更新成本（增量）."""
        self._db.execute(
            """
            UPDATE experiment
            SET total_tokens = total_tokens + ?,
                total_cost_usd = total_cost_usd + ?,
                total_compute_sec = total_compute_sec + ?
            WHERE id = ?
            """,
            (tokens, cost_usd, compute_sec, experiment_id),
        )

    def set_champion_policy(self, experiment_id: str, policy_id: str) -> bool:
        """设置冠军策略."""
        cursor = self._db.execute(
            "UPDATE experiment SET champion_policy_id = ? WHERE id = ?",
            (policy_id, experiment_id),
        )
        return cursor.rowcount > 0

    def set_baseline(self, experiment_id: str, candidate_id: str) -> bool:
        """设置基线候选."""
        cursor = self._db.execute(
            "UPDATE experiment SET baseline_candidate_id = ? WHERE id = ?",
            (candidate_id, experiment_id),
        )
        return cursor.rowcount > 0

    def list_experiments(
        self,
        *,
        status: str | None = None,
        domain_id: str | None = None,
        limit: int = 100,
    ) -> list[Experiment]:
        """列出实验."""
        conditions = []
        params: list[Any] = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if domain_id:
            conditions.append("domain_id = ?")
            params.append(domain_id)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        rows = self._db.fetchall(
            f"SELECT * FROM experiment WHERE {where} ORDER BY started_at DESC LIMIT ?",
            tuple(params),
        )
        return [self._row_to_experiment(row) for row in rows]

    def _row_to_experiment(self, row: Any) -> Experiment:
        return Experiment(
            id=row["id"],
            task_id=row["task_id"],
            task_name=row["task_name"],
            config_snapshot=safe_json_loads(row["config_snapshot"], default={}),
            domain_id=row["domain_id"],
            status=row["status"],
            baseline_candidate_id=row["baseline_candidate_id"],
            champion_policy_id=row["champion_policy_id"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            total_tokens=row["total_tokens"],
            total_cost_usd=row["total_cost_usd"],
            total_compute_sec=row["total_compute_sec"],
        )
