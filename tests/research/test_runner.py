"""Executable research runner tests."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from omnievolve.research import runner as runner_module
from omnievolve.research.matrix import build_default_matrix
from omnievolve.research.runner import (
    CalibrationRunSettings,
    EvaluatorNoiseCalibrator,
    ResearchBenchmarkRunner,
    ResearchRunSettings,
    benchmark_job_from_dict,
    build_replay_record,
    validate_calibration_report,
    validate_replay_record,
)

pytestmark = pytest.mark.unit


def _write_deterministic_replay_db(
    path: Path,
    *,
    candidate_id: str,
    score: float = 1.0,
    compute_sec: float = 0.1,
) -> None:
    checkpoint = {
        "schema_version": 2,
        "generation": 1,
        "total_candidates": 1,
        "recent_scores": [score],
        "runtime_state": {
            "best_candidate": [candidate_id, score],
            "budget": {
                "used_tokens": 0,
                "used_cost_usd": 0.0,
                "used_compute_sec": compute_sec,
                "cost_known": True,
                "counter": {"total_compute_sec": compute_sec},
            },
            "jobs": {"lease-id": {"status": "completed"}},
            "python_random_state": [3, [1, 2, 3], None],
        },
    }
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE candidate (
                id TEXT, generation INTEGER, artifact_hash TEXT,
                manifest_hash TEXT, status TEXT
            );
            CREATE TABLE candidate_lineage (
                child_id TEXT, parent_id TEXT, relation_type TEXT,
                parent_order INTEGER, op_detail TEXT
            );
            CREATE TABLE evaluation_run (
                candidate_id TEXT, seed INTEGER, split_name TEXT, attempt INTEGER,
                status TEXT, passed INTEGER, primary_score REAL,
                metrics TEXT, result_hash TEXT
            );
            CREATE TABLE llm_call_ledger (
                id TEXT, agent_role TEXT, model TEXT, input_tokens INTEGER,
                output_tokens INTEGER, total_tokens INTEGER, cost_usd REAL,
                request_hash TEXT, response_hash TEXT, created_at TEXT
            );
            CREATE TABLE experiment (
                id TEXT, started_at TEXT, checkpoint_data TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO candidate VALUES (?, 1, 'artifact', NULL, 'evaluated')",
            (candidate_id,),
        )
        connection.execute(
            """
            INSERT INTO evaluation_run
            VALUES (?, 0, 'default', 1, 'completed', 1, ?, '{}', 'result')
            """,
            (candidate_id, score),
        )
        connection.execute(
            "INSERT INTO experiment VALUES ('exp', 'now', ?)",
            (json.dumps(checkpoint),),
        )


def _add_replay_lineage(
    path: Path,
    *,
    parent_id: str,
    first_child_id: str,
    second_child_id: str,
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO candidate VALUES (?, 0, 'baseline', NULL, 'evaluated')",
            (parent_id,),
        )
        connection.execute(
            "INSERT INTO candidate VALUES (?, 2, 'artifact-2', NULL, 'evaluated')",
            (second_child_id,),
        )
        connection.executemany(
            "INSERT INTO candidate_lineage VALUES (?, ?, 'mutate', 0, '{}')",
            (
                (first_child_id, parent_id),
                (second_child_id, parent_id),
            ),
        )


def test_deterministic_outcome_normalizes_ids_and_timings(tmp_path):
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    changed = tmp_path / "changed.db"
    _write_deterministic_replay_db(
        first, candidate_id="z-child-1", compute_sec=0.1
    )
    _write_deterministic_replay_db(
        second, candidate_id="a-child-1", compute_sec=9.9
    )
    _write_deterministic_replay_db(changed, candidate_id="candidate-c", score=0.5)
    _add_replay_lineage(
        first,
        parent_id="parent-a",
        first_child_id="z-child-1",
        second_child_id="a-child-2",
    )
    _add_replay_lineage(
        second,
        parent_id="parent-b",
        first_child_id="a-child-1",
        second_child_id="z-child-2",
    )
    _add_replay_lineage(
        changed,
        parent_id="parent-c",
        first_child_id="candidate-c",
        second_child_id="child-c-2",
    )

    first_outcome = runner_module._deterministic_outcome(first)
    second_outcome = runner_module._deterministic_outcome(second)
    changed_outcome = runner_module._deterministic_outcome(changed)

    assert first_outcome["sha256"] == second_outcome["sha256"]
    assert first_outcome["sha256"] != changed_outcome["sha256"]
    assert (
        first_outcome["structural_sha256"]
        == changed_outcome["structural_sha256"]
    )


def test_benchmark_job_payload_roundtrip():
    original = next(job for job in build_default_matrix() if job.task.name == "sort")

    restored = benchmark_job_from_dict(original.to_dict())

    assert restored == original


def test_git_provenance_forces_utf8(monkeypatch, tmp_path):
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(stdout="abc\n")

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)
    assert runner_module._git_value(tmp_path, "rev-parse", "HEAD") == "abc"  # noqa: SLF001
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


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
        lambda path, job: {
            "score": 0.75,
            "cost_usd": 0.1,
            "total_tokens": 50,
            "llm_calls": 2,
            "candidate_count": 3,
            "checkpoint_generation": 2,
        },
    )
    monkeypatch.setattr(runner, "_git_commit", lambda: "deadbeef")

    measurement = runner._run_repetition(job, 0)  # noqa: SLF001

    assert measurement["score"] == 0.75
    assert measurement["cost_usd"] == 0.1
    benchmark_call = next(call for call in calls if "omnievolve.cli" in call)
    task_name_index = benchmark_call.index("--task-name")
    assert benchmark_call[task_name_index + 1] == "sort"
    assert any(arg == "evolution.self_evolve_enabled=false" for arg in benchmark_call)
    assert any(arg == "evolution.population_size=3" for arg in benchmark_call)
    assert any(
        arg == f"evolution.eval_repetitions={job.eval_repetitions}"
        for arg in benchmark_call
    )
    replay = json.loads(
        (tmp_path / "runs" / job.run_id / "rep-0" / "replay.json").read_text(
            encoding="utf-8"
        )
    )
    assert replay["schema_version"] == 2
    assert replay["git"]["commit"] == "ok"
    assert replay["pythonhashseed"] == str(job.seed)
    assert replay["replay_class"] == "stochastic_llm"
    assert "observed" in replay


def test_evaluator_calibrator_stops_at_first_converged_prefix(monkeypatch, tmp_path):
    calibrator = EvaluatorNoiseCalibrator(
        CalibrationRunSettings(
            repo_root=tmp_path,
            runs_dir=tmp_path / "runs",
        )
    )
    calls: list[tuple[str, int]] = []

    def fake_measure(task, *, seed, repetition):
        calls.append((task.name, repetition))
        return {
            "score": 0.5,
            "artifact_hash": f"frozen-{task.name}",
            "environment_version_id": "trusted:test",
            "provenance": {"schema_version": 2, "task": task.name},
        }

    monkeypatch.setattr(calibrator, "_measure", fake_measure)

    report = calibrator.run()

    assert report["all_converged"] is True
    assert report["reference_scale"] == 1.0
    assert all(
        task_result["calibration"]["repeats"] == 3
        for task_result in report["tasks"].values()
    )
    assert len(calls) == 9


def test_replay_provenance_detects_changed_inputs(monkeypatch, tmp_path):
    job = next(
        job
        for job in build_default_matrix()
        if job.task.name == "sort" and job.variant.name == "random_search"
    )
    initial = tmp_path / job.task.initial_code
    initial.parent.mkdir(parents=True)
    initial.write_text("def sort_items(xs): return sorted(xs)\n", encoding="utf-8")
    config = tmp_path / "configs" / "sort_optimization.toml"
    config.parent.mkdir(parents=True)
    config.write_text("[evolution]\nmax_generations=2\n", encoding="utf-8")
    evaluator = tmp_path / "examples" / "python_optimization" / "evaluator.py"
    evaluator.parent.mkdir(parents=True, exist_ok=True)
    evaluator.write_text("class SortEvaluator: pass\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    monkeypatch.setattr("omnievolve.research.runner._git_value", lambda *args: "deadbeef")
    monkeypatch.setattr("omnievolve.research.runner._git_diff_hash", lambda *args: "clean")

    record = build_replay_record(
        repo_root=tmp_path,
        job=job,
        repetition=0,
        argv=["python", "-m", "omnievolve.cli"],
        env={**os.environ, "PYTHONHASHSEED": "0"},
        config_path="configs/sort_optimization.toml",
        generations=2,
        population_size=3,
    )

    assert record["replay_class"] == "deterministic_artifacts"
    assert validate_replay_record(record, tmp_path) == []
    stable_provenance = {
        key: record[key]
        for key in (
            "schema_version",
            "cwd",
            "git",
            "runtime",
            "inputs",
            "safe_environment",
        )
    }
    calibration_report = {
        "tasks": {"sort": {"provenance": stable_provenance}}
    }
    assert validate_calibration_report(calibration_report, tmp_path) == []
    initial.write_text("def sort_items(xs): return xs\n", encoding="utf-8")
    assert validate_replay_record(record, tmp_path) == [
        "input fingerprint mismatch: initial_code"
    ]
    assert validate_calibration_report(calibration_report, tmp_path) == [
        "sort: input fingerprint mismatch: initial_code"
    ]


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


def _write_run_db(
    path: Path,
    *,
    candidates: int,
    llm_calls: int,
    generation: int = 2,
) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE evaluation_run (
                primary_score REAL,
                status TEXT
            );
            CREATE TABLE llm_call_ledger (
                cost_usd REAL,
                total_tokens INTEGER
            );
            CREATE TABLE candidate (id TEXT);
            CREATE TABLE experiment (
                id TEXT,
                status TEXT,
                checkpoint_data TEXT,
                started_at TEXT
            );
            INSERT INTO evaluation_run VALUES (0.75, 'completed');
            """
        )
        connection.executemany(
            "INSERT INTO candidate VALUES (?)",
            [(f"candidate-{index}",) for index in range(candidates)],
        )
        connection.executemany(
            "INSERT INTO llm_call_ledger VALUES (0.01, 10)",
            [() for _ in range(llm_calls)],
        )
        connection.execute(
            "INSERT INTO experiment VALUES (?, ?, ?, ?)",
            (
                "experiment",
                "completed",
                json.dumps({"generation": generation}),
                "2026-01-01T00:00:00Z",
            ),
        )


