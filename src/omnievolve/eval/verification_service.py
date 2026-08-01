"""VerificationService — 概率验证证据的持久化与失败语义.

集成计划 §8/§9.1（observer 模式）:
- 每次 parent-pair 操作一条 ``verification_batch``；
- 每个候选对一条 ``verification_comparison``；
- 规范化证据（VerificationEvidence + 请求摘要）存入 ArtifactStore，
  数据库只保存 hash 与摘要；
- 幂等：同 request_hash 不重复执行，attempt 递增（resume/replay）；
- 失败语义（§13）：普通运行记录 ``skipped/failed`` 并回退到纯 task
  score；verifier-on 研究运行必须 fail closed。

第一轮 observer 模式只写证据，绝不修改 ``search_score`` / ``passed`` /
``primary_score``。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from omnievolve.eval.verifier import (
    CandidateVerifier,
    VerificationEvidence,
    VerificationRequest,
    VerificationStatus,
)
from omnievolve.exceptions import LLMError, LLMVerifierCapabilityError
from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import Database
from omnievolve.storage.repositories.base import generate_id
from omnievolve.utils.hashing import compute_sha256_str

logger = logging.getLogger(__name__)

_BATCH_MODES = ("observer", "parent_pair", "island_ppt")


def _request_hash(request: VerificationRequest) -> str:
    """稳定请求哈希（幂等键，含顺序与全部配置维度）."""
    return compute_sha256_str(json.dumps(request.to_dict(), ensure_ascii=False, sort_keys=True))


@dataclass(frozen=True)
class VerificationBatchRecord:
    """一次 verification_batch 行的摘要（供引擎与研究 runner 读取）."""

    id: str
    experiment_id: str
    mode: str
    model: str
    status: str
    total_tokens: int
    cost_usd: float | None
    cost_known: bool


class VerificationService:
    """管理验证批次、比较行与 ArtifactStore 证据."""

    def __init__(
        self,
        db: Database,
        artifact_store: ArtifactStore,
        *,
        model: str,
        prompt_version_id: str,
        granularity: int,
        repetitions: int,
        criteria: tuple[str, ...],
        order_seed: int,
        capability_hash: str | None = None,
        mode: str = "observer",
        fail_closed: bool = False,
    ) -> None:
        if mode not in _BATCH_MODES:
            raise ValueError(f"unknown verification mode {mode!r}")
        self._db = db
        self._artifact_store = artifact_store
        self._model = model
        self._prompt_version_id = prompt_version_id
        self._granularity = granularity
        self._repetitions = repetitions
        self._criteria = tuple(criteria)
        self._order_seed = order_seed
        self._capability_hash = capability_hash
        self._mode = mode
        self._fail_closed = fail_closed

    # ── 写入路径 ──────────────────────────────────────────────────────

    def verify_pair(
        self,
        request: VerificationRequest,
        verifier: CandidateVerifier,
        *,
        generation: int | None = None,
        island_id: str | None = None,
    ) -> VerificationEvidence:
        """执行并持久化一次候选对验证.

        幂等：request_hash 已存在时返回已有 evidence 的摘要（不重复调用
        provider）。失败语义按 ``fail_closed`` 区分普通/研究运行。

        Raises:
            LLMError: fail_closed 且证据不足时（研究运行）。
        """
        request_hash = _request_hash(request)
        existing = self._load_comparison(request_hash)
        if existing is not None:
            logger.debug("Verification request %s already recorded; reusing evidence", request_hash[:12])
            return self._load_evidence(existing["evidence_hash"], request, existing)

        batch_id = generate_id()
        started = _now()
        batch = self._db.fetchone(
            "SELECT * FROM verification_batch WHERE id = ?", (batch_id,)
        )
        if batch is None:
            self._db.execute(
                """
                INSERT INTO verification_batch
                    (id, experiment_id, generation, island_id, mode, model,
                     prompt_version_id, granularity, repetitions, criteria_json,
                     order_seed, capability_hash, status, failure_category,
                     total_tokens, cost_usd, cost_known, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    request.experiment_id,
                    generation,
                    island_id,
                    self._mode,
                    self._model,
                    self._prompt_version_id,
                    self._granularity,
                    self._repetitions,
                    json.dumps(list(self._criteria), ensure_ascii=False),
                    self._order_seed,
                    self._capability_hash,
                    "running",
                    None,
                    0,
                    None,
                    1,
                    started,
                ),
            )

        try:
            evidence = verifier.verify_pair(request)
        except LLMVerifierCapabilityError as exc:
            return self._record_failure(
                batch_id,
                request,
                request_hash,
                status=VerificationStatus.UNSUPPORTED,
                failure_category="unsupported_capability",
                message=str(exc),
                started=started,
            )
        except (LLMError, ValueError, RuntimeError) as exc:
            return self._record_failure(
                batch_id,
                request,
                request_hash,
                status=VerificationStatus.FAILED,
                failure_category=type(exc).__name__,
                message=str(exc),
                started=started,
            )

        if evidence.status != VerificationStatus.COMPLETED:
            # verifier 返回非 completed 证据（coverage 不足/不完整/unsupported）：
            # 普通运行记录并回退；研究运行 fail closed（§13）。
            return self._record_non_completed(
                batch_id,
                request,
                request_hash,
                evidence=evidence,
                started=started,
            )

        evidence_hash = self._store_evidence(request, evidence)
        self._insert_comparison(
            batch_id=batch_id,
            request=request,
            request_hash=request_hash,
            evidence=evidence,
            evidence_hash=evidence_hash,
        )
        self._finish_batch(batch_id, started, status="completed", failure_category=None)
        return evidence

    def _record_non_completed(
        self,
        batch_id: str,
        request: VerificationRequest,
        request_hash: str,
        *,
        evidence: VerificationEvidence,
        started: str,
    ) -> VerificationEvidence:
        """verifier 返回非 completed 证据时的失败语义."""
        logger.warning(
            "Verification evidence not completed (%s) for %s/%s",
            evidence.status,
            request.candidate_id[:8],
            request.peer_candidate_id[:8],
        )
        evidence_hash = self._store_evidence(request, evidence)
        self._insert_comparison(
            batch_id=batch_id,
            request=request,
            request_hash=request_hash,
            evidence=evidence,
            evidence_hash=evidence_hash,
            status=evidence.status,
        )
        self._finish_batch(
            batch_id,
            started,
            status="failed",
            failure_category=evidence.status,
        )
        if self._fail_closed:
            if evidence.status == VerificationStatus.UNSUPPORTED:
                raise LLMVerifierCapabilityError(
                    "fail closed: verifier-on run cannot proceed without native logprobs"
                )
            raise LLMError(
                f"fail closed: verification evidence incomplete ({evidence.status})"
            )
        return evidence

    def _record_failure(
        self,
        batch_id: str,
        request: VerificationRequest,
        request_hash: str,
        *,
        status: str,
        failure_category: str,
        message: str,
        started: str,
    ) -> VerificationEvidence:
        """失败语义：普通运行记录并回退；研究运行 fail closed."""
        logger.warning(
            "Verification %s (%s) for %s/%s: %s",
            status,
            failure_category,
            request.candidate_id[:8],
            request.peer_candidate_id[:8],
            message[:300],
        )
        evidence = VerificationEvidence(
            candidate_score=0.0,
            peer_score=0.0,
            preference_probability=0.5,
            criterion_scores={criterion: 0.0 for criterion in request.criteria},
            variance=0.0,
            entropy=0.0,
            probability_coverage=0.0,
            status=status,
            evidence_hash=compute_sha256_str(f"{request_hash}:{status}"),
        )
        evidence_hash = self._store_evidence(request, evidence)
        self._insert_comparison(
            batch_id=batch_id,
            request=request,
            request_hash=request_hash,
            evidence=evidence,
            evidence_hash=evidence_hash,
            status=status,
        )
        self._finish_batch(
            batch_id,
            started,
            status="failed",
            failure_category=failure_category,
        )
        if self._fail_closed and status == VerificationStatus.UNSUPPORTED:
            raise LLMVerifierCapabilityError(
                f"fail closed: verifier-on run cannot proceed without native logprobs ({message})"
            )
        if self._fail_closed:
            raise LLMError(
                f"fail closed: verification evidence incomplete ({status}: {message})"
            )
        return evidence

    # ── 读取路径（observer 审计 / 离线 replay）────────────────────────

    def find_comparison(
        self,
        *,
        candidate_id: str,
        peer_candidate_id: str,
    ) -> list[dict[str, Any]]:
        """按候选对读取比较行（用于离线 replay 与审计）. """
        return [
            dict(row)
            for row in self._db.fetchall(
                """
                SELECT * FROM verification_comparison
                WHERE (left_candidate_id = ? AND right_candidate_id = ?)
                   OR (left_candidate_id = ? AND right_candidate_id = ?)
                ORDER BY attempt DESC
                """,
                (candidate_id, peer_candidate_id, peer_candidate_id, candidate_id),
            )
        ]

    def batches_for_experiment(self, experiment_id: str) -> list[VerificationBatchRecord]:
        rows = self._db.fetchall(
            """
            SELECT id, experiment_id, mode, model, status, total_tokens,
                   cost_usd, cost_known
            FROM verification_batch WHERE experiment_id = ? ORDER BY started_at
            """,
            (experiment_id,),
        )
        return [
            VerificationBatchRecord(
                id=row["id"],
                experiment_id=row["experiment_id"],
                mode=row["mode"],
                model=row["model"],
                status=row["status"],
                total_tokens=row["total_tokens"] or 0,
                cost_usd=row["cost_usd"],
                cost_known=bool(row["cost_known"]),
            )
            for row in rows
        ]

    # ── 内部实现 ──────────────────────────────────────────────────────

    def _store_evidence(
        self,
        request: VerificationRequest,
        evidence: VerificationEvidence,
    ) -> str:
        """规范化证据存入 ArtifactStore，返回 artifact hash."""
        payload = {
            "request": {
                "experiment_id": request.experiment_id,
                "candidate_id": request.candidate_id,
                "peer_candidate_id": request.peer_candidate_id,
                "task_id": request.task_id,
                "criteria": list(request.criteria),
                "granularity": request.granularity,
                "repetitions": request.repetitions,
                "order_seed": request.order_seed,
            },
            "evidence": evidence.to_dict(),
        }
        return self._artifact_store.store_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            "verification_evidence",
            media_type="application/json",
            meta={"evidence_status": evidence.status},
        )

    def _insert_comparison(
        self,
        *,
        batch_id: str,
        request: VerificationRequest,
        request_hash: str,
        evidence: VerificationEvidence,
        evidence_hash: str,
        status: str | None = None,
    ) -> None:
        comparison_status = status or evidence.status
        self._db.execute(
            """
            INSERT INTO verification_comparison
                (id, batch_id, left_candidate_id, right_candidate_id,
                 left_score, right_score, preference_left, variance, entropy,
                 probability_coverage, criterion_scores_json, request_hash,
                 evidence_hash, attempt, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generate_id(),
                batch_id,
                request.candidate_id,
                request.peer_candidate_id,
                evidence.candidate_score,
                evidence.peer_score,
                evidence.preference_probability,
                evidence.variance,
                evidence.entropy,
                evidence.probability_coverage,
                json.dumps(evidence.criterion_scores, ensure_ascii=False),
                request_hash,
                evidence_hash,
                1,
                comparison_status,
            ),
        )

    def _load_comparison(self, request_hash: str) -> dict[str, Any] | None:
        row = self._db.fetchone(
            "SELECT * FROM verification_comparison WHERE request_hash = ? LIMIT 1",
            (request_hash,),
        )
        return dict(row) if row else None

    def _load_evidence(
        self,
        evidence_hash: str,
        request: VerificationRequest,
        row: dict[str, Any],
    ) -> VerificationEvidence:
        """从 ArtifactStore 重建规范化证据（resume/replay 不重复调用 provider）."""
        try:
            raw = self._artifact_store.load_text(evidence_hash)
            payload = json.loads(raw)
            evidence = payload["evidence"]
            return VerificationEvidence(
                candidate_score=float(evidence["candidate_score"]),
                peer_score=float(evidence["peer_score"]),
                preference_probability=float(evidence["preference_probability"]),
                criterion_scores={
                    key: float(value)
                    for key, value in evidence["criterion_scores"].items()
                },
                variance=float(evidence["variance"]),
                entropy=float(evidence["entropy"]),
                probability_coverage=float(evidence["probability_coverage"]),
                status=evidence["status"],
                evidence_hash=evidence["evidence_hash"],
            )
        except Exception:
            # Artifact 缺失时从 DB 摘要重建（退化路径，不阻断审计）。
            return VerificationEvidence(
                candidate_score=float(row["left_score"] or 0.0),
                peer_score=float(row["right_score"] or 0.0),
                preference_probability=float(row["preference_left"] or 0.5),
                criterion_scores={criterion: 0.0 for criterion in request.criteria},
                variance=float(row["variance"] or 0.0),
                entropy=float(row["entropy"] or 0.0),
                probability_coverage=float(row["probability_coverage"] or 0.0),
                status=row["status"],
                evidence_hash=str(row["evidence_hash"] or ""),
            )

    def _finish_batch(
        self,
        batch_id: str,
        started: str,
        *,
        status: str,
        failure_category: str | None,
    ) -> None:
        self._db.execute(
            """
            UPDATE verification_batch
            SET status = ?, failure_category = ?, finished_at = ?
            WHERE id = ?
            """,
            (status, failure_category, _now(), batch_id),
        )


def _now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()


__all__ = ["VerificationService", "VerificationBatchRecord", "_request_hash"]
