"""Executable, resumable research benchmark queue."""

from __future__ import annotations

import json
import os
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
    AblationVariant,
    BenchmarkJob,
    BenchmarkTask,
    enqueue_matrix,
)
from omnievolve.storage.db import Database
from omnievolve.storage.job_store import Job, JobStore
from omnievolve.storage.local_executor import ExecutorReport, LocalTaskExecutor
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


@dataclass(frozen=True)
class ResearchRunSettings:
    repo_root: Path
    results_path: Path
    runs_dir: Path
    generations: int = 5
    population_size: int = 4
    timeout_sec: float = 3600.0
    trusted: bool = True


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
                "SELECT payload, last_error FROM job WHERE status = 'failed'"
            ):
                payload = json.loads(row["payload"])
                job = benchmark_job_from_dict(payload)
                self._append_result(
                    {
                        "schema_version": 1,
                        "run_id": job.run_id,
                        "task": job.task.name,
                        "variant": job.variant.name,
                        "seed": job.seed,
                        "status": "failed",
                        "score": None,
                        "error": row["last_error"],
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
            self._run_repetition(job, repetition)
            for repetition in range(job.repetitions)
        ]
        scores = [measurement["score"] for measurement in measurements]
        record = {
            "schema_version": 1,
            "run_id": job.run_id,
            "task": job.task.name,
            "variant": job.variant.name,
            "seed": job.seed,
            "status": "completed",
            "score": statistics.fmean(scores),
            "scores": scores,
            "repetitions": job.repetitions,
            "cost_usd": sum(measurement["cost_usd"] for measurement in measurements),
            "total_tokens": sum(
                measurement["total_tokens"] for measurement in measurements
            ),
            "wall_sec": sum(measurement["wall_sec"] for measurement in measurements),
            "git_commit": self._git_commit(),
            "generations": self._settings.generations,
            "population_size": self._settings.population_size,
        }
        self._append_result(record)
        return str(self._settings.results_path)

    def _run_repetition(
        self, job: BenchmarkJob, repetition: int
    ) -> dict[str, float | int]:
        run_dir = self._settings.runs_dir / job.run_id / f"rep-{repetition}"
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
            f"storage.db_path={json.dumps(str(db_path.resolve()))}",
            "--set",
            f"storage.artifact_dir={json.dumps(str(artifact_dir.resolve()))}",
            "--set",
            f"storage.vector_dir={json.dumps(str(vector_dir.resolve()))}",
            "--set",
            f"storage.export_dir={json.dumps(str(export_dir.resolve()))}",
            "--set",
            "storage.code_backend=cas",
        ]
        for key, value in job.variant.config_overrides.items():
            args.extend(("--set", f"{key}={json.dumps(value)}"))
        if self._settings.trusted:
            args.append("--trusted")

        env = os.environ.copy()
        env["PYTHONHASHSEED"] = str(job.seed + repetition)
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
        replay = {
            "argv": args,
            "cwd": str(self._settings.repo_root),
            "pythonhashseed": env["PYTHONHASHSEED"],
            "git_commit": self._git_commit(),
        }
        (run_dir / "replay.json").write_text(
            json.dumps(replay, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if completed.returncode != 0:
            tail = "\n".join(completed.stderr.splitlines()[-20:])
            raise RuntimeError(f"benchmark command failed ({completed.returncode}): {tail}")
        stats = self._read_run_stats(db_path)
        stats["wall_sec"] = time.monotonic() - started
        return stats

    @staticmethod
    def _read_run_stats(db_path: Path) -> dict[str, float | int]:
        if not db_path.exists():
            raise RuntimeError(f"benchmark database was not created: {db_path}")
        with sqlite3.connect(db_path) as connection:
            row = connection.execute(
                """
                SELECT MAX(primary_score)
                FROM evaluation_run
                WHERE status = 'completed' AND primary_score IS NOT NULL
                """
            ).fetchone()
            ledger = connection.execute(
                """
                SELECT COALESCE(SUM(cost_usd), 0), COALESCE(SUM(total_tokens), 0)
                FROM llm_call_ledger
                """
            ).fetchone()
        if row is None or row[0] is None:
            raise RuntimeError("benchmark produced no completed score")
        return {
            "score": float(row[0]),
            "cost_usd": float(ledger[0] if ledger else 0.0),
            "total_tokens": int(ledger[1] if ledger else 0),
        }

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
                check=True,
                timeout=10,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
