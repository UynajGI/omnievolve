"""Executable, resumable research benchmark queue."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omnievolve.research.matrix import (
    PILOT_TASKS,
    AblationVariant,
    BenchmarkJob,
    BenchmarkTask,
    enqueue_matrix,
)
from omnievolve.research.statistics import calibrate_evaluator_noise
from omnievolve.storage.db import Database
from omnievolve.storage.job_store import Job, JobStore
from omnievolve.storage.local_executor import (
    ExecutorReport,
    LocalTaskExecutor,
    PermanentJobError,
)
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.repositories.experiment_repo import ExperimentRepository

TASK_CONFIGS = {
    "contract_cheaper": "configs/contract_cheaper.toml",
    "heilbronn": "configs/heilbronn.toml",
    "lennard_jones": "configs/lennard_jones.toml",
    "matmul": "configs/matmul.toml",
    "nqueens": "configs/nqueens.toml",
    "occam_circuit": "configs/occam_circuit.toml",
    "orbit_q": "configs/orbit_q.toml",
    "sort": "configs/sort_optimization.toml",
}
_SLOW_LOOP_REQUIRED_VARIANTS = frozenset({"full", "no_novelty"})

_SAFE_REPLAY_ENV = (
    "OMNIEVOLVE_LLM_MODEL",
    "OMNIEVOLVE_LLM_API_BASE",
    "OPENAI_BASE_URL",
)


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_value(repo_root: Path, *args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _git_diff_hash(repo_root: Path) -> str | None:
    diff = _git_value(repo_root, "diff", "--binary", "HEAD")
    if diff is None:
        return None
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


def _replay_input_paths(repo_root: Path, job: BenchmarkJob, config_path: str) -> dict[str, Path]:
    module_name = job.task.evaluator.split(":", 1)[0]
    evaluator_path = repo_root / (module_name.replace(".", "/") + ".py")
    paths = {
        "initial_code": repo_root / job.task.initial_code,
        "task_config": repo_root / config_path,
        "evaluator": evaluator_path,
        "pyproject": repo_root / "pyproject.toml",
        "lockfile": repo_root / "uv.lock",
        # Fingerprint only: secret values are never serialized.
        "local_environment": repo_root / ".local.env",
    }
    return {name: path.resolve() for name, path in paths.items()}


def build_replay_record(
    *,
    repo_root: Path,
    job: BenchmarkJob,
    repetition: int,
    argv: list[str],
    env: dict[str, str],
    config_path: str,
    generations: int,
    population_size: int,
) -> dict[str, Any]:
    """Capture enough provenance to validate or rerun a research repetition."""
    inputs = {
        name: {"path": str(path), "sha256": _sha256_file(path)}
        for name, path in _replay_input_paths(repo_root, job, config_path).items()
    }
    artifact_deterministic = job.variant.name == "random_search"
    return {
        "schema_version": 2,
        "run_id": job.run_id,
        "repetition": repetition,
        "job": job.to_dict(),
        "argv": argv,
        "cwd": str(repo_root.resolve()),
        "pythonhashseed": env["PYTHONHASHSEED"],
        "git": {
            "commit": _git_value(repo_root, "rev-parse", "HEAD"),
            "diff_sha256": _git_diff_hash(repo_root),
        },
        "runtime": {
            "python_executable": str(Path(sys.executable).resolve()),
            "python_version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "inputs": inputs,
        "safe_environment": {key: env.get(key) for key in _SAFE_REPLAY_ENV},
        "settings": {
            "generations": generations,
            "population_size": population_size,
        },
        "replay_class": (
            "deterministic_artifacts"
            if artifact_deterministic
            else "stochastic_llm"
        ),
        "determinism_note": (
            "Mutation artifacts and lineage must reproduce exactly; runtime "
            "benchmark measurements are compared separately because they are noisy."
            if artifact_deterministic
            else "Inputs and non-LLM stages are reproducible; provider output may vary."
        ),
    }


def validate_replay_record(record: dict[str, Any], repo_root: Path) -> list[str]:
    """Return strict provenance mismatches; an empty list is replay-ready."""
    issues: list[str] = []
    if record.get("schema_version") != 2:
        return ["unsupported replay schema; expected version 2"]
    expected_root = Path(str(record.get("cwd", ""))).resolve()
    if expected_root != repo_root.resolve():
        issues.append(f"repository root mismatch: {repo_root.resolve()} != {expected_root}")
    git = record.get("git", {})
    if _git_value(repo_root, "rev-parse", "HEAD") != git.get("commit"):
        issues.append("git commit mismatch")
    if _git_diff_hash(repo_root) != git.get("diff_sha256"):
        issues.append("git working-tree diff mismatch")
    runtime = record.get("runtime", {})
    if platform.python_version() != runtime.get("python_version"):
        issues.append("python version mismatch")
    if platform.python_implementation() != runtime.get("implementation"):
        issues.append("python implementation mismatch")
    for name, metadata in record.get("inputs", {}).items():
        path = Path(str(metadata.get("path", "")))
        if _sha256_file(path) != metadata.get("sha256"):
            issues.append(f"input fingerprint mismatch: {name}")
    for key, expected in record.get("safe_environment", {}).items():
        if os.environ.get(key) != expected:
            issues.append(f"safe environment mismatch: {key}")
    return issues


def _setting_path(argv: list[str], key: str) -> Path:
    prefix = f"{key}="
    for value in argv:
        if value.startswith(prefix):
            return Path(json.loads(value[len(prefix) :]))
    raise RuntimeError(f"replay command is missing required setting {key}")


def _deterministic_outcome(db_path: Path) -> dict[str, Any]:
    """Return a timing-independent, ID-normalized replay outcome."""
    if not db_path.is_file():
        raise RuntimeError(f"replay database was not created: {db_path}")
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        candidates = connection.execute(
            """
            SELECT id, generation, artifact_hash, manifest_hash, status
            FROM candidate ORDER BY generation, artifact_hash, id
            """
        ).fetchall()
        id_map = {
            row["id"]: f"{row['generation']}:{row['artifact_hash']}:{row['manifest_hash'] or ''}"
            for row in candidates
        }

        def normalize(value: Any) -> Any:
            if isinstance(value, str):
                return id_map.get(value, value)
            if isinstance(value, list):
                return [normalize(item) for item in value]
            if isinstance(value, dict):
                return {
                    key: normalize(item)
                    for key, item in sorted(value.items())
                    if key not in {"used_compute_sec", "total_compute_sec"}
                }
            return value

        lineage = connection.execute(
            """
            SELECT child_id, parent_id, relation_type, parent_order, op_detail
            FROM candidate_lineage
            ORDER BY child_id, parent_order, parent_id
            """
        ).fetchall()
        evaluations = connection.execute(
            """
            SELECT c.id AS candidate_id, er.seed, er.split_name, er.attempt,
                   er.status, er.passed, er.primary_score, er.metrics, er.result_hash
            FROM evaluation_run er
            JOIN candidate c ON c.id = er.candidate_id
            ORDER BY c.generation, c.artifact_hash, er.seed, er.split_name, er.attempt
            """
        ).fetchall()
        llm_calls = connection.execute(
            """
            SELECT agent_role, model, input_tokens, output_tokens, total_tokens,
                   cost_usd, request_hash, response_hash
            FROM llm_call_ledger ORDER BY created_at, id
            """
        ).fetchall()
        checkpoint_row = connection.execute(
            """
            SELECT checkpoint_data FROM experiment
            ORDER BY started_at DESC, id DESC LIMIT 1
            """
        ).fetchone()

    checkpoint = json.loads(checkpoint_row["checkpoint_data"] or "{}") if checkpoint_row else {}
    checkpoint.pop("failed_directions", None)
    runtime = checkpoint.get("runtime_state", {})
    if isinstance(runtime, dict):
        # Job lease identifiers and wall/compute timings are operational
        # provenance, not deterministic search state.
        runtime.pop("jobs", None)
    outcome = {
        "candidates": [
            (
                row["generation"],
                row["artifact_hash"],
                row["manifest_hash"],
                row["status"],
            )
            for row in candidates
        ],
        "lineage": [
            (
                id_map.get(row["child_id"], row["child_id"]),
                id_map.get(row["parent_id"], row["parent_id"]),
                row["relation_type"],
                row["parent_order"],
                normalize(json.loads(row["op_detail"] or "{}")),
            )
            for row in lineage
        ],
        "evaluations": [
            (
                id_map.get(row["candidate_id"], row["candidate_id"]),
                row["seed"],
                row["split_name"],
                row["attempt"],
                row["status"],
                row["passed"],
                row["primary_score"],
                normalize(json.loads(row["metrics"] or "{}")),
                row["result_hash"],
            )
            for row in evaluations
        ],
        "llm_calls": [tuple(row) for row in llm_calls],
        "checkpoint": normalize(checkpoint),
    }
    payload = json.dumps(outcome, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    structural = {
        # Candidate pass/fail is evaluator output and can flip at a timing
        # threshold even when mutation produced byte-identical artifacts.
        "candidates": [row[:3] for row in outcome["candidates"]],
        "lineage": outcome["lineage"],
        "llm_calls": outcome["llm_calls"],
        "checkpoint": {
            "schema_version": checkpoint.get("schema_version"),
            "generation": checkpoint.get("generation"),
            "total_candidates": checkpoint.get("total_candidates"),
            "search_policy": runtime.get("search_policy")
            if isinstance(runtime, dict)
            else None,
            "selection_mode": runtime.get("selection_mode")
            if isinstance(runtime, dict)
            else None,
            "python_random_state": runtime.get("python_random_state")
            if isinstance(runtime, dict)
            else None,
        },
    }
    structural_payload = json.dumps(
        structural,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return {
        "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "structural_sha256": hashlib.sha256(
            structural_payload.encode("utf-8")
        ).hexdigest(),
        "outcome": outcome,
    }


def strict_replay(
    runs_dir: str | Path,
    run_id: str,
    *,
    repetition: int = 0,
    execute: bool = False,
    timeout_sec: float = 3600.0,
) -> dict[str, Any]:
    """Validate provenance and optionally rerun into a fresh isolated directory."""
    replay_path = Path(runs_dir) / run_id / f"rep-{repetition}" / "replay.json"
    if not replay_path.is_file():
        raise FileNotFoundError(f"replay record not found: {replay_path}")
    record = json.loads(replay_path.read_text(encoding="utf-8"))
    repo_root = Path(str(record.get("cwd", "")))
    issues = validate_replay_record(record, repo_root)
    if issues:
        raise RuntimeError("strict replay validation failed: " + "; ".join(issues))
    result: dict[str, Any] = {
        "validated": True,
        "executed": False,
        "replay_class": record["replay_class"],
        "determinism_note": record["determinism_note"],
    }
    if not execute:
        return result

    replay_dir = replay_path.parent / f"strict-replay-{time.time_ns()}"
    replay_dir.mkdir(parents=True)
    replacements = {
        "storage.db_path": replay_dir / "run.db",
        "storage.artifact_dir": replay_dir / "artifacts",
        "storage.vector_dir": replay_dir / "vectors",
        "storage.export_dir": replay_dir / "exports",
    }
    argv = list(record["argv"])
    for index, arg in enumerate(argv):
        for key, path in replacements.items():
            if arg.startswith(f"{key}="):
                argv[index] = f"{key}={json.dumps(str(path.resolve()))}"
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = str(record["pythonhashseed"])
    completed = subprocess.run(
        argv,
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
        check=False,
    )
    (replay_dir / "stdout.log").write_text(completed.stdout, encoding="utf-8")
    (replay_dir / "stderr.log").write_text(completed.stderr, encoding="utf-8")
    result.update(
        {
            "executed": True,
            "returncode": completed.returncode,
            "output_dir": str(replay_dir),
        }
    )
    if completed.returncode != 0:
        raise RuntimeError(f"strict replay command failed with exit code {completed.returncode}")
    if record["replay_class"] in {"deterministic", "deterministic_artifacts"}:
        original_db = _setting_path(list(record["argv"]), "storage.db_path")
        replay_db = replacements["storage.db_path"]
        original = _deterministic_outcome(original_db)
        replayed = _deterministic_outcome(replay_db)
        exact = original["sha256"] == replayed["sha256"]
        structural = (
            original["structural_sha256"] == replayed["structural_sha256"]
        )
        result.update(
            {
                "deterministic_equivalent": exact,
                "deterministic_artifacts_equivalent": structural,
                "original_outcome_sha256": original["sha256"],
                "replay_outcome_sha256": replayed["sha256"],
                "original_structural_sha256": original["structural_sha256"],
                "replay_structural_sha256": replayed["structural_sha256"],
            }
        )
        required_equivalent = (
            exact if record["replay_class"] == "deterministic" else structural
        )
        if not required_equivalent:
            raise RuntimeError(
                "strict replay outcome mismatch: "
                f"{original['structural_sha256']} != "
                f"{replayed['structural_sha256']}"
            )
    return result


@dataclass(frozen=True)
class ResearchRunSettings:
    repo_root: Path
    results_path: Path
    runs_dir: Path
    generations: int = 5
    population_size: int = 4
    timeout_sec: float = 3600.0
    trusted: bool = True


@dataclass(frozen=True)
class CalibrationRunSettings:
    """Execution settings for frozen-candidate evaluator noise calibration."""

    repo_root: Path
    runs_dir: Path
    timeout_sec: float = 3600.0
    trusted: bool = True


class EvaluatorNoiseCalibrator:
    """Measure evaluator noise without invoking mutation or an LLM."""

    def __init__(self, settings: CalibrationRunSettings) -> None:
        self._settings = settings
        settings.runs_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        *,
        tasks: tuple[BenchmarkTask, ...] = PILOT_TASKS,
        seed: int = 0,
        minimum_effect: float = 0.05,
        confidence: float = 0.95,
        min_repeats: int = 3,
        max_repeats: int = 10,
    ) -> dict[str, Any]:
        """Calibrate each task sequentially and stop once its CI is narrow enough."""
        if seed < 0:
            raise ValueError("calibration seed must be non-negative")
        task_results: dict[str, Any] = {}
        for task in tasks:
            measurements: list[float] = []
            artifact_hashes: list[str] = []
            environment_ids: list[str] = []
            provenance_records: list[dict[str, Any]] = []
            calibration = None
            for repetition in range(max_repeats):
                observed = self._measure(task, seed=seed, repetition=repetition)
                measurements.append(float(observed["score"]))
                artifact_hashes.append(str(observed["artifact_hash"]))
                environment_ids.append(str(observed["environment_version_id"]))
                provenance_records.append(dict(observed["provenance"]))
                if len(measurements) < min_repeats:
                    continue
                calibration = calibrate_evaluator_noise(
                    measurements,
                    reference_scale=1.0,
                    minimum_effect=minimum_effect,
                    confidence=confidence,
                    min_repeats=min_repeats,
                    max_repeats=max_repeats,
                )
                if calibration.converged:
                    break
            if calibration is None:
                raise RuntimeError(
                    f"task {task.name!r} produced too few calibration measurements"
                )
            if len(set(artifact_hashes)) != 1:
                raise RuntimeError(
                    f"task {task.name!r} calibration did not keep the candidate frozen"
                )
            provenance_fingerprints = {
                json.dumps(record, sort_keys=True) for record in provenance_records
            }
            if len(provenance_fingerprints) != 1:
                raise RuntimeError(
                    f"task {task.name!r} calibration provenance changed between repeats"
                )
            task_results[task.name] = {
                "measurements": measurements,
                "artifact_hash": artifact_hashes[0],
                "environment_version_ids": environment_ids,
                "provenance": provenance_records[0],
                "calibration": calibration.to_dict(),
            }
        return {
            "schema_version": 1,
            "protocol": "frozen_candidate_evaluator_noise",
            "seed": seed,
            "minimum_effect": minimum_effect,
            "reference_scale": 1.0,
            "confidence": confidence,
            "min_repeats": min_repeats,
            "max_repeats": max_repeats,
            "all_converged": all(
                bool(result["calibration"]["converged"])
                for result in task_results.values()
            ),
            "tasks": task_results,
        }

    def _measure(
        self,
        task: BenchmarkTask,
        *,
        seed: int,
        repetition: int,
    ) -> dict[str, Any]:
        run_id = hashlib.sha256(
            f"calibration-v1:{task.name}:{seed}".encode()
        ).hexdigest()[:16]
        calibration_variant = AblationVariant(
            name="evaluator_noise_calibration",
            description="Frozen initial candidate with no mutation or LLM calls.",
            config_overrides={
                "evolution.random_search_mode": True,
                "evolution.self_evolve_enabled": False,
            },
        )
        job = BenchmarkJob(
            run_id=run_id,
            task=task,
            variant=calibration_variant,
            seed=seed,
            repetitions=1,
            eval_repetitions=1,
            protocol="calibration",
        )
        run_dir = (
            self._settings.runs_dir
            / "calibration"
            / task.name
            / f"rep-{repetition}"
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        db_path = run_dir / "run.db"
        artifact_dir = run_dir / "artifacts"
        vector_dir = run_dir / "vectors"
        export_dir = run_dir / "exports"
        config_path = TASK_CONFIGS.get(task.name, "omnievolve.toml")
        args = [
            sys.executable,
            "-m",
            "omnievolve.cli",
            "run",
            task.initial_code,
            "--task-name",
            task.name,
            "--config",
            config_path,
            "--evaluator",
            task.evaluator,
            "--gens",
            "0",
            "--seed",
            str(seed),
            "--no-self-evolve",
            "--set",
            "evolution.population_size=1",
            "--set",
            "evolution.eval_repetitions=1",
            "--set",
            "evolution.random_search_mode=true",
            "--set",
            f"storage.db_path={json.dumps(str(db_path.resolve()))}",
            "--set",
            f"storage.artifact_dir={json.dumps(str(artifact_dir.resolve()))}",
            "--set",
            f"storage.vector_dir={json.dumps(str(vector_dir.resolve()))}",
            "--set",
            f"storage.export_dir={json.dumps(str(export_dir.resolve()))}",
            "--set",
            "storage.code_backend=cas",
            "--set",
            'embedding.code.provider="fake"',
            "--set",
            "embedding.code.dimension=128",
            "--set",
            'embedding.thought.provider="fake"',
            "--set",
            "embedding.thought.dimension=128",
        ]
        if self._settings.trusted:
            args.append("--trusted")
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = str(seed)
        replay = build_replay_record(
            repo_root=self._settings.repo_root,
            job=job,
            repetition=repetition,
            argv=args,
            env=env,
            config_path=config_path,
            generations=0,
            population_size=1,
        )
        replay_path = run_dir / "replay.json"
        if replay_path.exists() and db_path.exists():
            stored_replay = json.loads(replay_path.read_text(encoding="utf-8"))
            if (
                stored_replay.get("returncode") == 0
                and stored_replay.get("argv") == replay["argv"]
                and stored_replay.get("inputs") == replay["inputs"]
                and not validate_replay_record(
                    stored_replay, self._settings.repo_root
                )
            ):
                observed = self._read_measurement(db_path)
                observed["wall_sec"] = float(
                    stored_replay.get("observed", {}).get("wall_sec", 0.0)
                )
                observed["provenance_valid"] = True
                observed["provenance"] = self._stable_provenance(stored_replay)
                return observed
            raise RuntimeError(
                f"calibration slot {run_dir} exists but cannot be safely resumed; "
                "use a different --runs-dir"
            )
        replay_path.write_text(
            json.dumps(replay, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        started = time.monotonic()
        try:
            completed = subprocess.run(
                args,
                cwd=self._settings.repo_root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._settings.timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"calibration timed out after {self._settings.timeout_sec}s"
            ) from exc
        (run_dir / "stdout.log").write_text(completed.stdout, encoding="utf-8")
        (run_dir / "stderr.log").write_text(completed.stderr, encoding="utf-8")
        replay["returncode"] = completed.returncode
        if completed.returncode != 0:
            tail = "\n".join(completed.stderr.splitlines()[-20:])
            replay_path.write_text(
                json.dumps(replay, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            raise RuntimeError(
                f"calibration command failed with exit code "
                f"{completed.returncode}: {tail}"
            )
        provenance_errors = validate_replay_record(replay, self._settings.repo_root)
        if provenance_errors:
            raise RuntimeError(
                "calibration provenance changed during run: "
                + "; ".join(provenance_errors)
            )
        observed = self._read_measurement(db_path)
        observed["wall_sec"] = time.monotonic() - started
        observed["provenance_valid"] = True
        observed["provenance"] = self._stable_provenance(replay)
        replay["observed"] = observed
        replay_path.write_text(
            json.dumps(replay, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return observed

    @staticmethod
    def _stable_provenance(replay: dict[str, Any]) -> dict[str, Any]:
        """Keep the replay fields that must remain stable across repetitions."""
        return {
            key: replay[key]
            for key in (
                "schema_version",
                "cwd",
                "git",
                "runtime",
                "inputs",
                "safe_environment",
            )
        }

    @staticmethod
    def _read_measurement(db_path: Path) -> dict[str, Any]:
        if not db_path.exists():
            raise RuntimeError(f"calibration database was not created: {db_path}")
        with sqlite3.connect(db_path) as connection:
            experiment = connection.execute(
                """
                SELECT status
                FROM experiment
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
            measurement = connection.execute(
                """
                SELECT er.primary_score, c.artifact_hash,
                       er.environment_version_id, er.result_hash
                FROM evaluation_run er
                JOIN candidate c ON c.id = er.candidate_id
                WHERE c.generation = 0
                  AND er.status = 'completed'
                  AND er.primary_score IS NOT NULL
                ORDER BY er.id DESC
                LIMIT 1
                """
            ).fetchone()
            candidate_count = int(
                connection.execute("SELECT COUNT(*) FROM candidate").fetchone()[0]
            )
            llm_calls = int(
                connection.execute("SELECT COUNT(*) FROM llm_call_ledger").fetchone()[0]
            )
        if experiment is None or experiment[0] != "completed":
            raise RuntimeError("calibration experiment did not complete")
        if measurement is None:
            raise RuntimeError("calibration produced no completed initial evaluation")
        if candidate_count != 1:
            raise RuntimeError(
                "calibration must evaluate exactly one frozen candidate"
            )
        if llm_calls != 0:
            raise RuntimeError("calibration unexpectedly invoked an LLM")
        return {
            "score": float(measurement[0]),
            "artifact_hash": str(measurement[1]),
            "environment_version_id": str(measurement[2]),
            "result_hash": str(measurement[3]) if measurement[3] is not None else None,
            "candidate_count": candidate_count,
            "llm_calls": llm_calls,
        }


