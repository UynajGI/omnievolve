from __future__ import annotations

import json

import pytest

from omnievolve.research.matrix import (
    build_default_matrix,
    build_operator_portfolio_matrix,
    build_pilot_matrix,
    build_qd_archive_matrix,
    build_reference_credit_matrix,
    load_calibration_repetitions,
    summarize_results,
    write_manifest,
)


def test_pilot_matrix_is_fixed_45_run_paired_protocol():
    jobs = build_pilot_matrix()

    assert len(jobs) == 45
    assert {job.task.name for job in jobs} == {"sort", "nqueens", "circle_packing"}
    assert {job.seed for job in jobs} == {0, 1, 2}
    assert {job.variant.name for job in jobs} == {
        "full",
        "random_search",
        "single_agent",
        "no_novelty",
        "no_slow_loop",
    }
    full = next(job for job in jobs if job.variant.name == "full")
    no_novelty = next(job for job in jobs if job.variant.name == "no_novelty")
    no_slow = next(job for job in jobs if job.variant.name == "no_slow_loop")
    assert full.variant.config_overrides["evolution.self_evolve_enabled"] is True
    assert full.variant.config_overrides["meta_evolution.enabled"] is True
    assert (
        full.variant.config_overrides[
            "meta_evolution.meta_canary_budget_ratio"
        ]
        == 0.5
    )
    assert (
        full.variant.config_overrides["self_evaluator.roi_warn_threshold"]
        > 1_000_000
    )
    assert (
        no_novelty.variant.config_overrides["evolution.self_evolve_enabled"]
        is True
    )
    assert (
        no_novelty.variant.config_overrides["self_evaluator.roi_warn_threshold"]
        > 1_000_000
    )
    assert no_slow.variant.config_overrides["evolution.self_evolve_enabled"] is False
    assert {job.eval_repetitions for job in jobs} == {3}


def test_pilot_matrix_uses_per_task_calibrated_evaluator_repetitions():
    jobs = build_pilot_matrix(
        eval_repetitions={
            "sort": 3,
            "nqueens": 5,
            "circle_packing": 10,
        }
    )

    assert {
        task: {job.eval_repetitions for job in jobs if job.task.name == task}
        for task in ("sort", "nqueens", "circle_packing")
    } == {
        "sort": {3},
        "nqueens": {5},
        "circle_packing": {10},
    }
    assert len({job.run_id for job in jobs}) == len(jobs)


def test_load_calibration_repetitions_requires_audited_task_entries(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps(
            {
                "tasks": {
                    "sort": {"calibration": {"repeats": 3}},
                    "nqueens": {"calibration": {"repeats": 5}},
                    "circle_packing": {"calibration": {"repeats": 10}},
                }
            }
        ),
        encoding="utf-8",
    )

    assert load_calibration_repetitions(
        path,
        required_tasks=("sort", "nqueens", "circle_packing"),
    ) == {"sort": 3, "nqueens": 5, "circle_packing": 10}