def test_run_integrity_rejects_completed_shell_with_no_evolved_candidate(tmp_path: Path):
    job = next(
        job
        for job in build_default_matrix()
        if job.task.name == "sort" and job.variant.name == "full"
    )
    settings = ResearchRunSettings(
        repo_root=tmp_path,
        results_path=tmp_path / "results.jsonl",
        runs_dir=tmp_path / "runs",
        generations=2,
    )
    runner = ResearchBenchmarkRunner(settings)
    db_path = tmp_path / "run.db"
    _write_run_db(db_path, candidates=1, llm_calls=0)

    with pytest.raises(RuntimeError, match="no evolved candidates"):
        runner._read_run_stats(db_path, job)  # noqa: SLF001


def test_run_integrity_requires_llm_calls_for_llm_variant(tmp_path: Path):
    job = next(
        job
        for job in build_default_matrix()
        if job.task.name == "sort" and job.variant.name == "full"
    )
    settings = ResearchRunSettings(
        repo_root=tmp_path,
        results_path=tmp_path / "results.jsonl",
        runs_dir=tmp_path / "runs",
        generations=2,
    )
    runner = ResearchBenchmarkRunner(settings)
    db_path = tmp_path / "run.db"
    _write_run_db(db_path, candidates=2, llm_calls=0)

    with pytest.raises(RuntimeError, match="no successful LLM calls"):
        runner._read_run_stats(db_path, job)  # noqa: SLF001


def test_run_integrity_allows_llm_free_random_search(tmp_path: Path):
    job = next(
        job
        for job in build_default_matrix()
        if job.task.name == "sort" and job.variant.name == "random_search"
    )
    settings = ResearchRunSettings(
        repo_root=tmp_path,
        results_path=tmp_path / "results.jsonl",
        runs_dir=tmp_path / "runs",
        generations=2,
    )
    runner = ResearchBenchmarkRunner(settings)
    db_path = tmp_path / "run.db"
    _write_run_db(db_path, candidates=2, llm_calls=0)

    stats = runner._read_run_stats(db_path, job)  # noqa: SLF001

    assert stats["score"] == 0.75
    assert stats["candidate_count"] == 2
