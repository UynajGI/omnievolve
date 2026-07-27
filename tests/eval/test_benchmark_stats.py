"""Tests for deterministic benchmark statistics and regression decisions."""

from __future__ import annotations

import pytest

from omnievolve.eval.benchmark_stats import (
    bootstrap_confidence_interval,
    detect_regression,
    summarize_samples,
)


def test_summary_is_robust_and_deterministic():
    samples = [10.0, 10.1, 9.9, 10.2, 9.8, 100.0]
    first = summarize_samples(samples, seed=42)
    second = summarize_samples(samples, seed=42)

    assert first == second
    assert first.median == pytest.approx(10.05)
    assert first.outlier_count == 1
    assert first.ci_low <= first.median <= first.ci_high
    assert first.count == 6


def test_constant_samples_have_zero_width_interval():
    assert bootstrap_confidence_interval([3.0] * 10) == (3.0, 3.0)


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        ([12.0, 12.1, 11.9, 12.2, 11.8], "regression"),
        ([8.0, 8.1, 7.9, 8.2, 7.8], "improvement"),
        ([10.0, 10.1, 9.9, 10.2, 9.8], "stable"),
    ],
)
def test_detect_regression_for_lower_is_better(current, expected):
    baseline = [10.0, 10.1, 9.9, 10.2, 9.8]
    result = detect_regression(
        baseline,
        current,
        direction="lower",
        threshold=0.05,
        seed=7,
    )
    assert result.decision == expected


def test_detect_regression_for_higher_is_better():
    result = detect_regression(
        [100.0, 101.0, 99.0, 100.5, 99.5],
        [80.0, 81.0, 79.0, 80.5, 79.5],
        direction="higher",
        threshold=0.05,
        seed=7,
    )
    assert result.decision == "regression"


def test_invalid_samples_are_rejected():
    with pytest.raises(ValueError, match="at least one"):
        summarize_samples([])
    with pytest.raises(ValueError, match="finite"):
        summarize_samples([1.0, float("nan")])
