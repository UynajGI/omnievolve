from __future__ import annotations

import pytest

from omnievolve.research.statistics import (
    assess_pilot_gate,
    calibrate_evaluator_noise,
    cliffs_delta,
    holm_adjust,
    paired_randomization_p_value,
    paired_seed_power_analysis,
)


def test_noise_calibration_uses_first_converged_prefix():
    result = calibrate_evaluator_noise([1.0, 1.0, 1.0, 1.0])

    assert result.repeats == 3
    assert result.converged is True
    assert result.ci_half_width == 0.0


def test_noise_calibration_caps_at_ten_and_reports_nonconvergence():
    result = calibrate_evaluator_noise(
        [0.0, 2.0] * 5,
        reference_scale=1.0,
        minimum_effect=0.05,
    )

    assert result.repeats == 10
    assert result.converged is False


def test_paired_power_analysis_never_silently_expands_past_ten():
    result = paired_seed_power_analysis([0.4, -0.3, 0.5], minimum_effect=0.05)

    assert result.recommended_seeds == 10
    assert result.required_seeds_unbounded > 10
    assert result.underpowered_at_ten is True


def test_pilot_gate_requires_replay_pairs_and_known_cost():
    records = [
        {
            "task": task,
            "variant": variant,
            "seed": seed,
            "status": "completed",
            "provenance_valid": True,
            "cost_known": True,
        }
        for task in ("sort", "nqueens", "circle_packing")
        for variant in (
            "full",
            "random_search",
            "single_agent",
            "no_novelty",
            "no_slow_loop",
        )
        for seed in (0, 1)
    ]

    result = assess_pilot_gate(
        records,
        include_cost_metric=True,
        deterministic_replay_passed=True,
    )

    assert result.passed is True
    assert result.minimum_paired_seeds_per_cell == 2

    records[0]["cost_known"] = False
    failed = assess_pilot_gate(
        records,
        include_cost_metric=True,
        deterministic_replay_passed=True,
    )
    assert failed.passed is False
    assert "unknown prices" in " ".join(failed.reasons)

    incomplete = [
        record
        for record in records
        if not (
            record["task"] == "sort"
            and record["variant"] == "random_search"
            and record["seed"] == 1
        )
    ]
    incomplete[0]["cost_known"] = True
    failed = assess_pilot_gate(
        incomplete,
        include_cost_metric=True,
        deterministic_replay_passed=True,
    )
    assert failed.passed is False
    assert failed.minimum_paired_seeds_per_cell == 1


def test_noise_calibration_rejects_too_few_measurements():
    with pytest.raises(ValueError, match="at least 3"):
        calibrate_evaluator_noise([1.0, 1.0])


def test_rank_effect_randomization_and_holm_are_deterministic():
    assert cliffs_delta([3.0, 4.0], [1.0, 2.0]) == 1.0
    assert paired_randomization_p_value([1.0] * 5) == pytest.approx(2 / 32)
    adjusted = holm_adjust([0.01, 0.04, 0.03])
    assert adjusted == pytest.approx([0.03, 0.06, 0.06])
