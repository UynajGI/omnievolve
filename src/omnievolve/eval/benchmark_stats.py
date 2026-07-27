"""Deterministic, robust statistics for noisy evaluator benchmarks.

The module intentionally depends only on the Python standard library so the
same analysis is available inside minimal sandbox images.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

Direction = Literal["lower", "higher"]
RegressionDecision = Literal["improvement", "stable", "regression"]


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("at least one value is required")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = min(max(probability, 0.0), 1.0) * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight)


def bootstrap_confidence_interval(
    samples: Sequence[float],
    *,
    confidence: float = 0.95,
    resamples: int = 2_000,
    seed: int = 0,
    statistic: Callable[[Sequence[float]], float] = statistics.median,
) -> tuple[float, float]:
    """Return a deterministic percentile-bootstrap confidence interval."""
    values = tuple(float(value) for value in samples)
    if not values:
        raise ValueError("at least one sample is required")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if resamples < 1:
        raise ValueError("resamples must be positive")
    if len(values) == 1 or len(set(values)) == 1:
        point = float(statistic(values))
        return point, point

    rng = random.Random(seed)
    n = len(values)
    estimates = sorted(
        float(statistic(tuple(values[rng.randrange(n)] for _ in range(n))))
        for _ in range(resamples)
    )
    alpha = (1.0 - confidence) / 2.0
    return _quantile(estimates, alpha), _quantile(estimates, 1.0 - alpha)


@dataclass(frozen=True)
class BenchmarkSummary:
    """Robust summary for one repeated benchmark."""

    samples: tuple[float, ...]
    median: float
    mean: float
    stdev: float
    mad: float
    minimum: float
    maximum: float
    ci_low: float
    ci_high: float
    confidence: float
    outlier_count: int

    @property
    def count(self) -> int:
        return len(self.samples)

    @property
    def relative_margin(self) -> float:
        denominator = max(abs(self.median), 1e-15)
        return (self.ci_high - self.ci_low) / (2.0 * denominator)

    def to_dict(self, *, include_samples: bool = True) -> dict[str, float | int | list[float]]:
        result: dict[str, float | int | list[float]] = {
            "count": self.count,
            "median": self.median,
            "mean": self.mean,
            "stdev": self.stdev,
            "mad": self.mad,
            "min": self.minimum,
            "max": self.maximum,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "confidence": self.confidence,
            "relative_margin": self.relative_margin,
            "outlier_count": self.outlier_count,
        }
        if include_samples:
            result["samples"] = list(self.samples)
        return result


def summarize_samples(
    samples: Sequence[float],
    *,
    confidence: float = 0.95,
    resamples: int = 2_000,
    seed: int = 0,
) -> BenchmarkSummary:
    """Summarize samples using the median, MAD and a bootstrap interval."""
    values = tuple(float(value) for value in samples)
    if not values:
        raise ValueError("at least one sample is required")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("all samples must be finite")

    ordered = sorted(values)
    median = float(statistics.median(values))
    deviations = tuple(abs(value - median) for value in values)
    mad = float(statistics.median(deviations))
    q1 = _quantile(ordered, 0.25)
    q3 = _quantile(ordered, 0.75)
    iqr = q3 - q1
    lower_fence = q1 - 1.5 * iqr
    upper_fence = q3 + 1.5 * iqr
    ci_low, ci_high = bootstrap_confidence_interval(
        values,
        confidence=confidence,
        resamples=resamples,
        seed=seed,
    )
    return BenchmarkSummary(
        samples=values,
        median=median,
        mean=float(statistics.fmean(values)),
        stdev=float(statistics.stdev(values)) if len(values) > 1 else 0.0,
        mad=mad,
        minimum=min(values),
        maximum=max(values),
        ci_low=ci_low,
        ci_high=ci_high,
        confidence=confidence,
        outlier_count=sum(value < lower_fence or value > upper_fence for value in values),
    )


@dataclass(frozen=True)
class RegressionResult:
    """Confidence-aware comparison against a benchmark baseline."""

    decision: RegressionDecision
    direction: Direction
    threshold: float
    relative_change: float
    ci_low: float
    ci_high: float
    baseline: BenchmarkSummary
    current: BenchmarkSummary

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "direction": self.direction,
            "threshold": self.threshold,
            "relative_change": self.relative_change,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "baseline": self.baseline.to_dict(),
            "current": self.current.to_dict(),
        }


def detect_regression(
    baseline_samples: Sequence[float],
    current_samples: Sequence[float],
    *,
    direction: Direction = "lower",
    threshold: float = 0.05,
    confidence: float = 0.95,
    resamples: int = 2_000,
    seed: int = 0,
) -> RegressionResult:
    """Compare two repeated benchmarks using bootstrap relative degradation.

    Positive relative change always means degradation, regardless of whether
    lower or higher values are preferred.
    """
    if direction not in {"lower", "higher"}:
        raise ValueError("direction must be 'lower' or 'higher'")
    if threshold < 0:
        raise ValueError("threshold must be non-negative")

    baseline = summarize_samples(
        baseline_samples,
        confidence=confidence,
        resamples=resamples,
        seed=seed,
    )
    current = summarize_samples(
        current_samples,
        confidence=confidence,
        resamples=resamples,
        seed=seed + 1,
    )

    def degradation(base: float, candidate: float) -> float:
        if direction == "lower":
            return candidate / max(abs(base), 1e-15) - 1.0
        return base / max(abs(candidate), 1e-15) - 1.0

    relative_change = degradation(baseline.median, current.median)
    rng = random.Random(seed + 2)
    base_values = baseline.samples
    current_values = current.samples
    changes = sorted(
        degradation(
            float(statistics.median(rng.choices(base_values, k=len(base_values)))),
            float(statistics.median(rng.choices(current_values, k=len(current_values)))),
        )
        for _ in range(resamples)
    )
    alpha = (1.0 - confidence) / 2.0
    ci_low = _quantile(changes, alpha)
    ci_high = _quantile(changes, 1.0 - alpha)

    decision: RegressionDecision = "stable"
    if ci_low > threshold:
        decision = "regression"
    elif ci_high < -threshold:
        decision = "improvement"

    return RegressionResult(
        decision=decision,
        direction=direction,
        threshold=threshold,
        relative_change=relative_change,
        ci_low=ci_low,
        ci_high=ci_high,
        baseline=baseline,
        current=current,
    )


__all__ = [
    "BenchmarkSummary",
    "RegressionResult",
    "bootstrap_confidence_interval",
    "detect_regression",
    "summarize_samples",
]
