"""端到端审计报告生成.

S9-13: 实现端到端审计报告生成
    从最佳候选追溯所有父代、LLM、Prompt、环境、评估和策略。

参考 openevolve/evolution_trace.py 的 EvolutionTrace 模式：
    - 从最佳候选向上遍历 candidate_lineage DAG
    - 对每个候选收集：评估运行、LLM 调用、思想记录、策略版本
    - 生成可序列化的审计报告
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from omnievolve.storage.db import Database

logger = logging.getLogger(__name__)


@dataclass
class CandidateAuditEntry:
    """单个候选的审计条目."""

    candidate_id: str
    generation: int
    artifact_hash: str
    search_policy_id: str
    island_id: str | None
    status: str
    parents: list[dict[str, Any]] = field(default_factory=list)
    evaluations: list[dict[str, Any]] = field(default_factory=list)
    thoughts: list[dict[str, Any]] = field(default_factory=list)
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
    search_state: dict[str, Any] | None = None


@dataclass
class PolicyAuditEntry:
    """策略版本审计条目."""

    policy_id: str
    version: int
    status: str
    risk_level: str
    genome: dict[str, Any]
    parent_policy_id: str | None = None


@dataclass
class ExperimentAuditEntry:
    """实验级审计条目."""

    experiment_id: str
    task_name: str
    status: str
    config_snapshot: dict[str, Any]
    baseline_candidate_id: str | None
    champion_policy_id: str | None
    started_at: str | None
    finished_at: str | None
    total_tokens: int = 0
    total_cost_usd: float = 0.0


@dataclass
class AuditReport:
    """完整审计报告."""

    experiment: ExperimentAuditEntry
    best_candidate: CandidateAuditEntry | None
    candidates: list[CandidateAuditEntry]
    policies: list[PolicyAuditEntry]
    lineage_depth: int
    total_llm_calls: int
    total_evaluations: int
    artifact_integrity: dict[str, bool]
    missing_artifacts: list[str]
    missing_vector_indexes: int
    expired_leases: int

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典."""
        return {
            "experiment": asdict(self.experiment),
            "best_candidate": asdict(self.best_candidate) if self.best_candidate else None,
            "candidates": [asdict(c) for c in self.candidates],
            "policies": [asdict(p) for p in self.policies],
            "lineage_depth": self.lineage_depth,
            "total_llm_calls": self.total_llm_calls,
            "total_evaluations": self.total_evaluations,
            "artifact_integrity": self.artifact_integrity,
            "missing_artifacts": self.missing_artifacts,
            "missing_vector_indexes": self.missing_vector_indexes,
            "expired_leases": self.expired_leases,
        }

    def to_json(self, indent: int = 2) -> str:
        """序列化为 JSON."""
        return json.dumps(self.to_dict(), indent=indent, default=str, ensure_ascii=False)