def test_default_matrix_has_nine_tasks_five_variants_and_five_seeds(tmp_path):
    jobs = build_default_matrix()
    assert len(jobs) == 9 * 5 * 5
    assert len({job.run_id for job in jobs}) == len(jobs)
    assert all(job.task.initial_code.endswith("initial_code.py") for job in jobs)

    path = write_manifest(jobs, tmp_path / "matrix.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["task_count"] == 9
    assert payload["run_count"] == 225
    assert payload["eval_repetitions"]["sort"] == [3]


def test_reference_credit_ablation_is_separate_and_paired():
    jobs = build_reference_credit_matrix()

    assert len(jobs) == 90
    assert {job.variant.name for job in jobs} == {
        "reference_credit_on",
        "reference_credit_off",
    }
    assert all(
        "evolution.reference_credit_enabled" in job.variant.config_overrides
        for job in jobs
    )


def test_operator_portfolio_ablation_is_separate_and_paired():
    jobs = build_operator_portfolio_matrix()

    assert len(jobs) == 9 * 3 * 5
    assert {job.protocol for job in jobs} == {"operator_portfolio"}
    assert {job.variant.name for job in jobs} == {
        "operator_fixed",
        "operator_ucb",
        "operator_thompson",
    }
    assert all(
        job.variant.config_overrides["evolution.qd_archive_enabled"] is False
        for job in jobs
    )


def test_qd_archive_ablation_is_separate_and_does_not_enable_operator_bandit():
    jobs = build_qd_archive_matrix()

    assert len(jobs) == 9 * 2 * 5
    assert {job.protocol for job in jobs} == {"qd_archive"}
    assert {job.variant.name for job in jobs} == {"qd_off", "qd_on"}
    assert all(
        job.variant.config_overrides["evolution.operator_portfolio_enabled"] is False
        for job in jobs
    )


def test_matrix_requires_five_to_ten_unique_seeds():
    with pytest.raises(ValueError, match="5 to 10"):
        build_default_matrix(seeds=(1, 2))
    with pytest.raises(ValueError, match="unique"):
        build_default_matrix(seeds=(1, 1, 2, 3, 4))


def test_result_summary_includes_confidence_interval():
    records = [
        {"task": "sort", "variant": "full", "status": "completed", "score": value}
        for value in (0.5, 0.6, 0.7, 0.8, 0.9)
    ]
    records.extend(
        {"task": "sort", "variant": "no_novelty", "status": "completed", "score": value}
        for value in (0.2, 0.25, 0.3, 0.35, 0.4)
    )
    report = summarize_results(records)
    score = report["cells"][0]["score"]
    assert score["count"] == 5
    assert score["ci_low"] <= score["median"] <= score["ci_high"]
    assert report["comparisons"][0]["decision"] == "regression"


def test_slow_loop_decision_uses_paired_confidence_interval():
    records = []
    for seed in range(5):
        records.extend(
            [
                {
                    "task": "sort",
                    "variant": "full",
                    "seed": seed,
                    "status": "completed",
                    "score": 0.9,
                },
                {
                    "task": "sort",
                    "variant": "no_slow_loop",
                    "seed": seed,
                    "status": "completed",
                    "score": 0.5,
                },
            ]
        )

    decision = summarize_results(records)["slow_loop_decision"]

    assert decision["decision"] == "keep"
    assert decision["paired_runs"] == 5


def test_independent_ablation_summary_is_protocol_scoped_and_holm_corrected():
    records = []
    for seed in range(5):
        for variant, score in (
            ("operator_fixed", 0.5),
            ("operator_ucb", 0.7),
            ("operator_thompson", 0.6),
        ):
            records.append(
                {
                    "protocol": "operator_portfolio",
                    "task": "sort",
                    "variant": variant,
                    "seed": seed,
                    "status": "completed",
                    "score": score,
                    "frontier_auc": score,
                }
            )

    report = summarize_results(records, include_cost_metric=False)

    assert {cell["protocol"] for cell in report["cells"]} == {
        "operator_portfolio"
    }
    assert {comparison["relative_to"] for comparison in report["comparisons"]} == {
        "operator_fixed"
    }
    assert all(
        0.0 <= comparison["holm_adjusted_p"] <= 1.0
        for comparison in report["comparisons"]
    )
    assert all("cliffs_delta" in comparison for comparison in report["comparisons"])


def test_pilot_summary_applies_gate_and_recommends_formal_seed_count():
    records = []
    for variant in (
        "full",
        "random_search",
        "single_agent",
        "no_novelty",
        "no_slow_loop",
    ):
        for seed in (0, 1, 2):
            records.append(
                {
                    "protocol": "pilot",
                    "task": "sort",
                    "variant": variant,
                    "seed": seed,
                    "status": "completed",
                    "score": 0.9 if variant == "full" else 0.5,
                    "frontier_auc": 0.9 if variant == "full" else 0.5,
                    "provenance_valid": True,
                    "cost_known": False,
                }
            )

    report = summarize_results(
        records,
        include_cost_metric=False,
        deterministic_replay_passed=True,
    )

    assert report["pilot_gate"]["passed"] is True
    assert report["pilot_gate"]["minimum_paired_seeds_per_cell"] == 3
    assert report["formal_seed_recommendation"]["recommended_seeds"] == 5
    assert report["formal_seed_recommendation"]["underpowered_at_ten"] is False


def test_slow_loop_decision_refuses_unpaired_claim():
    report = summarize_results(
        [
            {
                "task": "sort",
                "variant": "full",
                "seed": 0,
                "status": "completed",
                "score": 1.0,
            }
        ]
    )

    assert report["slow_loop_decision"]["decision"] == "insufficient_data"
