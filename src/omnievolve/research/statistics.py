"""Statistical gates for evaluator calibration and paired research runs."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from statistics import NormalDist
from typing import Any


@dataclass(frozen=True)
class NoiseCalibration:
    repeats: int
    mean: float
    standard_deviation: float
    ci_half_width: float
    target_half_width: float
    converged: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calibrate_evaluator_noise(
    measurements: Sequence[float],
    *,
    reference_scale: float | None = None,
    minimum_effect: float = 0.05,
    confidence: float = 0.95,
    min_repeats: int = 3,
    max_repeats: int = 10,
) -> NoiseCalibration:
    """Choose the first repeat count whose CI resolves the target effect.

    ``measurements`` must be ordered exactly as collected from one frozen
    candidate. The function never invents samples: if the available prefix is
    insufficient it returns ``converged=False`` at the largest usable count.
    """
    if not 0 < minimum_effect < 1:
        raise ValueError("minimum_effect must be between zero and one")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")
    if min_repeats < 3 or max_repeats < min_repeats:
        raise ValueError("repeat bounds must satisfy 3 <= min_repeats <= max_repeats")
    values = [float(value) for value in measurements[:max_repeats]]
    if len(values) < min_repeats or not all(math.isfinite(value) for value in values):
        raise ValueError(f"at least {min_repeats} finite measurements are required")

    z_value = NormalDist().inv_cdf(0.5 + confidence / 2)
    last: NoiseCalibration | None = None
    for count in range(min_repeats, len(values) + 1):
        prefix = values[:count]
        mean = statistics.fmean(prefix)
        scale = (
            abs(float(reference_scale))
            if reference_scale is not None
            else max(abs(mean), 1e-12)
        )
        target = minimum_effect * scale
        deviation = statistics.stdev(prefix)
        half_width = z_value * deviation / math.sqrt(count)
        last = NoiseCalibration(
            repeats=count,
            mean=mean,
            standard_deviation=deviation,
            ci_half_width=half_width,
            target_half_width=target,
            converged=half_width <= target,
        )
        if last.converged:
            return last
    assert last is not None
    return last


@dataclass(frozen=True)
class PowerAnalysis:
    observed_pairs: int
    paired_standard_deviation: float
    minimum_effect: float
    required_seeds_unbounded: int
    recommended_seeds: int
    underpowered_at_ten: bool
    power: float
    alpha: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def paired_seed_power_analysis(
    paired_differences: Iterable[float],
    *,
    minimum_effect: float = 0.05,
    power: float = 0.80,
    alpha: float = 0.05,
    min_seeds: int = 5,
    max_seeds: int = 10,
) -> PowerAnalysis:
    """Estimate paired-seed sample size without silently exceeding ten seeds."""
    values = [float(value) for value in paired_differences]
    if len(values) < 2 or not all(math.isfinite(value) for value in values):
        raise ValueError("at least two finite paired differences are required")
    if minimum_effect <= 0:
        raise ValueError("minimum_effect must be positive")
    if not 0 < power < 1 or not 0 < alpha < 1:
        raise ValueError("power and alpha must be between zero and one")
    if not 2 <= min_seeds <= max_seeds:
        raise ValueError("seed bounds are invalid")

    deviation = statistics.stdev(values)
    z_alpha = NormalDist().inv_cdf(1 - alpha / 2)
    z_power = NormalDist().inv_cdf(power)
    required = max(2, math.ceil(((z_alpha + z_power) * deviation / minimum_effect) ** 2))
    return PowerAnalysis(
        observed_pairs=len(values),
        paired_standard_deviation=deviation,
        minimum_effect=minimum_effect,
        required_seeds_unbounded=required,
        recommended_seeds=min(max(required, min_seeds), max_seeds),
        underpowered_at_ten=required > max_seeds,
        power=power,
        alpha=alpha,
    )


def cliffs_delta(left: Sequence[float], right: Sequence[float]) -> float:
    """Return the rank-based probability-of-superiority effect size."""

    left_values = [float(value) for value in left]
    right_values = [float(value) for value in right]
    if not left_values or not right_values:
        raise ValueError("Cliff's delta requires two non-empty samples")
    if not all(math.isfinite(value) for value in left_values + right_values):
        raise ValueError("Cliff's delta requires finite samples")
    greater = sum(a > b for a in left_values for b in right_values)
    less = sum(a < b for a in left_values for b in right_values)
    return (greater - less) / (len(left_values) * len(right_values))


def paired_randomization_p_value(differences: Sequence[float]) -> float:
    """Exact two-sided paired sign-flip test for the 5–10 seed protocol."""

    values = [float(value) for value in differences]
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("paired randomization requires finite differences")
    observed = abs(statistics.fmean(values))
    if observed == 0:
        return 1.0
    extreme = 0
    permutation_count = 1 << len(values)
    for mask in range(permutation_count):
        permuted_mean = statistics.fmean(
            value if mask & (1 << index) else -value
            for index, value in enumerate(values)
        )
        if abs(permuted_mean) >= observed - 1e-15:
            extreme += 1
    return extreme / permutation_count


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    """Holm step-down family-wise error correction."""

    values = [float(value) for value in p_values]
    if not all(0.0 <= value <= 1.0 for value in values):
        raise ValueError("p-values must be between zero and one")
    adjusted = [0.0] * len(values)
    running = 0.0
    for rank, (index, value) in enumerate(sorted(enumerate(values), key=lambda item: item[1])):
        running = max(running, min(1.0, (len(values) - rank) * value))
        adjusted[index] = running
    return adjusted


@dataclass(frozen=True)
class PilotGate:
    passed: bool
    provenance_pollution: int
    non_algorithmic_failure_rate: float
    minimum_paired_seeds_per_cell: int
    costs_usable: bool
    deterministic_replay_passed: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_pilot_gate(
    records: Sequence[dict[str, Any]],
    *,
    include_cost_metric: bool,
    deterministic_replay_passed: bool,
) -> PilotGate:
    """Apply the fail-closed promotion gate before expanding the matrix."""
    provenance_pollution = sum(
        1
        for record in records
        if record.get("status") == "completed" and record.get("provenance_valid") is not True
    )
    failed = [record for record in records if record.get("status") != "completed"]
    non_algorithmic = [
        record
        for record in failed
        if record.get("failure_category") not in {"algorithmic", "candidate_invalid"}
    ]
    failure_rate = len(non_algorithmic) / max(len(records), 1)

    completed = {
        (str(record["task"]), str(record["variant"]), int(record["seed"]))
        for record in records
        if record.get("status") == "completed"
    }
    cells = {
        (str(record["task"]), str(record["variant"]))
        for record in records
        if record.get("task") is not None and record.get("variant") is not None
    }
    paired_counts: list[int] = []
    for task, variant in cells:
        full_seeds = {seed for t, name, seed in completed if t == task and name == "full"}
        variant_seeds = {
            seed for t, name, seed in completed if t == task and name == variant
        }
        paired_counts.append(len(full_seeds & variant_seeds))
    minimum_pairs = min(paired_counts, default=0)

    completed_records = [record for record in records if record.get("status") == "completed"]
    costs_usable = (not include_cost_metric) or all(
        record.get("cost_known") is True for record in completed_records
    )
    reasons = []
    if provenance_pollution:
        reasons.append("provenance/replay pollution is non-zero")
    if failure_rate > 0.05:
        reasons.append("non-algorithmic failure rate exceeds 5%")
    if minimum_pairs < 2:
        reasons.append("at least one cell has fewer than two valid paired seeds")
    if not costs_usable:
        reasons.append("cost metric requested with unknown prices")
    if not deterministic_replay_passed:
        reasons.append("deterministic replay invariant did not pass")
    return PilotGate(
        passed=not reasons,
        provenance_pollution=provenance_pollution,
        non_algorithmic_failure_rate=failure_rate,
        minimum_paired_seeds_per_cell=minimum_pairs,
        costs_usable=costs_usable,
        deterministic_replay_passed=deterministic_replay_passed,
        reasons=tuple(reasons),
    )