class AuditReportGenerator:
    """端到端审计报告生成器.

    S9-13: 从最佳候选追溯所有父代、LLM、Prompt、环境、评估和策略。
    """

    def __init__(
        self,
        db: Database,
        artifact_dir: str | None = None,
    ) -> None:
        self._db = db
        self._artifact_dir = artifact_dir

    def generate(
        self,
        experiment_id: str,
        *,
        include_all_candidates: bool = False,
    ) -> AuditReport:
        """生成完整审计报告.

        Args:
            experiment_id: 实验 ID
            include_all_candidates: True 时包含所有候选；False 仅包含 best + 血缘链
        """
        exp = self._collect_experiment(experiment_id)
        policies = self._collect_policies(experiment_id)
        best_id = self._find_best_candidate(experiment_id)

        # 收集血缘链上的候选（或全部候选）
        if include_all_candidates:
            candidate_ids = [
                row["id"]
                for row in self._db.fetchall(
                    "SELECT id FROM candidate WHERE experiment_id=? ORDER BY generation",
                    (experiment_id,),
                )
            ]
        else:
            candidate_ids = self._collect_lineage(best_id) if best_id else []

        candidates = [self._collect_candidate(cid, experiment_id) for cid in candidate_ids]

        # Artifact 完整性检查
        artifact_hashes = {c.artifact_hash for c in candidates}
        integrity, missing = self._check_artifacts(artifact_hashes)

        # 缺失向量索引
        pending = self._db.fetchone(
            "SELECT COUNT(*) as n FROM vector_index_job WHERE status='pending'"
        )
        missing_vectors = pending["n"] if pending else 0

        # 过期租约
        expired = self._db.fetchone(
            "SELECT COUNT(*) as n FROM job WHERE status='running' "
            "AND lease_expires_at < datetime('now')"
        )
        expired_leases = expired["n"] if expired else 0

        # 统计
        total_llm = sum(len(c.llm_calls) for c in candidates)
        total_eval = sum(len(c.evaluations) for c in candidates)
        depth = max((c.generation for c in candidates), default=0)

        best_entry = None
        if best_id:
            best_entry = next((c for c in candidates if c.candidate_id == best_id), None)

        return AuditReport(
            experiment=exp,
            best_candidate=best_entry,
            candidates=candidates,
            policies=policies,
            lineage_depth=depth,
            total_llm_calls=total_llm,
            total_evaluations=total_eval,
            artifact_integrity=integrity,
            missing_artifacts=missing,
            missing_vector_indexes=missing_vectors,
            expired_leases=expired_leases,
        )

    # ------------------------------------------------------------------ #
    #  收集方法
    # ------------------------------------------------------------------ #

    def _collect_experiment(self, experiment_id: str) -> ExperimentAuditEntry:
        row = self._db.fetchone("SELECT * FROM experiment WHERE id=?", (experiment_id,))
        if row is None:
            raise ValueError(f"Experiment not found: {experiment_id}")
        return ExperimentAuditEntry(
            experiment_id=row["id"],
            task_name=row["task_name"],
            status=row["status"],
            config_snapshot=json.loads(row["config_snapshot"]) if row["config_snapshot"] else {},
            baseline_candidate_id=row["baseline_candidate_id"],
            champion_policy_id=row["champion_policy_id"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            total_tokens=row["total_tokens"] or 0,
            total_cost_usd=row["total_cost_usd"] or 0.0,
        )

    def _find_best_candidate(self, experiment_id: str) -> str | None:
        row = self._db.fetchone(
            """
            SELECT c.id
            FROM candidate c
            JOIN evaluation_run er ON c.id = er.candidate_id
            WHERE c.experiment_id=? AND er.status='completed'
            ORDER BY er.primary_score DESC LIMIT 1
            """,
            (experiment_id,),
        )
        return row["id"] if row else None

    def _collect_lineage(self, candidate_id: str | None) -> list[str]:
        """从候选向上收集血缘链（BFS）."""
        if candidate_id is None:
            return []
        visited: list[str] = []
        queue = [candidate_id]
        seen: set[str] = set()
        while queue:
            cid = queue.pop(0)
            if cid in seen:
                continue
            seen.add(cid)
            visited.append(cid)
            # 向上找父代
            parents = self._db.fetchall(
                "SELECT parent_id FROM candidate_lineage WHERE child_id=?",
                (cid,),
            )
            for p in parents:
                if p["parent_id"] not in seen:
                    queue.append(p["parent_id"])
        return visited

    def _collect_candidate(self, candidate_id: str, experiment_id: str) -> CandidateAuditEntry:
        """收集单个候选的全部审计数据."""
        row = self._db.fetchone("SELECT * FROM candidate WHERE id=?", (candidate_id,))
        if row is None:
            return CandidateAuditEntry(
                candidate_id=candidate_id,
                generation=-1,
                artifact_hash="",
                search_policy_id="",
                island_id=None,
                status="missing",
            )

        # 父代
        parents = [
            {
                "parent_id": p["parent_id"],
                "relation_type": p["relation_type"],
                "parent_order": p["parent_order"],
            }
            for p in self._db.fetchall(
                "SELECT parent_id, relation_type, parent_order "
                "FROM candidate_lineage WHERE child_id=? ORDER BY parent_order",
                (candidate_id,),
            )
        ]

        # 评估运行
        evals = [
            {
                "run_id": e["id"],
                "evaluator_version_id": e["evaluator_version_id"],
                "environment_version_id": e["environment_version_id"],
                "status": e["status"],
                "passed": e["passed"],
                "primary_score": e["primary_score"],
                "execution_time_ms": e["execution_time_ms"],
            }
            for e in self._db.fetchall(
                "SELECT id, evaluator_version_id, environment_version_id, "
                "status, passed, primary_score, execution_time_ms "
                "FROM evaluation_run WHERE candidate_id=? ORDER BY attempt",
                (candidate_id,),
            )
        ]

        # 思想记录（experiment 级，因为 thought_record 没有 candidate_id 列）
        thoughts = [
            {
                "thought_id": t["id"],
                "content_preview": t["content"][:200] if t["content"] else "",
                "confidence": t["confidence"],
                "mechanism_tags": json.loads(t["mechanism_tags"]) if t["mechanism_tags"] else [],
            }
            for t in self._db.fetchall(
                "SELECT id, content, confidence, mechanism_tags "
                "FROM thought_record WHERE experiment_id=? ORDER BY created_at DESC LIMIT 10",
                (experiment_id,),
            )
        ]

        # LLM 调用
        llm_calls = [
            {
                "call_id": call_row["id"],
                "agent_role": call_row["agent_role"],
                "model": call_row["model"],
                "input_tokens": call_row["input_tokens"],
                "output_tokens": call_row["output_tokens"],
                "cost_usd": call_row["cost_usd"],
            }
            for call_row in self._db.fetchall(
                "SELECT id, agent_role, model, input_tokens, output_tokens, "
                "cost_usd FROM llm_call_ledger WHERE experiment_id=?",
                (experiment_id,),
            )
        ]

        # 搜索状态
        ss = self._db.fetchone(
            "SELECT visit_count, value_sum, selection_count, offspring_count, "
            "frontier_status FROM candidate_search_state WHERE candidate_id=?",
            (candidate_id,),
        )

        return CandidateAuditEntry(
            candidate_id=row["id"],
            generation=row["generation"],
            artifact_hash=row["artifact_hash"],
            search_policy_id=row["search_policy_id"],
            island_id=row["island_id"],
            status=row["status"],
            parents=parents,
            evaluations=evals,
            thoughts=thoughts,
            llm_calls=llm_calls,
            search_state=dict(ss) if ss else None,
        )

    def _collect_policies(self, experiment_id: str) -> list[PolicyAuditEntry]:
        rows = self._db.fetchall(
            "SELECT id, version, status, risk_level, genome, parent_policy_id "
            "FROM search_policy_version WHERE experiment_id=? ORDER BY version",
            (experiment_id,),
        )
        return [
            PolicyAuditEntry(
                policy_id=r["id"],
                version=r["version"],
                status=r["status"],
                risk_level=r["risk_level"],
                genome=json.loads(r["genome"]) if r["genome"] else {},
                parent_policy_id=r["parent_policy_id"],
            )
            for r in rows
        ]

    def _check_artifacts(self, artifact_hashes: set[str]) -> tuple[dict[str, bool], list[str]]:
        """检查 artifact 完整性."""
        from pathlib import Path

        integrity: dict[str, bool] = {}
        missing: list[str] = []
        for h in artifact_hashes:
            # 检查 DB 中是否有记录
            row = self._db.fetchone("SELECT hash FROM artifact WHERE hash=?", (h,))
            if row is None:
                integrity[h] = False
                missing.append(h)
                continue
            # 检查文件是否存在
            if self._artifact_dir:
                # artifact_path_from_hash 格式: sha256/ab/cd/full_hash
                from omnievolve.utils.hashing import artifact_path_from_hash

                p = Path(self._artifact_dir) / artifact_path_from_hash(h)
                if p.exists():
                    integrity[h] = True
                else:
                    integrity[h] = False
                    missing.append(h)
            else:
                integrity[h] = True
        return integrity, missing
