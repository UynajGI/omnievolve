"""Probabilistic LLM-as-a-Verifier 接口与数学.

第一轮范围（PR 1-3）:
- 原生概率 scoring API（token logprob expectation）
- capability probe
- observer-only verifier（只写证据，不改 search_score）
- 完整 provenance（ArtifactStore evidence + DB 摘要）
- 离线 replay calibration

数学定义（集成计划 §4）:
    V(x, τ) = 1 / (C K) * Σ_c Σ_k Σ_g p(v_g | x, c, τ) φ(v_g)
    P(candidate > peer) = sigmoid(V_candidate - V_peer)

评分 token 概率只在已知 mass 上求和，缺失 token 不补零、不无条件
重归一化；覆盖率由调用方单独校验并进入证据。
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# ── 证据状态（§13 failure semantics）──────────────────────────────────


class VerificationStatus:
    """规范化验证证据状态常量."""

    COMPLETED = "completed"
    SKIPPED = "skipped"  # 普通运行回退：provider 不支持 / 证据不完整
    FAILED = "failed"
    UNSUPPORTED = "unsupported"  # provider 无原生 logprobs
    INSUFFICIENT_COVERAGE = "insufficient_coverage"
    INCOMPLETE_EVIDENCE = "incomplete_evidence"
    INTEGRITY_FAILURE = "integrity_failure"  # candidate prompt injection 等


# ── 数据类 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScoreTokenDistribution:
    """单次评分调用中评分 token 的概率分布.

    ``probabilities`` 只在 provider 返回的已知 top-K mass 上取值；
    缺失 token 不会被补零。``covered_probability_mass`` 为已知 mass 总和，
    低于配置门槛时按 fail closed 处理。
    """

    probabilities: dict[str, float]
    expected_score: float
    entropy: float
    covered_probability_mass: float

    def to_dict(self) -> dict[str, object]:
        return {
            "probabilities": dict(self.probabilities),
            "expected_score": self.expected_score,
            "entropy": self.entropy,
            "covered_probability_mass": self.covered_probability_mass,
        }


@dataclass(frozen=True)
class VerificationRequest:
    """一次 parent-pair 验证请求.

    ``evidence`` 只包含公开任务描述、结构化 diff、AST 摘要、执行摘要
    和资源证据；禁止 hidden-test 源码/答案/秘密数据。
    """

    experiment_id: str
    candidate_id: str
    peer_candidate_id: str
    task_id: str
    criteria: tuple[str, ...]
    granularity: int
    repetitions: int
    order_seed: int
    evidence: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.granularity < 1:
            raise ValueError("verification granularity must be positive")
        if self.repetitions < 1:
            raise ValueError("verification repetitions must be positive")
        if not self.criteria:
            raise ValueError("verification requires at least one criterion")
        if self.candidate_id == self.peer_candidate_id:
            raise ValueError("candidate and peer must differ")

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "candidate_id": self.candidate_id,
            "peer_candidate_id": self.peer_candidate_id,
            "task_id": self.task_id,
            "criteria": list(self.criteria),
            "granularity": self.granularity,
            "repetitions": self.repetitions,
            "order_seed": self.order_seed,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class VerificationEvidence:
    """规范化验证证据（用于 ArtifactStore 与 DB 摘要）.

    ``candidate_score`` / ``peer_score`` 是 A/B 交换后的平均偏好分数；
    ``preference_probability`` 是 Bradley-Terry P(candidate > peer)。
    """

    candidate_score: float
    peer_score: float
    preference_probability: float
    criterion_scores: dict[str, float]
    variance: float
    entropy: float
    probability_coverage: float
    status: str
    evidence_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_score": self.candidate_score,
            "peer_score": self.peer_score,
            "preference_probability": self.preference_probability,
            "criterion_scores": dict(self.criterion_scores),
            "variance": self.variance,
            "entropy": self.entropy,
            "probability_coverage": self.probability_coverage,
            "status": self.status,
            "evidence_hash": self.evidence_hash,
        }


@runtime_checkable
class CandidateVerifier(Protocol):
    """候选对概率验证器协议.

    duck-typed（与 TaskEvaluator 一致）：不强制继承，满足签名即实现。
    """

    def verify_pair(self, request: VerificationRequest) -> VerificationEvidence:
        """对候选对执行概率验证并返回规范化证据."""
        ...


# ── 评分 token 映射 ────────────────────────────────────────────────────


def build_score_token_map(
    score_tokens: tuple[str, ...],
    *,
    explicit_scores: dict[str, float] | None = None,
) -> dict[str, float]:
    """构造评分 token → [0, 1] 的映射 φ.

    默认把整数字面量 token（如 "0".."20"）线性映射到 [0, 1]；
    非整数 token 必须通过 ``explicit_scores`` 显式给出，否则抛错，
    避免把任意离散文本冒充概率评分。
    """
    if explicit_scores is None:
        explicit_scores = {}
    if not score_tokens:
        raise ValueError("score token set must not be empty")
    numeric: list[int] = []
    for token in score_tokens:
        if token in explicit_scores:
            continue
        try:
            numeric.append(int(token))
        except ValueError as exc:
            raise ValueError(
                f"score token {token!r} is not an integer literal and has no explicit score"
            ) from exc
    maximum = max(numeric, default=1)
    if maximum < 1:
        raise ValueError("score tokens must include at least one value >= 1")
    mapping: dict[str, float] = {}
    for token in score_tokens:
        if token in explicit_scores:
            value = float(explicit_scores[token])
        else:
            value = int(token) / maximum
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"score token {token!r} maps outside [0, 1]")
        mapping[token] = value
    return mapping


def token_expectation(
    probabilities: dict[str, float],
    score_map: dict[str, float],
) -> tuple[float, float, float]:
    """在已知概率 mass 上计算期望评分、熵与覆盖率.

    缺失 token 不补零、不无条件重归一化；覆盖率 < 1 表示分布信息不足，
    由调用方按 fail closed 处理。

    Returns:
        (expected_score, entropy, covered_mass)
    """
    expected = 0.0
    entropy = 0.0
    covered = 0.0
    for token, probability in probabilities.items():
        if probability <= 0:
            continue
        expected += probability * score_map.get(token, 0.0)
        covered += probability
        if probability > 0:
            entropy -= probability * math.log(probability)
    return expected, entropy, covered


def criterion_aggregate(
    per_repetition: list[ScoreTokenDistribution],
) -> tuple[float, float, float]:
    """聚合单个 criterion 的 K 次重复.

    Returns:
        (expected_score, variance, entropy) — variance 使用样本方差；
        K=1 时方差为 0.0。
    """
    if not per_repetition:
        raise ValueError("criterion requires at least one repetition")
    scores = [item.expected_score for item in per_repetition]
    mean = statistics.fmean(scores)
    variance = statistics.variance(scores) if len(scores) > 1 else 0.0
    entropy = statistics.fmean(item.entropy for item in per_repetition)
    return mean, variance, entropy


def bradley_terry_preference(left_score: float, right_score: float) -> float:
    """P(left > right) = sigmoid(left - right)，数值稳定实现."""
    delta = float(left_score) - float(right_score)
    delta = max(-30.0, min(30.0, delta))
    return 1.0 / (1.0 + math.exp(-delta))


def compute_evidence(
    *,
    candidate_scores: dict[str, float],
    peer_scores: dict[str, float],
    variances: dict[str, float],
    entropies: dict[str, float],
    coverage: float,
    status: str,
    evidence_hash: str,
) -> VerificationEvidence:
    """从 criterion 聚合结果构造 VerificationEvidence.

    candidate/peer 分数均为各 criterion 均值；variance 取各 criterion
    样本方差均值（无重复时记录 0.0）；entropy 为平均熵。
    """
    if not candidate_scores or set(candidate_scores) != set(peer_scores):
        raise ValueError("candidate and peer criterion scores must share the same criteria")
    candidate_score = statistics.fmean(candidate_scores.values())
    peer_score = statistics.fmean(peer_scores.values())
    criterion_scores = {
        criterion: candidate_scores[criterion] - peer_scores[criterion]
        for criterion in candidate_scores
    }
    return VerificationEvidence(
        candidate_score=candidate_score,
        peer_score=peer_score,
        preference_probability=bradley_terry_preference(candidate_score, peer_score),
        criterion_scores=criterion_scores,
        variance=statistics.fmean(variances.values()) if variances else 0.0,
        entropy=statistics.fmean(entropies.values()) if entropies else 0.0,
        probability_coverage=coverage,
        status=status,
        evidence_hash=evidence_hash,
    )


__all__ = [
    "VerificationStatus",
    "ScoreTokenDistribution",
    "VerificationRequest",
    "VerificationEvidence",
    "CandidateVerifier",
    "build_score_token_map",
    "token_expectation",
    "criterion_aggregate",
    "bradley_terry_preference",
    "compute_evidence",
]
