"""概率 verifier 数学单元测试（集成计划 §16.1）."""

from __future__ import annotations

import math

import pytest

from omnievolve.eval.verifier import (
    VerificationRequest,
    VerificationStatus,
    bradley_terry_preference,
    build_score_token_map,
    compute_evidence,
    criterion_aggregate,
    token_expectation,
)


class TestTokenExpectation:
    def test_expected_score_over_known_mass(self):
        probabilities = {"0": 0.0, "10": 0.5, "20": 0.5}
        score_map = build_score_token_map(("0", "10", "20"))
        expected, entropy, coverage = token_expectation(probabilities, score_map)
        assert expected == pytest.approx(0.5 * 0.5 + 1.0 * 0.5)
        assert coverage == pytest.approx(1.0)

    def test_missing_token_not_filled_zero(self):
        # 缺失 token 不补零：期望只在已知 mass 上求和，coverage < 1。
        probabilities = {"20": 0.5}
        score_map = build_score_token_map(("0", "10", "20"))
        expected, _, coverage = token_expectation(probabilities, score_map)
        assert expected == pytest.approx(0.5)
        assert coverage == pytest.approx(0.5)

    def test_no_unconditional_renormalization(self):
        # 已知 mass 不全时不得重归一化到 1。
        probabilities = {"0": 0.25}
        score_map = build_score_token_map(("0", "10", "20"))
        expected, _, coverage = token_expectation(probabilities, score_map)
        assert expected == pytest.approx(0.0)
        assert coverage == pytest.approx(0.25)

    def test_entropy_of_certain_distribution_is_zero(self):
        probabilities = {"10": 1.0}
        score_map = build_score_token_map(("0", "10", "20"))
        _, entropy, coverage = token_expectation(probabilities, score_map)
        assert entropy == pytest.approx(0.0, abs=1e-12)
        assert coverage == pytest.approx(1.0)


class TestScoreTokenMap:
    def test_integer_tokens_linear_mapping(self):
        score_map = build_score_token_map(("0", "5", "10", "20"))
        assert score_map["0"] == 0.0
        assert score_map["5"] == 0.25
        assert score_map["10"] == 0.5
        assert score_map["20"] == 1.0

    def test_non_integer_requires_explicit_score(self):
        with pytest.raises(ValueError, match="no explicit score"):
            build_score_token_map(("low", "high"))

    def test_explicit_scores_override(self):
        score_map = build_score_token_map(
            ("low", "high"), explicit_scores={"low": 0.0, "high": 1.0}
        )
        assert score_map["low"] == 0.0
        assert score_map["high"] == 1.0

    def test_out_of_range_mapping_rejected(self):
        with pytest.raises(ValueError, match=r"outside \[0, 1\]"):
            build_score_token_map(("0", "5"), explicit_scores={"0": 0.0, "5": 1.5})


class TestBradleyTerry:
    def test_symmetric(self):
        p_ab = bradley_terry_preference(0.6, 0.4)
        p_ba = bradley_terry_preference(0.4, 0.6)
        assert p_ab == pytest.approx(1.0 - p_ba)

    def test_equal_scores_give_half(self):
        assert bradley_terry_preference(0.5, 0.5) == pytest.approx(0.5)

    def test_numerically_stable_at_extremes(self):
        # P(candidate > peer) = sigmoid(score 差)：
        # sigmoid(1.0) ≈ 0.731，sigmoid(-1.0) ≈ 0.269。
        assert bradley_terry_preference(1.0, 0.0) == pytest.approx(1.0 / (1.0 + math.exp(-1.0)))
        assert bradley_terry_preference(0.0, 1.0) == pytest.approx(1.0 / (1.0 + math.exp(1.0)))
        # 不溢出：极大差距被裁剪到 [-30, 30]。
        value = bradley_terry_preference(1e9, -1e9)
        assert math.isfinite(value)


class TestCriterionAggregate:
    def test_mean_and_variance(self):
        distributions = []
        for value in (0.2, 0.4, 0.6):
            distributions.append(_fake_distribution(expected=value))
        mean, variance, entropy = criterion_aggregate(distributions)
        assert mean == pytest.approx(0.4)
        assert variance == pytest.approx(0.04)

    def test_single_repetition_zero_variance(self):
        mean, variance, _ = criterion_aggregate([_fake_distribution(expected=0.7)])
        assert mean == pytest.approx(0.7)
        assert variance == 0.0

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            criterion_aggregate([])


class TestComputeEvidence:
    def test_preference_and_criterion_scores(self):
        evidence = compute_evidence(
            candidate_scores={"a": 0.6, "b": 0.5},
            peer_scores={"a": 0.4, "b": 0.5},
            variances={"a": 0.01, "b": 0.0},
            entropies={"a": 0.5, "b": 0.3},
            coverage=0.97,
            status=VerificationStatus.COMPLETED,
            evidence_hash="abc",
        )
        assert evidence.candidate_score == pytest.approx(0.55)
        assert evidence.peer_score == pytest.approx(0.45)
        assert evidence.preference_probability > 0.5
        assert evidence.criterion_scores["a"] == pytest.approx(0.2)
        assert evidence.variance == pytest.approx(0.005)
        assert evidence.entropy == pytest.approx(0.4)
        assert evidence.probability_coverage == pytest.approx(0.97)
        assert evidence.status == VerificationStatus.COMPLETED

    def test_mismatched_criteria_rejected(self):
        with pytest.raises(ValueError):
            compute_evidence(
                candidate_scores={"a": 0.5},
                peer_scores={"b": 0.5},
                variances={},
                entropies={},
                coverage=1.0,
                status="completed",
                evidence_hash="x",
            )


class TestVerificationRequestValidation:
    def test_requires_criteria(self):
        with pytest.raises(ValueError, match="at least one criterion"):
            VerificationRequest(
                experiment_id="e",
                candidate_id="c",
                peer_candidate_id="p",
                task_id="t",
                criteria=(),
                granularity=1,
                repetitions=1,
                order_seed=0,
            )

    def test_rejects_self_pair(self):
        with pytest.raises(ValueError, match="must differ"):
            VerificationRequest(
                experiment_id="e",
                candidate_id="same",
                peer_candidate_id="same",
                task_id="t",
                criteria=("specification_fidelity",),
                granularity=1,
                repetitions=1,
                order_seed=0,
            )


def _fake_distribution(expected: float):
    from omnievolve.eval.verifier import ScoreTokenDistribution

    return ScoreTokenDistribution(
        probabilities={"10": 1.0},
        expected_score=expected,
        entropy=0.0,
        covered_probability_mass=1.0,
    )
