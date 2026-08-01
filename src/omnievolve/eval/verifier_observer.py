"""VerifierObserver — Fast Loop observer-only verifier hook.

集成计划 §9.1（Phase A，第一轮默认行为）:
- 接在 EvaluationService.evaluate() 返回后、_apply_eval_result() 前；
- 仅对通过硬正确性测试且存在 parent 的候选创建 verifier evidence；
- evidence 写库，绝不修改 ``search_score`` / ``passed`` / ``primary_score``；
- 失败只记录，不阻断进化（observer 是旁路审计）。

输入证据（§5.1）只包含公开任务描述、结构化 diff、AST/代码摘要和
执行摘要；禁止 hidden-test 源码、答案或秘密数据。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from omnievolve.eval.verification_service import VerificationService
from omnievolve.eval.verifier import (
    CandidateVerifier,
    VerificationEvidence,
    VerificationRequest,
)
from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import Database

logger = logging.getLogger(__name__)

_MAX_CODE_CHARS = 2000
_MAX_DIFF_CHARS = 1500


class VerifierObserver:
    """构建 parent-pair VerificationRequest 并持久化证据."""

    def __init__(
        self,
        service: VerificationService,
        verifier: CandidateVerifier,
        *,
        criteria: tuple[str, ...],
        granularity: int,
        repetitions: int,
        order_seed: int,
    ) -> None:
        self._service = service
        self._verifier = verifier
        self._criteria = criteria
        self._granularity = granularity
        self._repetitions = repetitions
        self._order_seed = order_seed

    def observe(
        self,
        *,
        candidate_id: str,
        peer_id: str,
        code_text: str,
        output: Any,
        execution_summary: dict[str, Any],
        thought_summary: str,
        mechanism_tags: list[str],
        generation: int,
        island_id: str,
        task_name: str,
        experiment_id: str,
        evaluator_version_id: str,
        environment_version_id: str,
        db: Database,
        artifact_store: ArtifactStore,
    ) -> VerificationEvidence | None:
        """构建请求并持久化一条观察证据.

        Returns:
            规范化证据；证据构建失败返回 None（observer 不阻断进化）。
        """
        try:
            peer_artifact = db.fetchone(
                "SELECT artifact_hash, diff_artifact_hash FROM candidate WHERE id = ?",
                (peer_id,),
            )
            if peer_artifact is None:
                logger.debug("Verifier observer skipped: peer %s not found", peer_id)
                return None
            peer_code = ""
            peer_diff = ""
            if peer_artifact["artifact_hash"]:
                peer_code = artifact_store.load_text(peer_artifact["artifact_hash"]) or ""
            if peer_artifact["diff_artifact_hash"]:
                peer_diff = artifact_store.load_text(peer_artifact["diff_artifact_hash"]) or ""
            peer_eval = db.fetchone(
                """
                SELECT passed, primary_score, execution_time_ms, memory_peak_kb
                FROM evaluation_run WHERE candidate_id = ?
                ORDER BY COALESCE(finished_at, started_at) DESC LIMIT 1
                """,
                (peer_id,),
            )
        except Exception:
            logger.debug("Verifier observer could not load peer data", exc_info=True)
            return None

        evidence: dict[str, object] = {
            "task_description": task_name,
            "candidate_summary": code_text[:_MAX_CODE_CHARS],
            "candidate_diff": _read_diff(artifact_store, db, candidate_id)[:_MAX_DIFF_CHARS],
            "candidate_eval": _format_eval_summary(output, execution_summary),
            "peer_summary": peer_code[:_MAX_CODE_CHARS],
            "peer_diff": peer_diff[:_MAX_DIFF_CHARS],
            "peer_eval": _format_peer_eval(peer_eval),
            "thought_summary": thought_summary[:500] if thought_summary else "",
            "mechanism_tags": list(mechanism_tags or []),
            "evaluator_version_id": evaluator_version_id,
            "environment_version_id": environment_version_id,
        }
        request = VerificationRequest(
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            peer_candidate_id=peer_id,
            task_id=task_name,
            criteria=self._criteria,
            granularity=self._granularity,
            repetitions=self._repetitions,
            order_seed=self._order_seed,
            evidence=evidence,
        )
        return self._service.verify_pair(
            request,
            self._verifier,
            generation=generation,
            island_id=island_id,
        )


def _read_diff(artifact_store: ArtifactStore, db: Database, candidate_id: str) -> str:
    row = db.fetchone(
        "SELECT diff_artifact_hash FROM candidate WHERE id = ?",
        (candidate_id,),
    )
    if row and row["diff_artifact_hash"]:
        try:
            return artifact_store.load_text(row["diff_artifact_hash"]) or ""
        except Exception:
            return ""
    return ""


def _format_eval_summary(output: Any, execution_summary: dict[str, Any]) -> str:
    return json.dumps(
        {
            "passed": bool(output.passed),
            "score": float(output.score),
            "failure_reason": output.failure_reason[:200] if output.failure_reason else "",
            "execution_time_ms": execution_summary.get("execution_time_ms"),
            "memory_peak_kb": execution_summary.get("memory_peak_kb"),
            "cpu_time_ms": execution_summary.get("cpu_time_ms"),
            "early_stopped": execution_summary.get("early_stopped", False),
        },
        ensure_ascii=False,
    )


def _format_peer_eval(peer_eval: Any) -> str:
    if peer_eval is None:
        return json.dumps({"passed": None, "score": None})
    return json.dumps(
        {
            "passed": bool(peer_eval["passed"]) if peer_eval["passed"] is not None else None,
            "score": float(peer_eval["primary_score"])
            if peer_eval["primary_score"] is not None
            else None,
            "execution_time_ms": peer_eval["execution_time_ms"],
            "memory_peak_kb": peer_eval["memory_peak_kb"],
        },
        ensure_ascii=False,
    )


__all__ = ["VerifierObserver"]
