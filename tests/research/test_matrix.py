from __future__ import annotations

import json

import pytest

from omnievolve.research.matrix import build_default_matrix, summarize_results, write_manifest


def test_default_matrix_has_nine_tasks_five_variants_and_five_seeds(tmp_path):
    jobs = build_default_matrix()
    assert len(jobs) == 9 * 5 * 5
    assert len({job.run_id for job in jobs}) == len(jobs)
    assert all(job.task.initial_code.endswith("initial_code.py") for job in jobs)

    path = write_manifest(jobs, tmp_path / "matrix.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["task_count"] == 9
    assert payload["run_count"] == 225


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
