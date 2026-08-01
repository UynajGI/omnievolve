"""FakeProbabilisticVerifier — 确定性概率验证器（测试/研究用）.

不依赖真实 provider：从 request 的稳定字段播种生成确定性概率分布，
支持固定 fixture 与强制状态（failure semantics 测试）。

用途（集成计划 §6.4）:
- deterministic resume 不变式 run(N) == run(K) + resume(N-K)
- research replay 与离线 calibration
- failure semantics 测试
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics

from omnievolve.eval.verifier import (
    ScoreTokenDistribution,
    VerificationEvidence,
    VerificationRequest,
    VerificationStatus,
    bradley_terry_preference,
    token_expectation,
)

_DEFAULT_SCORE_TOKENS = tuple(str(value) for value in range(0, 21))

_REQUIRED_EVIDENCE_KEYS = (
    "task_description",
    "candidate_summary",
    "candidate_diff",
    "candidate_eval",
    "peer_summary",
    "peer_diff",
    "peer_eval",
)


def _stable_seed(request: VerificationRequest, salt: str = "") -> int:
    """从 request 稳定字段派生确定性种子."""
    payload = json.dumps(
        {
            "experiment_id": request.experiment_id,
            "candidate_id": request.candidate_id,
            "peer_candidate_id": request.peer_candidate_id,
            "task_id": request.task_id,
            "criteria": list(request.criteria),
            "granularity": request.granularity,
            "order_seed": request.order_seed,
            "salt": salt,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


class FakeProbabilisticVerifier:
    """确定性概率验证器.

    Args:
        seed: 全局偏移种子（额外 salt）。
        score_tokens: 评分 token 集合（默认 0..20）。
        fixture: 可选的 (candidate_id, peer_candidate_id) → 分数元组映射，
            覆盖确定性生成结果；分数在 [0, 1]。
        force_status: 强制返回状态（测试 failure semantics），
            None 时返回 ``completed``。
        coverage: 概率覆盖率（默认 0.97，可通过 fixture 覆盖）。
    """

    def __init__(
        self,
        *,
        seed: int = 0,
        score_tokens: tuple[str, ...] = _DEFAULT_SCORE_TOKENS,
        fixture: dict[tuple[str, str], tuple[float, float]] | None = None,
        force_status: str | None = None,
        coverage: float = 0.97,
    ) -> None:
        self._seed = seed
        self._score_tokens = score_tokens
        self._fixture = dict(fixture or {})
        self._force_status = force_status
        self._coverage = coverage
        self.calls: list[VerificationRequest] = []

    def verify_pair(self, request: VerificationRequest) -> VerificationEvidence:
        """确定性验证：run(N) == run(K) + resume(N-K) 依赖此实现."""
        self.calls.append(request)
        missing = [
            key for key in _REQUIRED_EVIDENCE_KEYS if key not in request.evidence
        ]
        if missing:
            raise ValueError(
                f"verification evidence missing required keys: {', '.join(missing)}"
            )
        pair = (request.candidate_id, request.peer_candidate_id)

        if self._force_status is not None:
            status = self._force_status
            if status == VerificationStatus.COMPLETED:
                candidate_score = peer_score = 0.5
            else:
                candidate_score = peer_score = 0.0
            return self._build_evidence(
                request,
                candidate_score=candidate_score,
                peer_score=peer_score,
                criterion_scores={criterion: 0.0 for criterion in request.criteria},
                variance=0.0,
                entropy=0.0,
                status=status,
            )

        if pair in self._fixture:
            candidate_score, peer_score = self._fixture[pair]
            criterion_scores = {
                criterion: candidate_score - peer_score
                for criterion in request.criteria
            }
            return self._build_evidence(
                request,
                candidate_score=candidate_score,
                peer_score=peer_score,
                criterion_scores=criterion_scores,
                variance=0.0,
                entropy=0.0,
                status=VerificationStatus.COMPLETED,
            )

        # 确定性：每个 criterion 一个独立播种的 token 分布。
        criterion_scores = {}
        entropies: list[float] = []
        variances: list[float] = []
        score_map = {
            token: (int(token) / 20.0) for token in self._score_tokens
        }
        for criterion_index, criterion in enumerate(request.criteria):
            criterion_rng = random.Random(
                _stable_seed(request, salt=f"criterion:{criterion_index}:{self._seed}")
            )
            # 偏向 candidate 或 peer 的确定性偏好（A/B 交换由上层处理）。
            preference_bias = criterion_rng.uniform(-0.3, 0.3)
            candidate_expected = 0.5 + preference_bias
            peer_expected = 0.5 - preference_bias
            per_repetition_candidate: list[ScoreTokenDistribution] = []
            per_repetition_peer: list[ScoreTokenDistribution] = []
            for repetition in range(request.repetitions):
                rep_rng = random.Random(
                    _stable_seed(
                        request, salt=f"rep:{criterion_index}:{repetition}:{self._seed}"
                    )
                )
                candidate_tokens = self._sample_distribution(
                    rep_rng, candidate_expected
                )
                peer_tokens = self._sample_distribution(rep_rng, peer_expected)
                per_repetition_candidate.append(
                    ScoreTokenDistribution(
                        probabilities=candidate_tokens,
                        expected_score=token_expectation(
                            candidate_tokens, score_map
                        )[0],
                        entropy=token_expectation(candidate_tokens, score_map)[1],
                        covered_probability_mass=self._coverage,
                    )
                )
                per_repetition_peer.append(
                    ScoreTokenDistribution(
                        probabilities=peer_tokens,
                        expected_score=token_expectation(peer_tokens, score_map)[0],
                        entropy=token_expectation(peer_tokens, score_map)[1],
                        covered_probability_mass=self._coverage,
                    )
                )
            candidate_avg = statistics.fmean(
                item.expected_score for item in per_repetition_candidate
            )
            peer_avg = statistics.fmean(
                item.expected_score for item in per_repetition_peer
            )
            criterion_scores[criterion] = candidate_avg - peer_avg
            entropies.append(
                statistics.fmean(
                    item.entropy for item in per_repetition_candidate + per_repetition_peer
                )
            )
            variances.append(
                statistics.variance(
                    [item.expected_score for item in per_repetition_candidate]
                    + [item.expected_score for item in per_repetition_peer]
                )
                if request.repetitions > 1
                else 0.0
            )

        candidate_score = 0.5 + statistics.fmean(criterion_scores.values()) / 2
        peer_score = 0.5 - statistics.fmean(criterion_scores.values()) / 2
        return self._build_evidence(
            request,
            candidate_score=max(0.0, min(1.0, candidate_score)),
            peer_score=max(0.0, min(1.0, peer_score)),
            criterion_scores=criterion_scores,
            variance=statistics.fmean(variances),
            entropy=statistics.fmean(entropies),
            status=VerificationStatus.COMPLETED,
        )

    @staticmethod
    def _sample_distribution(
        rng: random.Random,
        target_mean: float,
    ) -> dict[str, float]:
        """按目标均值抽样一个评分 token 概率分布（覆盖全部 score tokens）."""
        probabilities: dict[str, float] = {}
        for index in range(21):
            distance = abs(float(index) - target_mean * 20.0)
            weight = math.exp(-distance / rng.uniform(2.0, 6.0))
            probabilities[str(index)] = weight + 1e-6
        total = sum(probabilities.values())
        return {token: p / total for token, p in probabilities.items()}

    @staticmethod
    def _build_evidence(
        request: VerificationRequest,
        *,
        candidate_score: float,
        peer_score: float,
        criterion_scores: dict[str, float],
        variance: float,
        entropy: float,
        status: str,
    ) -> VerificationEvidence:
        evidence_hash = hashlib.sha256(
            json.dumps(
                {
                    "candidate_score": candidate_score,
                    "peer_score": peer_score,
                    "criterion_scores": criterion_scores,
                    "status": status,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return VerificationEvidence(
            candidate_score=candidate_score,
            peer_score=peer_score,
            preference_probability=bradley_terry_preference(candidate_score, peer_score),
            criterion_scores=criterion_scores,
            variance=variance,
            entropy=entropy,
            probability_coverage=0.97,
            status=status,
            evidence_hash=evidence_hash,
        )


__all__ = ["FakeProbabilisticVerifier", "_DEFAULT_SCORE_TOKENS"]