def validate_calibration_report(
    payload: dict[str, Any],
    repo_root: Path,
) -> list[str]:
    """Validate every task calibration against the current source/runtime state."""
    issues: list[str] = []
    task_payloads = payload.get("tasks")
    if not isinstance(task_payloads, dict) or not task_payloads:
        return ["calibration report has no task results"]
    for task_name, task_result in task_payloads.items():
        provenance = (
            task_result.get("provenance")
            if isinstance(task_result, dict)
            else None
        )
        if not isinstance(provenance, dict):
            issues.append(f"{task_name}: missing calibration provenance")
            continue
        task_issues = validate_replay_record(provenance, repo_root)
        issues.extend(f"{task_name}: {issue}" for issue in task_issues)
    return issues


def benchmark_job_from_dict(payload: dict[str, Any]) -> BenchmarkJob:
    """Reconstruct a benchmark job from a manifest/queue payload."""
    task = BenchmarkTask(**payload["task"])
    variant_payload = dict(payload["variant"])
    variant_payload["cli_flags"] = tuple(variant_payload.get("cli_flags", ()))
    variant = AblationVariant(**variant_payload)
    return BenchmarkJob(
        run_id=str(payload["run_id"]),
        task=task,
        variant=variant,
        seed=int(payload["seed"]),
        repetitions=int(payload.get("repetitions", 1)),
        eval_repetitions=int(payload.get("eval_repetitions", 1)),
        protocol=str(payload.get("protocol", "formal")),
    )


