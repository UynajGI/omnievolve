"""Executable research runner tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from omnievolve.research.matrix import build_default_matrix
from omnievolve.research.runner import (
    ResearchBenchmarkRunner,
    ResearchRunSettings,
    benchmark_job_from_dict,
)

pytestmark = pytest.mark.unit


def test_benchmark_job_payload_roundtrip():
    original = next(job for job in build_default_matrix() if job.task.name == "sort")

    restored = benchmark_job_from_dict(original.to_dict())

    assert restored == original


def test_run_repetition_records_replay_and_applies_variant(monkeypatch, tmp_path):
    job = next(
        job
        for job in build_default_matrix()
        if job.task.name == "sort" and job.variant.name == "no_slow_loop"
    )
    settings = ResearchRunSettings(
        repo_root=tmp_path,
        results_path=tmp_path / "results.jsonl",
        runs_dir=tmp_path / "runs",
        generations=2,
        population_size=3,
    )
    runner = ResearchBenchmarkRunner(settings, max_concurrency=1)
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("omnievolve.research.runner.subprocess.run", fake_run)
    monkeypatch.setattr(
        runner,
        "_read_run_stats",
        lambda path: {"score": 0.75, "cost_usd": 0.1, "total_tokens": 50},
    )
    monkeypatch.setattr(runner, "_git_commit", lambda: "deadbeef")

    measurement = runner._run_repetition(job, 0)  # noqa: SLF001

    assert measurement["score"] == 0.75
    assert measurement["cost_usd"] == 0.1
    assert any(
        arg == "evolution.self_evolve_enabled=false" for arg in calls[0]
    )
    assert any(arg == "evolution.population_size=3" for arg in calls[0])
    replay = json.loads(
        (tmp_path / "runs" / job.run_id / "rep-0" / "replay.json").read_text(
            encoding="utf-8"
        )
    )
    assert replay["git_commit"] == "deadbeef"
    assert replay["pythonhashseed"] == str(job.seed)


def test_result_append_is_idempotent(tmp_path: Path):
    settings = ResearchRunSettings(
        repo_root=tmp_path,
        results_path=tmp_path / "results.jsonl",
        runs_dir=tmp_path / "runs",
    )
    runner = ResearchBenchmarkRunner(settings)
    record = {
        "run_id": "same",
        "task": "sort",
        "variant": "full",
        "seed": 0,
        "status": "completed",
        "score": 1.0,
    }

    runner._append_result(record)  # noqa: SLF001
    runner._append_result(record)  # noqa: SLF001

    assert settings.results_path.read_text(encoding="utf-8").count("\n") == 1
