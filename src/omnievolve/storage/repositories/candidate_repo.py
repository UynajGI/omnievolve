"""Candidate 与 Thought Repository.

S4-01: 实现 Candidate/Thought Repository
S4-02: 实现多父代 CandidateLineage
S4-03: 实现 reference edge 与 lineage edge 分离
S4-04: 实现 SearchState 最小字段与更新规则
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from omnievolve.storage.db import Database
from omnievolve.storage.repositories.base import generate_id, now_iso

logger = logging.getLogger(__name__)


@dataclass
class ThoughtRecord:
    """思想记录."""

    id: str
    experiment_id: str
    task_id: str
    content: str
    domain_id: str | None = None
    rationale: str | None = None
    risk_notes: str | None = None
    confidence: float | None = None
    mechanism_tags: list[str] = field(default_factory=list)
    prompt_version_id: str | None = None
    model_call_id: str | None = None
    created_at: str | None = None


@dataclass
class Candidate:
    """候选."""

    id: str
    experiment_id: str
    task_id: str
    generation: int
    artifact_hash: str
    search_policy_id: str
    island_id: str | None = None
    thought_id: str | None = None
    diff_artifact_hash: str | None = None
    manifest_hash: str | None = None
    status: str = "pending"
    novelty_score: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None


@dataclass
class CandidateLineage:
    """候选血缘（多父代）."""

    child_id: str
    parent_id: str
    relation_type: str  # mutate/crossover/repair/import
    parent_order: int = 0
    op_detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchState:
    """搜索状态."""

    candidate_id: str
    visit_count: int = 0
    value_sum: float = 0.0
    prior: float = 0.0
    virtual_loss: float = 0.0
    selection_count: int = 0
    offspring_count: int = 0
    frontier_status: str = "open"  # open/closed/pruned/elite


class CandidateRepository:
    """Candidate Repository."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create_thought(
        self,
        experiment_id: str,
        task_id: str,
        content: str,
        *,
        domain_id: str | None = None,
        rationale: str | None = None,
        risk_notes: str | None = None,
        confidence: float | None = None,
        mechanism_tags: list[str] | None = None,
        prompt_version_id: str | None = None,
        model_call_id: str | None = None,
    ) -> ThoughtRecord:
        """创建思想记录."""
        thought = ThoughtRecord(
            id=generate_id(),
            experiment_id=experiment_id,
            task_id=task_id,
            content=content,
            domain_id=domain_id,
            rationale=rationale,
            risk_notes=risk_notes,
            confidence=confidence,
            mechanism_tags=mechanism_tags or [],
            prompt_version_id=prompt_version_id,
            model_call_id=model_call_id,
            created_at=now_iso(),
        )

        self._db.execute(
            """
            INSERT INTO thought_record
                (id, experiment_id, task_id, domain_id, content, rationale,
                 risk_notes, confidence, mechanism_tags, prompt_version_id, model_call_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thought.id,
                thought.experiment_id,
                thought.task_id,
                thought.domain_id,
                thought.content,
                thought.rationale,
                thought.risk_notes,
                thought.confidence,
                json.dumps(thought.mechanism_tags),
                thought.prompt_version_id,
                thought.model_call_id,
            ),
        )

        # T4: 同步写入 FTS5 索引
        from omnievolve.storage.migrations import index_thought_fts

        index_thought_fts(
            self._db,
            thought.id,
            thought.content,
            json.dumps(thought.mechanism_tags) if thought.mechanism_tags else "",
        )

        return thought

    def create_candidate(
        self,
        experiment_id: str,
        task_id: str,
        generation: int,
        artifact_hash: str,
        search_policy_id: str,
        *,
        island_id: str | None = None,
        thought_id: str | None = None,
        diff_artifact_hash: str | None = None,
        manifest_hash: str | None = None,
        parents: list[tuple[str, str]] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Candidate:
        """创建候选.

        Args:
            parents: 父代列表 [(parent_id, relation_type), ...]
        """
        candidate = Candidate(
            id=generate_id(),
            experiment_id=experiment_id,
            task_id=task_id,
            generation=generation,
            artifact_hash=artifact_hash,
            search_policy_id=search_policy_id,
            island_id=island_id,
            thought_id=thought_id,
            diff_artifact_hash=diff_artifact_hash,
            manifest_hash=manifest_hash,
            meta=meta or {},
            created_at=now_iso(),
        )

        with self._db.transaction() as conn:
            # 插入候选
            conn.execute(
                """
                INSERT INTO candidate
                    (id, experiment_id, task_id, generation, island_id, thought_id,
                     artifact_hash, diff_artifact_hash, manifest_hash, search_policy_id,
                     status, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.id,
                    candidate.experiment_id,
                    candidate.task_id,
                    candidate.generation,
                    candidate.island_id,
                    candidate.thought_id,
                    candidate.artifact_hash,
                    candidate.diff_artifact_hash,
                    candidate.manifest_hash,
                    candidate.search_policy_id,
                    candidate.status,
                    json.dumps(candidate.meta) if candidate.meta else None,
                ),
            )

            # 插入初始搜索状态
            conn.execute(
                """
                INSERT INTO candidate_search_state (candidate_id)
                VALUES (?)
                """,
                (candidate.id,),
            )

            # 插入血缘关系
            if parents:
                for order, (parent_id, relation_type) in enumerate(parents):
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO candidate_lineage
                            (child_id, parent_id, relation_type, parent_order)
                        VALUES (?, ?, ?, ?)
                        """,
                        (candidate.id, parent_id, relation_type, order),
                    )

        return candidate

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        """获取候选."""
        row = self._db.fetchone("SELECT * FROM candidate WHERE id = ?", (candidate_id,))
        if row is None:
            return None
        return self._row_to_candidate(row)

    def get_parents(self, candidate_id: str) -> list[tuple[str, str, int]]:
        """获取父代列表.

        Returns:
            [(parent_id, relation_type, parent_order), ...]
        """
        rows = self._db.fetchall(
            """
            SELECT parent_id, relation_type, parent_order
            FROM candidate_lineage
            WHERE child_id = ?
            ORDER BY parent_order
            """,
            (candidate_id,),
        )
        return [(row["parent_id"], row["relation_type"], row["parent_order"]) for row in rows]

    def get_children(self, candidate_id: str) -> list[str]:
        """获取子代列表."""
        rows = self._db.fetchall(
            "SELECT child_id FROM candidate_lineage WHERE parent_id = ?",
            (candidate_id,),
        )
        return [row["child_id"] for row in rows]

    def add_reference_edge(
        self,
        src_candidate_id: str,
        dst_candidate_id: str,
        reference_type: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """添加引用边（非血缘）."""
        self._db.execute(
            """
            INSERT OR IGNORE INTO candidate_reference_edge
                (src_candidate_id, dst_candidate_id, reference_type, detail)
            VALUES (?, ?, ?, ?)
            """,
            (
                src_candidate_id,
                dst_candidate_id,
                reference_type,
                json.dumps(detail) if detail else None,
            ),
        )

    def update_status(self, candidate_id: str, status: str) -> bool:
        """更新候选状态."""
        cursor = self._db.execute(
            "UPDATE candidate SET status = ? WHERE id = ?",
            (status, candidate_id),
        )
        return cursor.rowcount > 0

    def update_search_state(
        self,
        candidate_id: str,
        *,
        visit_delta: int = 0,
        value_delta: float = 0.0,
        selection_delta: int = 0,
        offspring_delta: int = 0,
        frontier_status: str | None = None,
    ) -> None:
        """更新搜索状态."""
        updates = ["updated_at = ?"]
        params: list[Any] = [now_iso()]

        if visit_delta:
            updates.append("visit_count = visit_count + ?")
            params.append(visit_delta)
        if value_delta:
            updates.append("value_sum = value_sum + ?")
            params.append(value_delta)
        if selection_delta:
            updates.append("selection_count = selection_count + ?")
            params.append(selection_delta)
        if offspring_delta:
            updates.append("offspring_count = offspring_count + ?")
            params.append(offspring_delta)
        if frontier_status:
            updates.append("frontier_status = ?")
            params.append(frontier_status)

        params.append(candidate_id)

        self._db.execute(
            f"UPDATE candidate_search_state SET {', '.join(updates)} WHERE candidate_id = ?",
            tuple(params),
        )

    def get_search_state(self, candidate_id: str) -> SearchState | None:
        """获取搜索状态."""
        row = self._db.fetchone(
            "SELECT * FROM candidate_search_state WHERE candidate_id = ?",
            (candidate_id,),
        )
        if row is None:
            return None

        return SearchState(
            candidate_id=row["candidate_id"],
            visit_count=row["visit_count"],
            value_sum=row["value_sum"],
            prior=row["prior"],
            virtual_loss=row["virtual_loss"],
            selection_count=row["selection_count"],
            offspring_count=row["offspring_count"],
            frontier_status=row["frontier_status"],
        )

    def list_by_experiment(
        self,
        experiment_id: str,
        generation: int | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Candidate]:
        """列出实验的候选."""
        conditions = ["experiment_id = ?"]
        params: list[Any] = [experiment_id]

        if generation is not None:
            conditions.append("generation = ?")
            params.append(generation)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where = " AND ".join(conditions)
        params.append(limit)

        rows = self._db.fetchall(
            f"SELECT * FROM candidate WHERE {where} ORDER BY generation DESC, id LIMIT ?",
            tuple(params),
        )
        return [self._row_to_candidate(row) for row in rows]

    def get_best_candidates(
        self,
        experiment_id: str,
        evaluator_version_id: str,
        environment_version_id: str,
        limit: int = 10,
    ) -> list[tuple[Candidate, float]]:
        """获取最佳候选（按评估分数）."""
        rows = self._db.fetchall(
            """
            SELECT c.*, er.primary_score
            FROM candidate c
            JOIN evaluation_run er ON c.id = er.candidate_id
            WHERE c.experiment_id = ?
              AND er.evaluator_version_id = ?
              AND er.environment_version_id = ?
              AND er.status = 'completed'
              AND er.passed = 1
            ORDER BY er.primary_score DESC
            LIMIT ?
            """,
            (experiment_id, evaluator_version_id, environment_version_id, limit),
        )
        return [(self._row_to_candidate(row), row["primary_score"]) for row in rows]

    def _row_to_candidate(self, row: Any) -> Candidate:
        """Row 转 Candidate."""
        return Candidate(
            id=row["id"],
            experiment_id=row["experiment_id"],
            task_id=row["task_id"],
            generation=row["generation"],
            artifact_hash=row["artifact_hash"],
            search_policy_id=row["search_policy_id"],
            island_id=row["island_id"],
            thought_id=row["thought_id"],
            diff_artifact_hash=row["diff_artifact_hash"],
            manifest_hash=row["manifest_hash"],
            status=row["status"],
            novelty_score=row["novelty_score"],
            meta=json.loads(row["meta"]) if row["meta"] else {},
            created_at=row["created_at"],
        )