def load_manifest_jobs(path: str | Path) -> list[BenchmarkJob]:
    """Load jobs from a matrix manifest."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [benchmark_job_from_dict(job) for job in payload.get("jobs", [])]


class ResearchBenchmarkRunner:
    """Run benchmark jobs through the existing leased local queue."""

    def __init__(
        self,
        settings: ResearchRunSettings,
        *,
        max_concurrency: int = 2,
        max_attempts: int = 3,
    ) -> None:
        self._settings = settings
        self._max_concurrency = max_concurrency
        self._max_attempts = max_attempts
        self._result_lock = threading.Lock()
        settings.results_path.parent.mkdir(parents=True, exist_ok=True)
        settings.runs_dir.mkdir(parents=True, exist_ok=True)

    def run(self, jobs: list[BenchmarkJob], queue_db: str | Path) -> ExecutorReport:
        """Idempotently enqueue and drain a benchmark matrix."""
        queue_path = Path(queue_db)
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        db = Database(str(queue_path))
        initialize_database(db)
        existing = db.fetchone(
            "SELECT id FROM experiment WHERE task_id = ? ORDER BY id LIMIT 1",
            ("research-benchmark",),
        )
        if existing:
            experiment_id = str(existing["id"])
        else:
            experiment = ExperimentRepository(db).create(
                task_id="research-benchmark",
                task_name="research-benchmark",
                config_snapshot={
                    "run_count": len(jobs),
                    "generations": self._settings.generations,
                    "population_size": self._settings.population_size,
                },
            )
            experiment_id = experiment.id
        store = JobStore(db, lease_sec=max(120, int(self._settings.timeout_sec) + 60))
        store.recover_orphan_jobs()
        enqueue_matrix(
            jobs,
            store,
            experiment_id,
            max_attempts=self._max_attempts,
        )
        executor = LocalTaskExecutor(
            store,
            {"research_benchmark": self._handle_job},
            max_concurrency=self._max_concurrency,
            retry_backoff_sec=1.0,
        )
        try:
            report = executor.run_until_idle()
            for row in db.fetchall(
                "SELECT payload, last_error, attempt FROM job WHERE status = 'failed'"
            ):
                payload = json.loads(row["payload"])
                job = benchmark_job_from_dict(payload)
                self._append_result(
                    {
                        "schema_version": 2,
                        "run_id": job.run_id,
                        "task": job.task.name,
                        "variant": job.variant.name,
                        "seed": job.seed,
                        "status": "failed",
                        "score": None,
                        "error": row["last_error"],
                        "failure_category": self._failure_category(str(row["last_error"])),
                        "attempts": int(row["attempt"]),
                    }
                )
            return report
        finally:
            db.close()

    def _handle_job(self, queued_job: Job) -> str:
        job = benchmark_job_from_dict(queued_job.payload)
        existing = self._find_existing_result(job.run_id)
        if existing is not None:
            return str(self._settings.results_path)

        measurements = [
            self._run_repetition(job, repetition, attempt=queued_job.attempt)
            for repetition in range(job.repetitions)
        ]
        scores = [float(measurement["frontier_auc"]) for measurement in measurements]
        known_cost = all(bool(measurement["cost_known"]) for measurement in measurements)
        score_stdev = statistics.stdev(scores) if len(scores) > 1 else 0.0
        score_ci_half_width = (
            1.96 * score_stdev / (len(scores) ** 0.5) if len(scores) > 1 else 0.0
        )
        record = {
            "schema_version": 2,
            "run_id": job.run_id,
            "protocol": job.protocol,
            "task": job.task.name,
            "variant": job.variant.name,
            "seed": job.seed,
            "status": "completed",
            "score": statistics.fmean(scores),
            "scores": scores,
            "frontier_auc": statistics.fmean(scores),
            "best_of_budget": statistics.fmean(
                float(measurement["best_of_budget"]) for measurement in measurements
            ),
            "success_rate": statistics.fmean(
                float(measurement["success_rate"]) for measurement in measurements
            ),
            "score_stdev": score_stdev,
            "score_ci95": [
                statistics.fmean(scores) - score_ci_half_width,
                statistics.fmean(scores) + score_ci_half_width,
            ],
            "repetitions": job.repetitions,
            "eval_repetitions": job.eval_repetitions,
            "cost_usd": (
                sum(float(measurement["cost_usd"]) for measurement in measurements)
                if known_cost
                else None
            ),
            "cost_known": known_cost,
            "total_tokens": sum(
                measurement["total_tokens"] for measurement in measurements
            ),
            "llm_calls": sum(measurement["llm_calls"] for measurement in measurements),
            "candidate_counts": [
                measurement["candidate_count"] for measurement in measurements
            ],
            "checkpoint_generations": [
                measurement["checkpoint_generation"] for measurement in measurements
            ],
            "wall_sec": sum(measurement["wall_sec"] for measurement in measurements),
            "provenance_valid": all(
                measurement.get("provenance_valid") is True for measurement in measurements
            ),
            "failure_category": None,
            "attempts": queued_job.attempt,
            "git_commit": self._git_commit(),
            "generations": self._settings.generations,
            "population_size": self._settings.population_size,
        }
        self._append_result(record)
        return str(self._settings.results_path)

    def _run_repetition(
        self, job: BenchmarkJob, repetition: int, *, attempt: int = 1
    ) -> dict[str, Any]:
        repetition_dir = self._settings.runs_dir / job.run_id / f"rep-{repetition}"
        run_dir = repetition_dir / "attempts" / f"attempt-{attempt}"
        run_dir.mkdir(parents=True, exist_ok=True)
        db_path = run_dir / "run.db"
        artifact_dir = run_dir / "artifacts"
        vector_dir = run_dir / "vectors"
        export_dir = run_dir / "exports"
        config_path = TASK_CONFIGS.get(job.task.name, "omnievolve.toml")

        args = [
            sys.executable,
            "-m",
            "omnievolve.cli",
            "run",
            job.task.initial_code,
            "--task-name",
            job.task.name,
            "--config",
            config_path,
            "--evaluator",
            job.task.evaluator,
            "--gens",
            str(self._settings.generations),
            "--seed",
            str(job.seed + repetition),
            "--set",
            f"evolution.population_size={self._settings.population_size}",
            "--set",
            f"evolution.eval_repetitions={job.eval_repetitions}",
            "--set",
            f"storage.db_path={json.dumps(str(db_path.resolve()))}",
            "--set",
            f"storage.artifact_dir={json.dumps(str(artifact_dir.resolve()))}",
            "--set",
            f"storage.vector_dir={json.dumps(str(vector_dir.resolve()))}",
            "--set",
            f"storage.export_dir={json.dumps(str(export_dir.resolve()))}",
            "--set",
            "storage.code_backend=cas",
            "--set",
            'embedding.code.provider="fake"',
            "--set",
            "embedding.code.dimension=128",
            "--set",
            'embedding.thought.provider="fake"',
            "--set",
            "embedding.thought.dimension=128",
        ]
        for key, value in job.variant.config_overrides.items():
            args.extend(("--set", f"{key}={json.dumps(value)}"))
        if self._settings.trusted:
            args.append("--trusted")

        env = os.environ.copy()
        env["PYTHONHASHSEED"] = str(job.seed + repetition)
        replay = build_replay_record(
            repo_root=self._settings.repo_root,
            job=job,
            repetition=repetition,
            argv=args,
            env=env,
            config_path=config_path,
            generations=self._settings.generations,
            population_size=self._settings.population_size,
        )
        replay_path = run_dir / "replay.json"
        replay_path.write_text(
            json.dumps(replay, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        started = time.monotonic()
        try:
            completed = subprocess.run(
                args,
                cwd=self._settings.repo_root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._settings.timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"benchmark timed out after {self._settings.timeout_sec}s"
            ) from exc

        (run_dir / "stdout.log").write_text(completed.stdout, encoding="utf-8")
        (run_dir / "stderr.log").write_text(completed.stderr, encoding="utf-8")
        replay["returncode"] = completed.returncode
        (run_dir / "replay.json").write_text(
            json.dumps(replay, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if completed.returncode != 0:
            tail = "\n".join(completed.stderr.splitlines()[-20:])
            self._raise_command_failure(completed.returncode, tail)
        provenance_errors = validate_replay_record(replay, self._settings.repo_root)
        if provenance_errors:
            raise PermanentJobError(
                "research provenance changed during run: " + "; ".join(provenance_errors)
            )
        stats = self._read_run_stats(db_path, job)
        stats["wall_sec"] = time.monotonic() - started
        stats["provenance_valid"] = True
        stats["attempt"] = attempt
        replay["observed"] = stats
        replay_path.write_text(
            json.dumps(replay, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        repetition_dir.mkdir(parents=True, exist_ok=True)
        (repetition_dir / "replay.json").write_text(
            json.dumps(replay, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return stats

    def _read_run_stats(
        self, db_path: Path, job: BenchmarkJob
    ) -> dict[str, Any]:
        """Read metrics and reject superficially completed, non-evolving runs."""
        if not db_path.exists():
            raise RuntimeError(f"benchmark database was not created: {db_path}")
        with sqlite3.connect(db_path) as connection:
            try:
                trajectory = connection.execute(
                    """
                    SELECT c.generation, er.primary_score, COALESCE(er.passed, 0)
                    FROM evaluation_run er
                    JOIN candidate c ON c.id = er.candidate_id
                    WHERE er.status = 'completed' AND er.primary_score IS NOT NULL
                      AND c.status != 'aborted'
                    ORDER BY c.generation, er.id
                    """
                ).fetchall()
            except sqlite3.OperationalError:
                # Compatibility with compact unit fixtures and schema-v1 runs.
                row = connection.execute(
                    """
                    SELECT MAX(primary_score)
                    FROM evaluation_run
                    WHERE status = 'completed' AND primary_score IS NOT NULL
                    """
                ).fetchone()
                trajectory = [] if row is None or row[0] is None else [(0, row[0], 1)]
            ledger = connection.execute(
                """
                SELECT COUNT(*), COUNT(cost_usd), SUM(cost_usd),
                       COALESCE(SUM(total_tokens), 0)
                FROM llm_call_ledger
                """
            ).fetchone()
            candidate_count = int(
                connection.execute("SELECT COUNT(*) FROM candidate").fetchone()[0]
            )
            experiment = connection.execute(
                """
                SELECT status, checkpoint_data
                FROM experiment
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
            try:
                policy_experiments = connection.execute(
                    """
                    SELECT COUNT(*), SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)
                    FROM policy_experiment
                    """
                ).fetchone()
            except sqlite3.OperationalError:
                policy_experiments = (0, 0)
        if not trajectory:
            raise RuntimeError("benchmark produced no completed score")
        if experiment is None:
            raise RuntimeError("benchmark produced no experiment record")
        if experiment[0] != "completed":
            raise RuntimeError(f"benchmark experiment ended with status {experiment[0]!r}")
        checkpoint = json.loads(experiment[1] or "{}")
        checkpoint_generation = int(checkpoint.get("generation", 0))
        if checkpoint_generation < self._settings.generations:
            raise RuntimeError(
                "benchmark stopped before the requested generation "
                f"({checkpoint_generation} < {self._settings.generations})"
            )
        if candidate_count <= 1:
            raise RuntimeError(
                "benchmark produced no evolved candidates; candidate-slot failures "
                "must not be reported as a completed run"
            )
        llm_calls = int(ledger[0] if ledger else 0)
        if job.variant.name != "random_search" and llm_calls == 0:
            raise RuntimeError(
                f"benchmark variant {job.variant.name!r} produced no successful LLM calls"
            )
        canary_total = int(policy_experiments[0] if policy_experiments else 0)
        canary_completed = int(
            (policy_experiments[1] or 0) if policy_experiments else 0
        )
        if (
            job.variant.name in _SLOW_LOOP_REQUIRED_VARIANTS
            and canary_completed == 0
        ):
            raise PermanentJobError(
                f"{job.variant.name} variant produced no completed independent "
                "policy canary; "
                "it is not distinguishable from no_slow_loop"
            )
        if job.variant.name == "no_slow_loop" and canary_total:
            raise PermanentJobError(
                "no_slow_loop produced policy canary evidence despite being disabled"
            )
        generation_best: dict[int, float] = {}
        for generation, score, _passed in trajectory:
            generation = int(generation or 0)
            generation_best[generation] = max(
                generation_best.get(generation, -float("inf")), float(score)
            )
        frontier = []
        running_best = -float("inf")
        for generation in range(self._settings.generations + 1):
            if generation in generation_best:
                running_best = max(running_best, generation_best[generation])
            if math.isfinite(running_best):
                frontier.append(running_best)
        best_of_budget = max(float(row[1]) for row in trajectory)
        frontier_auc = statistics.fmean(frontier)
        success_rate = statistics.fmean(float(bool(row[2])) for row in trajectory)
        priced_calls = int(ledger[1] if ledger else 0)
        cost_known = llm_calls == priced_calls
        cost_usd = (
            float(ledger[2] or 0.0)
            if ledger and cost_known
            else None
        )
        return {
            "score": frontier_auc,
            "frontier_auc": frontier_auc,
            "best_of_budget": best_of_budget,
            "success_rate": success_rate,
            "cost_usd": cost_usd,
            "cost_known": cost_known,
            "total_tokens": int(ledger[3] if ledger else 0),
            "llm_calls": llm_calls,
            "candidate_count": candidate_count,
            "checkpoint_generation": checkpoint_generation,
            "policy_canary_count": canary_total,
            "policy_canary_completed": canary_completed,
        }

    @staticmethod
    def _raise_command_failure(returncode: int, stderr_tail: str) -> None:
        message = f"benchmark command failed ({returncode}): {stderr_tail}"
        permanent_markers = (
            "authentication",
            "unauthorized",
            "invalid api key",
            "permission denied",
            "configurationerror",
            "invalid configuration",
            "no such option",
            "integrity",
        )
        if any(marker in stderr_tail.lower() for marker in permanent_markers):
            raise PermanentJobError(message)
        raise RuntimeError(message)

    @staticmethod
    def _failure_category(error: str) -> str:
        lower = error.lower()
        if "permanentjoberror" in lower or any(
            marker in lower
            for marker in ("authentication", "unauthorized", "configuration", "integrity")
        ):
            return "permanent_configuration_auth_integrity"
        if "timeout" in lower or "rate limit" in lower or "temporar" in lower:
            return "transient_provider_or_timeout"
        return "infrastructure"

    def _find_existing_result(self, run_id: str) -> dict[str, Any] | None:
        if not self._settings.results_path.exists():
            return None
        with self._result_lock:
            for line in self._settings.results_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("run_id") == run_id and record.get("status") == "completed":
                    return record
        return None

    def _append_result(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self._result_lock:
            if self._find_existing_result_unlocked(str(record["run_id"])):
                return
            with self._settings.results_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def _find_existing_result_unlocked(self, run_id: str) -> bool:
        if not self._settings.results_path.exists():
            return False
        return any(
            json.loads(line).get("run_id") == run_id
            for line in self._settings.results_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    def _git_commit(self) -> str | None:
        try:
            return subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self._settings.repo_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
                timeout=10,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
