"""Inspiration Collector — 提取自 EvolutionEngine.

T1 重构第一步：将上下文收集逻辑从 1446 行的 EvolutionEngine 中分离。
包含：父代加载、inspiration 收集、reference edge 写入。

这个组件是无状态的——所有状态通过参数传入。
引擎持有它的实例并委托调用。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from omnievolve.storage.artifact_store import ArtifactStore
    from omnievolve.storage.db import Database
    from omnievolve.storage.repositories.candidate_repo import CandidateRepository

logger = logging.getLogger(__name__)


class InspirationCollector:
    """收集进化上下文 — 父代代码、高分 inspiration、reference edges."""

    def __init__(
        self,
        db: Database,
        candidate_repo: CandidateRepository,
        artifact_store: ArtifactStore,
    ) -> None:
        self._db = db
        self._candidate_repo = candidate_repo
        self._artifact_store = artifact_store

    def load_parents(self, parent_ids: list[str]) -> tuple[list[str], list[str], list[str]]:
        """批量加载父代代码、思想、评估失败信息（T3: 1 次 IN 查询代替 N 次）.

        Returns:
            (codes, thoughts, eval_failures) — eval_failures 包含每个父代最近一次
            失败评估的 stderr/failure_reason（空字符串表示无失败或成功）。
        """
        if not parent_ids:
            return [], [], []

        placeholders = ",".join(["?"] * len(parent_ids))
        rows = self._db.fetchall(
            f"""
            SELECT id, artifact_hash, meta
            FROM candidate
            WHERE id IN ({placeholders})
            """,
            tuple(parent_ids),
        )
        row_map = {row["id"]: row for row in rows}

        codes: list[str] = []
        thoughts: list[str] = []
        failures: list[str] = []
        for pid in parent_ids:
            row = row_map.get(pid)
            if row is None:
                continue
            try:
                code = self._artifact_store.load_text(row["artifact_hash"])
                codes.append(code)
            except Exception:
                logger.debug("Cannot load artifact %s", row["artifact_hash"])
            meta_str = row["meta"]
            if meta_str:
                try:
                    meta = json.loads(meta_str)
                    if isinstance(meta.get("thought"), str):
                        thoughts.append(meta["thought"])
                except (ValueError, TypeError):
                    pass
            # P0-1: Load parent's last evaluation failure (stderr + failure_reason)
            failures.append(self._load_eval_failure(pid))
        return codes, thoughts, failures

    def _load_eval_failure(self, candidate_id: str) -> str:
        """加载候选最近一次失败评估的 stderr/failure_reason（P0-1）.

        优先取 failure_reason（evaluator 解析的人读错误），回退到 stderr 后 500 字。
        成功或无评估记录时返回空字符串。
        """
        try:
            row = self._db.fetchone(
                """
                SELECT er.passed, er.metrics, er.stderr_hash
                FROM evaluation_run er
                WHERE er.candidate_id = ?
                  AND er.status = 'completed'
                ORDER BY er.finished_at DESC
                LIMIT 1
                """,
                (candidate_id,),
            )
        except Exception:
            logger.debug("Failed to load eval failure for %s", candidate_id)
            return ""

        if row is None or row["passed"] == 1:
            return ""

        # 1. Evaluator-provided failure_reason (most readable)
        failure_reason = ""
        try:
            metrics = json.loads(row["metrics"]) if row["metrics"] else {}
            failure_reason = metrics.get("failure_reason", "") or metrics.get("error", "")
        except (ValueError, TypeError):
            pass

        # 2. Raw stderr (fallback or supplement)
        stderr_text = ""
        if row["stderr_hash"]:
            try:
                stderr_text = self._artifact_store.load_text(row["stderr_hash"])
            except Exception:
                logger.debug("Failed to load stderr artifact %s", row["stderr_hash"], exc_info=True)

        # Combine: failure_reason first (if any), then stderr tail
        parts: list[str] = []
        if failure_reason:
            parts.append(failure_reason[:500])
        if stderr_text and stderr_text.strip():
            parts.append(f"stderr:\n{stderr_text[-500:]}")
        return "\n".join(parts) if parts else ""

    def collect_inspiration(
        self,
        experiment_id: str,
        evaluator_version_id: str,
        environment_version_id: str,
        exclude_parent_ids: list[str],
        *,
        top_k: int = 3,
        random_k: int = 2,
        reference_k: int = 1,
    ) -> list[dict]:
        """ShinkaEvolve/AlphaEvolve inspiration programs + P0 cross-branch references.

        三个来源（全部注入**完整代码**，context_builder 按 token 预算截断）：
        - top_k: 全局高分候选
        - random_k: 随机已评估候选（探索）
        - reference_k: candidate_reference_edge 中得分最高的被引用候选 ——
          P0 跨分支引用真正回流到生成（此前只记录不查询）。
        所有来源按 candidate_id 统一去重。
        """
        inspirations: list[dict] = []
        seen: set[str] = set(exclude_parent_ids)

        def _append(cand_id: str, score: float, code: str, source: str) -> None:
            if not code or cand_id in seen:
                return
            seen.add(cand_id)
            inspirations.append(
                {"candidate_id": cand_id, "score": score, "code": code, "source": source}
            )

        # 1) Top-K 高分候选 — 批量加载（完整代码）
        try:
            bests = self._candidate_repo.get_best_candidates(
                experiment_id,
                evaluator_version_id,
                environment_version_id,
                limit=top_k * 2,
            )
            for cand, score in bests:
                if len([i for i in inspirations if i["source"] == "top_k"]) >= top_k:
                    break
                try:
                    code = self._artifact_store.load_text(cand.artifact_hash)
                except Exception:
                    logger.debug("Cannot load artifact %s", cand.artifact_hash)
                    continue
                _append(cand.id, float(score), code, "top_k")
        except Exception:
            logger.debug("Failed to collect top-K inspirations", exc_info=True)

        # 2) Random-K 已评估候选（完整代码）
        try:
            rows = (
                self._db.fetchall(
                    """
                SELECT c.id, c.artifact_hash, er.primary_score
                FROM candidate c
                JOIN evaluation_run er ON c.id = er.candidate_id
                WHERE c.experiment_id = ? AND er.status = 'completed'
                  AND c.id NOT IN ({})
                ORDER BY RANDOM() LIMIT ?
                """.format(
                        ",".join(["?"] * len(exclude_parent_ids)) if exclude_parent_ids else "''"
                    ),
                    (experiment_id, *exclude_parent_ids, random_k * 3),
                )
                if exclude_parent_ids
                else self._db.fetchall(
                    """
                SELECT c.id, c.artifact_hash, er.primary_score
                FROM candidate c
                JOIN evaluation_run er ON c.id = er.candidate_id
                WHERE c.experiment_id = ? AND er.status = 'completed'
                ORDER BY RANDOM() LIMIT ?
                """,
                    (experiment_id, random_k * 3),
                )
            )
            for row in rows or []:
                if len([i for i in inspirations if i["source"] == "random"]) >= random_k:
                    break
                try:
                    code = self._artifact_store.load_text(row["artifact_hash"])
                except Exception:
                    logger.debug("Cannot load artifact %s", row["artifact_hash"])
                    continue
                _append(str(row["id"]), float(row["primary_score"] or 0.0), code, "random")
        except Exception:
            logger.debug("Failed to collect random inspirations", exc_info=True)

        # 3) Reference-edge 高分候选（P0 跨分支回流）— 被引用且得分最高者
        if reference_k > 0:
            try:
                exclude_sql = (
                    ",".join(["?"] * len(exclude_parent_ids)) if exclude_parent_ids else "''"
                )
                params: tuple[Any, ...] = tuple(exclude_parent_ids)
                ref_rows = self._db.fetchall(
                    f"""
                    SELECT e.src_candidate_id AS cid,
                           MAX(er.primary_score) AS best_score,
                           COUNT(*) AS ref_count
                    FROM candidate_reference_edge e
                    JOIN evaluation_run er
                      ON er.candidate_id = e.src_candidate_id AND er.status = 'completed'
                    WHERE e.src_candidate_id NOT IN ({exclude_sql})
                    GROUP BY e.src_candidate_id
                    ORDER BY best_score DESC, ref_count DESC
                    LIMIT ?
                    """,
                    (*params, reference_k * 2),
                )
                for row in ref_rows or []:
                    if (
                        len([i for i in inspirations if i["source"] == "reference_edge"])
                        >= reference_k
                    ):
                        break
                    try:
                        code = self._artifact_store.load_text(
                            self._artifact_hash_for(str(row["cid"]))
                        )
                    except Exception:
                        logger.debug("Cannot load reference-edge artifact %s", row["cid"])
                        continue
                    _append(
                        str(row["cid"]),
                        float(row["best_score"] or 0.0),
                        code,
                        "reference_edge",
                    )
            except Exception:
                logger.debug("Failed to collect reference-edge inspirations", exc_info=True)

        return inspirations

    def _artifact_hash_for(self, candidate_id: str) -> str:
        """按 candidate_id 取 artifact_hash（reference-edge 查询用）."""
        row = self._db.fetchone(
            "SELECT artifact_hash FROM candidate WHERE id = ?",
            (candidate_id,),
        )
        if row is None:
            raise KeyError(f"candidate not found: {candidate_id}")
        return str(row["artifact_hash"])

    def write_reference_edges(
        self,
        child_id: str,
        inspiration: list[dict],
        *,
        parent_ids: list[str],
    ) -> None:
        """P0: 写入跨分支引用边."""
        parent_set = set(parent_ids)
        for insp in inspiration:
            src_id = insp.get("candidate_id", "")
            if not src_id or src_id in parent_set or src_id == child_id:
                continue
            source = insp.get("source", "unknown")
            ref_type = {
                "top_k": "cross_branch",
                "random_k": "exploration",
                "random": "exploration",
                "memory": "memory",
            }.get(source, "reference")
            try:
                self._db.execute(
                    """
                    INSERT OR IGNORE INTO candidate_reference_edge
                        (src_candidate_id, dst_candidate_id, reference_type, detail)
                    VALUES (?, ?, ?, ?)
                    """,
                    (src_id, child_id, ref_type, f"source={source} score={insp.get('score', '?')}"),
                )
            except Exception:
                logger.warning("Failed to write reference edge (P0 cross-branch)", exc_info=True)
