from __future__ import annotations

import json

import pytest

from omnievolve.research.matrix import (
    build_default_matrix,
    build_reference_credit_matrix,
    summarize_results,
    write_manifest,
)


def test_default_matrix_has_nine_tasks_five_variants_and_five_seeds(tmp_path):
    jobs = build_default_matrix()
    assert len(jobs) == 9 * 5 * 5
    assert len({job.run_id for job in jobs}) == len(jobs)
    assert all(job.task.initial_code.endswith("initial_code.py") for job in jobs)

    path = write_manifest(jobs, tmp_path / "matrix.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["task_count"] == 9
    assert payload["run_count"] == 225


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
