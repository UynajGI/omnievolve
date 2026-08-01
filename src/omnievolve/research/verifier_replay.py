"""R1 离线 replay calibration — 概率 verifier 的离线证据评估.

集成计划 §17.2：
- 数据：已有 experiment 的 completed candidates（同 task/evaluator）；
- pair label 只用 primary score 差异超过双方 CI/tolerance 的 pair
  （或 hidden correctness 明确不同 —— 第一轮只用分数差）；
- 比较 G = 1/5/20、K = 1/3、单 criterion vs 三 criteria；
- 报告 pairwise accuracy（含单侧 95% CI 下界）、Brier、ECE、
  tie/abstention rate、Spearman、coverage、token/cost、失败分类。

R1 升级门（§17.2）:
- pairwise accuracy 单侧 95% CI 下界 > 0.5
- Brier score < 0.25
- probability coverage >= 0.95
- 非算法失败率 <= 5%
- 成本已知或协议预先排除成本
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any

from omnievolve.eval.verifier import (
    CandidateVerifier,
    VerificationRequest,
    VerificationStatus,
)
from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import Database

logger = logging.getLogger(__name__)

_DEFAULT_CRITERIA = (
    "specification_fidelity",
    "mechanism_realization",
    "evidence_consistency",
)
_SINGLE_CRITERION = ("specification_fidelity",)
_MAX_CODE_CHARS = 2000
_DEFAULT_REPLAY_SCORE_TOKENS = tuple(str(v) for v in range(0, 21))


@dataclass(frozen=True)
class LabeledPair:
    """一对带 ground-truth label 的候选对."""

    candidate_id: str
    peer_candidate_id: str
    task_id: str
    candidate_score: float
    peer_score: float
    label: float  # +1 = candidate 更优, -1 = peer 更优
    evidence: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class VerifierVariant:
    """一次 calibration 变体（G/K/C 组合）."""

    name: str
    granularity: int
    repetitions: int
    criteria: tuple[str, ...]

    @property
    def criterion_count(self) -> int:
        return len(self.criteria)


@dataclass(frozen=True)
class VariantReport:
    """单个变体的 calibration 报告."""

    name: str
    granularity: int
    repetitions: int
    criteria: tuple[str, ...]
    pairs_attempted: int
    pairs_completed: int
    accuracy: float
    accuracy_ci_lower: float
    brier: float
    ece: float
    tie_rate: float
    spearman: float | None
    probability_coverage: float
    failure_rate: float
    failure_categories: dict[str, int]
    total_tokens: int
    cost_usd: float | None
    cost_known: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "granularity": self.granularity,
            "repetitions": self.repetitions,
            "criteria": list(self.criteria),
            "pairs_attempted": self.pairs_attempted,
            "pairs_completed": self.pairs_completed,
            "accuracy": round(self.accuracy, 6),
            "accuracy_ci_lower": round(self.accuracy_ci_lower, 6),
            "brier": round(self.brier, 6),
            "ece": round(self.ece, 6),
            "tie_rate": round(self.tie_rate, 6),
            "spearman": round(self.spearman, 6) if self.spearman is not None else None,
            "probability_coverage": round(self.probability_coverage, 6),
            "failure_rate": round(self.failure_rate, 6),
            "failure_categories": dict(self.failure_categories),
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "cost_known": self.cost_known,
        }


class VerifierReplayRunner:
    """离线构造 labeled pairs 并运行 G/K/C calibration 变体.

    Args:
        db: 数据库（读取 candidate/evaluation_run）。
        artifact_store: ArtifactStore（读取候选代码摘要）。
        verifier_factory: (variant) -> CandidateVerifier 工厂；真实 provider
            与 Fake verifier 均由调用方注入。
        score_tokens: 评分 token 集合（默认 0..20）。
        token_accounting: 可选 (tokens, cost, cost_known) 回调，用于记录
            真实 provider 的 token/成本。
    """

    def __init__(
        self,
        db: Database,
        artifact_store: ArtifactStore,
        *,
        verifier_factory: Callable[[VerifierVariant], CandidateVerifier],
        score_tokens: tuple[str, ...] = _DEFAULT_REPLAY_SCORE_TOKENS,
        token_accounting: Callable[[], tuple[int, float | None, bool]] | None = None,
    ) -> None:
        self._db = db
        self._artifact_store = artifact_store
        self._verifier_factory = verifier_factory
        self._score_tokens = score_tokens
        self._token_accounting = token_accounting

    # ── 数据构造 ──────────────────────────────────────────────────────

    def build_labeled_pairs(
        self,
        *,
        experiment_id: str | None = None,
        task_id: str | None = None,
        min_score_gap: float = 0.05,
        max_pairs: int = 200,
        seed: int = 42,
    ) -> list[LabeledPair]:
        """构造 label 明确的候选对.

        只使用 completed 且有 primary_score 的 evaluation_run；
        同一 (task, evaluator_version, environment_version) 内 primary
        score 差 >= ``min_score_gap`` 的 pair 才进入数据集
        （避免用测量噪声当 ground truth）。

        每个候选只取 latest 的一条 completed run（按 finished_at/attempt），
        固定 evaluator/environment 语义：同一候选的多版本、多 seed、
        多 attempt 不会被重复当成独立样本，也不会混用不同评估语义的分数。
        """
        import random

        where = ["e.status = 'completed'", "e.primary_score IS NOT NULL"]
        params: list[Any] = []
        if experiment_id:
            where.append("c.experiment_id = ?")
            params.append(experiment_id)
        if task_id:
            where.append("c.task_id = ?")
            params.append(task_id)
        rows = self._db.fetchall(
            f"""
            SELECT c.id AS candidate_id, c.task_id AS task_id,
                   e.primary_score AS score, c.artifact_hash AS artifact_hash,
                   e.evaluator_version_id AS evaluator_version_id,
                   e.environment_version_id AS environment_version_id,
                   e.execution_time_ms AS execution_time_ms
            FROM candidate c
            JOIN evaluation_run e ON e.candidate_id = c.id
            WHERE {" AND ".join(where)}
            ORDER BY COALESCE(e.finished_at, e.started_at) DESC, e.attempt DESC
            """,
            tuple(params),
        )
        # 按 (task, evaluator, environment) 分组；每候选保留 latest run。
        by_scope: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = {}
        for row in rows:
            record = dict(row)
            scope = (
                str(record["task_id"]),
                str(record["evaluator_version_id"]),
                str(record["environment_version_id"]),
            )
            per_candidate = by_scope.setdefault(scope, {})
            per_candidate.setdefault(record["candidate_id"], record)

        pairs: list[LabeledPair] = []
        for (task, _evaluator, _environment), candidates in by_scope.items():
            candidates_list = list(candidates.values())
            for i, left in enumerate(candidates_list):
                for right in candidates_list[i + 1 :]:
                    if left["candidate_id"] == right["candidate_id"]:
                        continue
                    difference = float(left["score"]) - float(right["score"])
                    if abs(difference) < min_score_gap:
                        continue
                    label = 1.0 if difference > 0 else -1.0
                    # 保留原始方向（left/right），label = sign(score 差)，
                    # 使数据集同时包含正负样本。
                    pairs.append(
                        LabeledPair(
                            candidate_id=left["candidate_id"],
                            peer_candidate_id=right["candidate_id"],
                            task_id=task,
                            candidate_score=float(left["score"]),
                            peer_score=float(right["score"]),
                            label=label,
                            evidence=self._build_evidence(left, right, task),
                        )
                    )
        rng = random.Random(seed)
        rng.shuffle(pairs)
        return pairs[:max_pairs]

    def _build_evidence(
        self,
        candidate: dict[str, Any],
        peer: dict[str, Any],
        task_id: str,
    ) -> dict[str, object]:
        """构造发送给 verifier 的证据.

        ground-truth label 来自 primary_score 差异（不进入 prompt）：
        ``candidate_eval``/``peer_eval`` 只含 passed 与执行摘要，
        绝不携带双方分数 —— 否则 R1 accuracy/Brier/Spearman 衡量的
        是模型能否读答案，而不是能否独立验证代码（target leakage）。
        """

        def code_summary(artifact_hash: str) -> str:
            try:
                return (self._artifact_store.load_text(artifact_hash) or "")[:_MAX_CODE_CHARS]
            except Exception:
                return ""

        return {
            "task_description": task_id,
            "candidate_summary": code_summary(candidate["artifact_hash"]),
            "candidate_diff": "",
            "candidate_eval": json.dumps(
                {
                    "passed": True,
                    "execution_time_ms": candidate.get("execution_time_ms"),
                }
            ),
            "peer_summary": code_summary(peer["artifact_hash"]),
            "peer_diff": "",
            "peer_eval": json.dumps(
                {"passed": True, "execution_time_ms": peer.get("execution_time_ms")}
            ),
            "thought_summary": "",
            "mechanism_tags": [],
            "evaluator_version_id": candidate.get("evaluator_version_id", "replay"),
            "environment_version_id": candidate.get("environment_version_id", "replay"),
        }

    # ── 变体运行 ──────────────────────────────────────────────────────

    def run_variant(
        self,
        pairs: list[LabeledPair],
        variant: VerifierVariant,
        *,
        tie_threshold: float = 0.05,
    ) -> VariantReport:
        """在固定 G/K/C 变体上运行全部 pair 并计算指标."""
        verifier = self._verifier_factory(variant)
        preferences: list[float] = []
        labels: list[float] = []
        score_differences: list[float] = []
        coverages: list[float] = []
        failure_categories: dict[str, int] = {}
        completed = 0
        tokens_before, cost_before, _ = self._accounting_snapshot()

        for pair in pairs:
            request = VerificationRequest(
                experiment_id="replay",
                candidate_id=pair.candidate_id,
                peer_candidate_id=pair.peer_candidate_id,
                task_id=pair.task_id,
                criteria=variant.criteria,
                granularity=variant.granularity,
                repetitions=variant.repetitions,
                order_seed=42,
                evidence=pair.evidence,
            )
            try:
                evidence = verifier.verify_pair(request)
            except Exception as exc:
                failure_categories[type(exc).__name__] = (
                    failure_categories.get(type(exc).__name__, 0) + 1
                )
                continue
            if evidence.status != VerificationStatus.COMPLETED:
                failure_categories[evidence.status] = failure_categories.get(evidence.status, 0) + 1
                continue
            completed += 1
            preferences.append(evidence.preference_probability)
            labels.append(1.0 if pair.label > 0 else 0.0)
            score_differences.append(pair.candidate_score - pair.peer_score)
            coverages.append(evidence.probability_coverage)

        tokens_after, cost_after, cost_known = self._accounting_snapshot()
        total_tokens = max(0, tokens_after - tokens_before)
        cost_usd = None
        if cost_before is not None and cost_after is not None:
            cost_usd = max(0.0, cost_after - cost_before)
        elif cost_known is False:
            cost_known = False

        if not preferences:
            return VariantReport(
                name=variant.name,
                granularity=variant.granularity,
                repetitions=variant.repetitions,
                criteria=variant.criteria,
                pairs_attempted=len(pairs),
                pairs_completed=0,
                accuracy=0.0,
                accuracy_ci_lower=0.0,
                brier=1.0,
                ece=1.0,
                tie_rate=1.0,
                spearman=None,
                probability_coverage=0.0,
                failure_rate=1.0,
                failure_categories=failure_categories,
                total_tokens=total_tokens,
                cost_usd=cost_usd,
                cost_known=cost_known,
            )

        # accuracy 只在非 tie 的 pair 上计算：preference == 0.5 是 abstention，
        # 不得隐式映射为"预测 peer 胜出"（否则恒定输出 0.5 的 verifier
        # 会按 pair 方向分布获得虚假 accuracy）。tie 单独报告。
        non_tie = [
            (preference, label)
            for preference, label in zip(preferences, labels)
            if abs(preference - 0.5) >= tie_threshold
        ]
        correct = [(preference > 0.5) == (label > 0.5) for preference, label in non_tie]
        accuracy = statistics.fmean(correct) if correct else 0.0
        accuracy_ci_lower = _one_sided_ci_lower(accuracy, len(correct))
        brier = statistics.fmean(
            (preference - label) ** 2 for preference, label in zip(preferences, labels)
        )
        tie_rate = statistics.fmean(
            1.0 if abs(preference - 0.5) < tie_threshold else 0.0 for preference in preferences
        )
        ece = _expected_calibration_error(preferences, labels)
        spearman = _spearman(preferences, score_differences)
        total_failures = sum(failure_categories.values())
        failure_rate = total_failures / max(len(pairs), 1)
        return VariantReport(
            name=variant.name,
            granularity=variant.granularity,
            repetitions=variant.repetitions,
            criteria=variant.criteria,
            pairs_attempted=len(pairs),
            pairs_completed=completed,
            accuracy=accuracy,
            accuracy_ci_lower=accuracy_ci_lower,
            brier=brier,
            ece=ece,
            tie_rate=tie_rate,
            spearman=spearman,
            probability_coverage=statistics.fmean(coverages),
            failure_rate=failure_rate,
            failure_categories=failure_categories,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            cost_known=cost_known,
        )

    def run_calibration(
        self,
        pairs: list[LabeledPair],
        *,
        granularities: tuple[int, ...] = (1, 5, 20),
        repetitions: tuple[int, ...] = (1, 3),
        criteria_options: tuple[tuple[str, ...], ...] = (
            _SINGLE_CRITERION,
            _DEFAULT_CRITERIA,
        ),
        tie_threshold: float = 0.05,
    ) -> list[VariantReport]:
        """运行 G × K × C 全组合 calibration."""
        reports: list[VariantReport] = []
        for granularity in granularities:
            for repetition in repetitions:
                for criteria in criteria_options:
                    name = f"G{granularity}_K{repetition}_C{len(criteria)}"
                    variant = VerifierVariant(
                        name=name,
                        granularity=granularity,
                        repetitions=repetition,
                        criteria=criteria,
                    )
                    reports.append(self.run_variant(pairs, variant, tie_threshold=tie_threshold))
        return reports

    def _accounting_snapshot(self) -> tuple[int, float | None, bool]:
        if self._token_accounting is None:
            return 0, None, False
        try:
            tokens, cost, cost_known = self._token_accounting()
            return int(tokens), float(cost) if cost is not None else None, bool(cost_known)
        except Exception:
            return 0, None, False


@dataclass(frozen=True)
class R1Gate:
    """R1 升级门评估结果（§17.2）."""

    passed: bool
    reasons: tuple[str, ...]
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reasons": list(self.reasons),
            "details": self.details,
        }


def assess_r1_gate(
    report: VariantReport,
    *,
    accuracy_null: float = 0.5,
    brier_max: float = 0.25,
    coverage_min: float = 0.95,
    failure_max: float = 0.05,
    cost_excluded: bool = False,
    min_pairs: int = 30,
) -> R1Gate:
    """对单个变体应用 R1 升级门（§17.2）.

    小样本保护：``min_pairs`` 设定了有效 pair 数下限，防止极少证据
    （如 1-3 个全部成功 pair）在 Wilson 区间下仍被放行。
    """
    reasons: list[str] = []
    if report.pairs_completed == 0:
        reasons.append("no completed pairs")
    elif report.pairs_completed < min_pairs:
        reasons.append(f"completed pairs {report.pairs_completed} < minimum {min_pairs}")
    if report.accuracy_ci_lower <= accuracy_null:
        reasons.append(f"accuracy CI lower bound {report.accuracy_ci_lower:.3f} <= {accuracy_null}")
    if report.brier >= brier_max:
        reasons.append(f"brier {report.brier:.3f} >= {brier_max}")
    if report.probability_coverage < coverage_min:
        reasons.append(f"coverage {report.probability_coverage:.3f} < {coverage_min}")
    if report.failure_rate > failure_max:
        reasons.append(f"failure rate {report.failure_rate:.3f} > {failure_max}")
    if not cost_excluded and not report.cost_known:
        reasons.append("cost unknown and not pre-excluded")
    return R1Gate(
        passed=not reasons,
        reasons=tuple(reasons),
        details={"accuracy_ci_lower": report.accuracy_ci_lower, "brier": report.brier},
    )


def write_report(reports: list[VariantReport], path: str) -> str:
    """把 calibration 报告写入 JSON 文件（research 产物惯例）."""
    payload = {
        "protocol": "R1-verifier-replay-calibration",
        "variants": [report.to_dict() for report in reports],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def _one_sided_ci_lower(accuracy: float, count: int) -> float:
    """单侧 95% 二项比例 CI 下界（Wilson score interval）.

    相比 Wald 正态近似：在 accuracy 接近 0/1 或样本极小时不会给出
    虚假的窄区间（Wald 对 ``accuracy=1.0, count=1`` 返回 ~1.0，
    使 R1 门在极少证据下错误放行）。
    """
    if count == 0:
        return 0.0
    z_value = NormalDist().inv_cdf(0.95)
    n = float(count)
    denominator = 1.0 + z_value**2 / n
    center = (accuracy + z_value**2 / (2 * n)) / denominator
    margin = (
        z_value * math.sqrt((accuracy * (1 - accuracy) + z_value**2 / (4 * n)) / n) / denominator
    )
    return max(0.0, center - margin)


def _expected_calibration_error(
    preferences: list[float],
    labels: list[float],
    bins: int = 10,
) -> float:
    """按 10 桶计算的 ECE."""
    if not preferences:
        return 1.0
    width = 1.0 / bins
    total = 0.0
    count = 0
    for index in range(bins):
        low, high = index * width, (index + 1) * width
        bucket = [
            (p, label)
            for p, label in zip(preferences, labels)
            if low <= p < high or (index == bins - 1 and p == 1.0)
        ]
        if not bucket:
            continue
        confidence = statistics.fmean(p for p, _ in bucket)
        accuracy = statistics.fmean(label for _, label in bucket)
        total += len(bucket) * abs(confidence - accuracy)
        count += len(bucket)
    return total / count if count else 1.0


def _spearman(preferences: list[float], scores: list[float]) -> float | None:
    """Spearman 秩相关（preference vs 分数差）."""
    if len(preferences) < 3:
        return None
    try:
        pref_ranks = _rank(preferences)
        score_ranks = _rank(scores)
        mean_p = statistics.fmean(pref_ranks)
        mean_s = statistics.fmean(score_ranks)
        numerator = sum((p - mean_p) * (s - mean_s) for p, s in zip(pref_ranks, score_ranks))
        denominator = math.sqrt(
            sum((p - mean_p) ** 2 for p in pref_ranks) * sum((s - mean_s) ** 2 for s in score_ranks)
        )
        if denominator == 0:
            return None
        return numerator / denominator
    except Exception:
        return None


def _rank(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        duplicate = 1
        while (
            index + duplicate < len(ordered) and ordered[index + duplicate][1] == ordered[index][1]
        ):
            duplicate += 1
        average = index + 1 + (duplicate - 1) / 2
        for offset in range(duplicate):
            ranks[ordered[index + offset][0]] = average
        index += duplicate
    return ranks


__all__ = [
    "LabeledPair",
    "VerifierVariant",
    "VariantReport",
    "R1Gate",
    "VerifierReplayRunner",
    "assess_r1_gate",
    "write_report",
    "_DEFAULT_CRITERIA",
    "_SINGLE_CRITERION",
]
