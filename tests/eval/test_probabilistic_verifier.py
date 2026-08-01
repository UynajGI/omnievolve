"""ProbabilisticVerifier 运行时行为测试（集成计划 §6.2/§11/§13）.

覆盖审查修复：
- top-K 全概率质量期望与覆盖率（不只取 actual token）；
- order_seed 决定首个 A/B 臂（repetitions=1 不再固定 candidate 在 A 位）；
- live 模式强制成对 A/B 交换；
- max_calls_per_candidate / max_tokens_per_candidate 预算执行；
- 重复测量方差按臂拆分（不混入 treatment effect）；
- 真实 usage 进入证据。
"""

from __future__ import annotations

import pytest

from omnievolve.agents.llm_gateway import TokenScoreResponse
from omnievolve.eval.probabilistic_verifier import (
    ProbabilisticVerifier,
    ProbabilisticVerifierConfig,
)
from omnievolve.eval.verifier import VerificationRequest, VerificationStatus
from omnievolve.exceptions import LLMVerifierCapabilityError

CRITERION = ("specification_fidelity",)

_REQUIRED_EVIDENCE = {
    "task_description": "sort integers",
    "candidate_summary": "def f(x): return sorted(x)",
    "candidate_diff": "",
    "candidate_eval": '{"passed": true}',
    "peer_summary": "def f(x): return x",
    "peer_diff": "",
    "peer_eval": '{"passed": true}',
}


class _ScriptedGateway:
    """按 prompt 中 A/B 臂分配确定性分布；记录调用次数与用量.

    ``position_biased=True`` 时按位置打分（A 位置恒高分、B 位置恒低分），
    与具体臂无关 —— 用于演示 order_seed 如何抵消位置偏差。
    """

    def __init__(
        self,
        candidate_dist: dict[str, float],
        peer_dist: dict[str, float],
        *,
        tokens_per_call: int = 11,
        cost_usd: float | None = None,
        position_biased: bool = False,
    ) -> None:
        self._candidate_dist = dict(candidate_dist)
        self._peer_dist = dict(peer_dist)
        self.tokens_per_call = tokens_per_call
        self._cost_usd = cost_usd
        self._position_biased = position_biased
        self.calls = 0
        self.a_arm_is_candidate: list[bool] = []

    def score_tokens(
        self,
        messages: list[dict[str, str]],
        *,
        score_tokens: tuple[str, ...],
        model: str,
        top_logprobs: int,
        experiment_id: str,
        prompt_version_id: str,
        granularity: int = 1,
        temperature: float = 0.0,
        max_retries: int | None = None,
        endpoints: list | None = None,
    ) -> TokenScoreResponse:
        del score_tokens, top_logprobs, experiment_id, prompt_version_id
        del temperature, max_retries, endpoints
        self.calls += 1
        user = messages[1]["content"]
        a_is_candidate = "--- Candidate A (cand-1) ---" in user
        self.a_arm_is_candidate.append(a_is_candidate)
        if self._position_biased:
            # 纯位置偏差：A 位置高分、B 位置低分（与臂无关）。
            a_dist, b_dist = {"20": 1.0}, {"0": 1.0}
        else:
            a_dist = self._candidate_dist if a_is_candidate else self._peer_dist
            b_dist = self._peer_dist if a_is_candidate else self._candidate_dist
        half = granularity // 2
        positions = [dict(a_dist) for _ in range(half)] + [dict(b_dist) for _ in range(half)]
        actual_tokens = tuple(max(dist, key=dist.get) for dist in positions)
        return TokenScoreResponse(
            content="".join(actual_tokens),
            model=model or "stub-model",
            per_position_probabilities=tuple(positions),
            actual_tokens=actual_tokens,
            probability_coverage=0.99,
            input_tokens=10,
            output_tokens=granularity,
            total_tokens=self.tokens_per_call,
            cost_usd=self._cost_usd,
        )


def _request(order_seed: int = 0, repetitions: int = 1) -> VerificationRequest:
    return VerificationRequest(
        experiment_id="exp-1",
        candidate_id="cand-1",
        peer_candidate_id="peer-1",
        task_id="sort",
        criteria=CRITERION,
        granularity=2,
        repetitions=repetitions,
        order_seed=order_seed,
        evidence=dict(_REQUIRED_EVIDENCE),
    )


def _verifier(
    gateway,
    *,
    granularity: int = 2,
    repetitions: int = 1,
    score_tokens: tuple[str, ...] = ("0", "10", "20"),
    minimum_coverage: float = 0.95,
    max_calls: int = 6,
    max_tokens: int | None = None,
    enforce_paired_swap: bool = False,
    live_min_repetitions: int = 2,
    criteria: tuple[str, ...] = CRITERION,
) -> ProbabilisticVerifier:
    return ProbabilisticVerifier(
        gateway,
        ProbabilisticVerifierConfig(
            model="stub-model",
            criteria=criteria,
            granularity=granularity,
            repetitions=repetitions,
            temperature=0.0,
            minimum_probability_coverage=minimum_coverage,
            prompt_version_id="pv1",
            score_tokens=score_tokens,
            max_calls_per_candidate=max_calls,
            max_tokens_per_candidate=max_tokens,
            enforce_paired_swap=enforce_paired_swap,
            live_min_repetitions=live_min_repetitions,
        ),
        experiment_id="exp-1",
    )


