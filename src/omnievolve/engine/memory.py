"""分层记忆.

S7-01: 冻结 MemoryRecord 与 L0~L4 scope 规则
S7-02: 实现 Memory Ingestor 与四元组扩展
S7-03: 实现分层检索预算与去重
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from omnievolve.storage.db import Database
from omnievolve.storage.repositories.base import generate_id, now_iso

logger = logging.getLogger(__name__)


# Scope 级别
SCOPE_BRANCH = 0  # L0 当前分支
SCOPE_EXPERIMENT = 1  # L1 当前实验
SCOPE_TASK_FAMILY = 2  # L2 任务族
SCOPE_DOMAIN = 3  # L3 领域
SCOPE_GLOBAL = 4  # L4 全局


@dataclass
class MemoryRecord:
    """记忆记录."""

    id: str
    scope_level: int
    outcome_summary: dict[str, Any]
    success_flag: bool
    experiment_id: str | None = None
    task_id: str | None = None
    task_family: str | None = None
    domain_id: str | None = None
    branch_id: str | None = None
    thought_id: str | None = None
    candidate_id: str | None = None
    code_diff_hash: str | None = None
    embedding_code_ref: str | None = None
    embedding_thought_ref: str | None = None
    citation_count: int = 0
    adoption_count: int = 0
    created_at: str | None = None


class MemoryStore:
    """分层记忆存储."""

    def __init__(
        self,
        db: Database,
        *,
        scope_weights: dict[int, float] | None = None,
    ) -> None:
        self._db = db
        self._scope_weights = scope_weights or {
            SCOPE_BRANCH: 1.0,
            SCOPE_EXPERIMENT: 0.9,
            SCOPE_TASK_FAMILY: 0.6,
            SCOPE_DOMAIN: 0.4,
            SCOPE_GLOBAL: 0.2,
        }

    def add_memory(
        self,
        scope_level: int,
        outcome_summary: dict[str, Any],
        success_flag: bool,
        *,
        experiment_id: str | None = None,
        task_id: str | None = None,
        task_family: str | None = None,
        domain_id: str | None = None,
        branch_id: str | None = None,
        thought_id: str | None = None,
        candidate_id: str | None = None,
        code_diff_hash: str | None = None,
    ) -> MemoryRecord:
        """添加记忆."""
        memory = MemoryRecord(
            id=generate_id(),
            scope_level=scope_level,
            outcome_summary=outcome_summary,
            success_flag=success_flag,
            experiment_id=experiment_id,
            task_id=task_id,
            task_family=task_family,
            domain_id=domain_id,
            branch_id=branch_id,
            thought_id=thought_id,
            candidate_id=candidate_id,
            code_diff_hash=code_diff_hash,
            created_at=now_iso(),
        )

        self._db.execute(
            """
            INSERT INTO memory_entry
                (id, experiment_id, task_id, task_family, domain_id, branch_id,
                 scope_level, thought_id, candidate_id, code_diff_hash,
                 outcome_summary, success_flag)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory.id,
                memory.experiment_id,
                memory.task_id,
                memory.task_family,
                memory.domain_id,
                memory.branch_id,
                memory.scope_level,
                memory.thought_id,
                memory.candidate_id,
                memory.code_diff_hash,
                json.dumps(memory.outcome_summary),
                1 if memory.success_flag else 0,
            ),
        )

        # T4: 同步写入 FTS5 索引
        from omnievolve.storage.migrations import index_memory_fts

        index_memory_fts(self._db, memory.id, json.dumps(memory.outcome_summary))

        return memory

    def retrieve(
        self,
        *,
        experiment_id: str | None = None,
        task_id: str | None = None,
        domain_id: str | None = None,
        scope_levels: list[int] | None = None,
        success_only: bool = False,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        """检索记忆.

        按 scope 权重排序。
        """
        conditions = []
        params: list[Any] = []

        if scope_levels:
            placeholders = ",".join(["?"] * len(scope_levels))
            conditions.append(f"scope_level IN ({placeholders})")
            params.extend(scope_levels)

        if experiment_id:
            conditions.append("(experiment_id = ? OR experiment_id IS NULL)")
            params.append(experiment_id)

        if task_id:
            conditions.append("(task_id = ? OR task_id IS NULL)")
            params.append(task_id)

        if domain_id:
            conditions.append("(domain_id = ? OR domain_id IS NULL)")
            params.append(domain_id)

        if success_only:
            conditions.append("success_flag = 1")

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        rows = self._db.fetchall(
            f"SELECT * FROM memory_entry WHERE {where} ORDER BY created_at DESC LIMIT ?",
            tuple(params),
        )

        return [self._row_to_memory(row) for row in rows]

    def record_citation(self, memory_id: str) -> None:
        """记录引用."""
        self._db.execute(
            "UPDATE memory_entry SET citation_count = citation_count + 1 WHERE id = ?",
            (memory_id,),
        )

    def record_adoption(self, memory_id: str) -> None:
        """记录采用."""
        self._db.execute(
            "UPDATE memory_entry SET adoption_count = adoption_count + 1 WHERE id = ?",
            (memory_id,),
        )

    def get_stats(self, experiment_id: str | None = None) -> dict[str, Any]:
        """获取统计."""
        if experiment_id:
            row = self._db.fetchone(
                """
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN success_flag = 1 THEN 1 ELSE 0 END) as success,
                       SUM(citation_count) as citations,
                       SUM(adoption_count) as adoptions
                FROM memory_entry WHERE experiment_id = ?
                """,
                (experiment_id,),
            )
        else:
            row = self._db.fetchone(
                """
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN success_flag = 1 THEN 1 ELSE 0 END) as success,
                       SUM(citation_count) as citations,
                       SUM(adoption_count) as adoptions
                FROM memory_entry
                """
            )

        return {
            "total": row["total"] if row else 0,
            "success": row["success"] if row and row["success"] else 0,
            "citations": row["citations"] if row and row["citations"] else 0,
            "adoptions": row["adoptions"] if row and row["adoptions"] else 0,
        }

    def _row_to_memory(self, row: Any) -> MemoryRecord:
        """Row 转 MemoryRecord."""
        return MemoryRecord(
            id=row["id"],
            scope_level=row["scope_level"],
            outcome_summary=json.loads(row["outcome_summary"]),
            success_flag=bool(row["success_flag"]),
            experiment_id=row["experiment_id"],
            task_id=row["task_id"],
            task_family=row["task_family"],
            domain_id=row["domain_id"],
            branch_id=row["branch_id"],
            thought_id=row["thought_id"],
            candidate_id=row["candidate_id"],
            code_diff_hash=row["code_diff_hash"],
            embedding_code_ref=row["embedding_code_ref"],
            embedding_thought_ref=row["embedding_thought_ref"],
            citation_count=row["citation_count"],
            adoption_count=row["adoption_count"],
            created_at=row["created_at"],
        )