class TestExpectationAndCoverage:
    def test_top_k_expectation_uses_full_distribution(self):
        """top-K 中所有评分 token 都计入期望与覆盖率（P(19)=0.45/P(20)=0.40）."""
        gateway = _ScriptedGateway(
            {"19": 0.45, "20": 0.40, "x": 0.15},
            {"19": 0.45, "20": 0.40, "x": 0.15},
        )
        verifier = _verifier(
            gateway,
            score_tokens=("19", "20"),
            minimum_coverage=0.8,
        )
        evidence = verifier.verify_pair(_request())
        # 每位置期望 = 0.45*0.95 + 0.40*1.0 = 0.8275；两个位置平均。
        assert evidence.candidate_score == pytest.approx(0.8275)
        assert evidence.peer_score == pytest.approx(0.8275)
        # 覆盖率 = 评分 token 概率质量 = 0.85/位置。
        assert evidence.probability_coverage == pytest.approx(0.85)
        assert evidence.status == VerificationStatus.COMPLETED

    def test_coverage_below_threshold_fails_closed(self):
        gateway = _ScriptedGateway(
            {"19": 0.45, "20": 0.40, "x": 0.15},
            {"19": 0.45, "20": 0.40, "x": 0.15},
        )
        verifier = _verifier(
            gateway,
            score_tokens=("19", "20"),
            minimum_coverage=0.95,  # 0.85 < 0.95
        )
        evidence = verifier.verify_pair(_request())
        assert evidence.status == VerificationStatus.INSUFFICIENT_COVERAGE


class TestOrderSeed:
    def test_order_seed_controls_first_arm(self):
        """repetitions=1 时 order_seed 决定 candidate 在 A 还是 B 位."""
        even_gateway = _ScriptedGateway({"20": 1.0}, {"0": 1.0})
        odd_gateway = _ScriptedGateway({"20": 1.0}, {"0": 1.0})
        _verifier(even_gateway).verify_pair(_request(order_seed=0))
        _verifier(odd_gateway).verify_pair(_request(order_seed=1))
        # seed=0 → candidate 在 A 位；seed=1 → candidate 在 B 位。
        assert even_gateway.a_arm_is_candidate == [True]
        assert odd_gateway.a_arm_is_candidate == [False]

    def test_order_seed_offsets_position_bias(self):
        """位置偏差模型（A 位恒高分）：seed 决定偏差落在哪个臂."""
        even_gateway = _ScriptedGateway({"20": 1.0}, {"0": 1.0}, position_biased=True)
        odd_gateway = _ScriptedGateway({"20": 1.0}, {"0": 1.0}, position_biased=True)
        even_evidence = _verifier(even_gateway).verify_pair(_request(order_seed=0))
        odd_evidence = _verifier(odd_gateway).verify_pair(_request(order_seed=1))
        # seed=0：candidate 在 A 位（高分）；seed=1：candidate 在 B 位（低分）。
        assert even_evidence.preference_probability > 0.5
        assert odd_evidence.preference_probability < 0.5


class TestBudgets:
    def test_enforce_paired_swap_raises(self):
        """live 模式（enforce_paired_swap）要求成对 A/B 交换."""
        gateway = _ScriptedGateway({"20": 1.0}, {"0": 1.0})
        verifier = _verifier(gateway, enforce_paired_swap=True, live_min_repetitions=2)
        with pytest.raises(ValueError, match="paired A/B swap"):
            verifier.verify_pair(_request(repetitions=1))

    def test_max_calls_enforced(self):
        """3 criteria × 3 repetitions = 9 次调用 > max_calls=6 → fail closed."""
        gateway = _ScriptedGateway({"20": 1.0}, {"0": 1.0})
        verifier = _verifier(
            gateway,
            max_calls=6,
            criteria=("specification_fidelity", "mechanism_realization", "evidence_consistency"),
        )
        request = VerificationRequest(
            experiment_id="exp-1",
            candidate_id="cand-1",
            peer_candidate_id="peer-1",
            task_id="sort",
            criteria=(
                "specification_fidelity",
                "mechanism_realization",
                "evidence_consistency",
            ),
            granularity=2,
            repetitions=3,
            order_seed=0,
            evidence=dict(_REQUIRED_EVIDENCE),
        )
        with pytest.raises(LLMVerifierCapabilityError, match="call budget exceeded"):
            verifier.verify_pair(request)
        assert gateway.calls == 0

    def test_max_tokens_enforced(self):
        """累计 token 超限 → fail closed（11 token/次，2 次 = 22 > 15）."""
        gateway = _ScriptedGateway({"20": 1.0}, {"0": 1.0}, tokens_per_call=11)
        verifier = _verifier(gateway, max_calls=10, max_tokens=15)
        with pytest.raises(LLMVerifierCapabilityError, match="token budget exceeded"):
            verifier.verify_pair(_request(repetitions=2))
        assert gateway.calls == 2


class TestVarianceAndUsage:
    def test_within_arm_variance_not_confounded_by_treatment(self):
        """两臂各自稳定但均值差大 → 测量方差必须为 0（不混入 treatment）."""
        gateway = _ScriptedGateway({"20": 1.0}, {"0": 1.0})
        verifier = _verifier(gateway, repetitions=2)
        evidence = verifier.verify_pair(_request(repetitions=2))
        assert evidence.variance == 0.0

    def test_usage_recorded_in_evidence(self):
        gateway = _ScriptedGateway({"20": 1.0}, {"0": 1.0}, tokens_per_call=11, cost_usd=0.001)
        verifier = _verifier(gateway)
        evidence = verifier.verify_pair(_request())
        # 1 criterion × 1 repetition = 1 次调用。
        assert evidence.total_tokens == 11
        assert evidence.cost_usd == pytest.approx(0.001)
        assert evidence.cost_known is True
