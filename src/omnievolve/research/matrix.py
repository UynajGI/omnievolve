"""Deterministic multi-task, multi-seed ablation benchmark matrix.

The matrix is deliberately a protocol rather than an eager API-spending runner.
Every run has a stable id, explicit configuration overrides, and a result schema
that can be resumed and independently audited.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from omnievolve.eval.benchmark_stats import detect_regression, summarize_samples


@dataclass(frozen=True)
class BenchmarkTask:
    name: str
    initial_code: str
    evaluator: str
    category: str


@dataclass(frozen=True)
class AblationVariant:
    name: str
    description: str
    config_overrides: dict[str, Any] = field(default_factory=dict)
    cli_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class BenchmarkJob:
    run_id: str
    task: BenchmarkTask
    variant: AblationVariant
    seed: int
    repetitions: int = 1

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["variant"]["cli_flags"] = list(self.variant.cli_flags)
        return value


DEFAULT_TASKS = (
    BenchmarkTask(
        "circle_packing",
        "examples/circle_packing/initial_code.py",
        "examples.circle_packing.evaluator:CirclePackingEvaluator",
        "continuous_geometry",
    ),
    BenchmarkTask(
        "contract_cheaper",
        "examples/contract_cheaper/initial_code.py",
        "examples.contract_cheaper.evaluator:ContractCheaperEvaluator",
        "program_optimization",
    ),
    BenchmarkTask(
        "heilbronn",
        "examples/heilbronn/initial_code.py",
        "examples.heilbronn.evaluator:HeilbronnEvaluator",
        "continuous_geometry",
    ),
    BenchmarkTask(
        "lennard_jones",
        "examples/lennard_jones/initial_code.py",
        "examples.lennard_jones.evaluator:LennardJonesEvaluator",
        "scientific_computing",
    ),
    BenchmarkTask(
        "matmul",
        "examples/matmul/initial_code.py",
        "examples.matmul.evaluator:MatmulEvaluator",
        "algorithm_discovery",
    ),
    BenchmarkTask(
        "nqueens",
        "examples/nqueens/initial_code.py",
        "examples.nqueens.evaluator:NQueensEvaluator",
        "combinatorial",
    ),
    BenchmarkTask(
        "occam_circuit",
        "examples/occam_circuit/initial_code.py",
        "examples.occam_circuit.evaluator:OccamCircuitEvaluator",
        "circuit_design",
    ),
    BenchmarkTask(
        "orbit_q",
        "examples/orbit_q/initial_code.py",
        "examples.orbit_q.evaluator:OrbitQEvaluator",
        "symbolic_math",
    ),
    BenchmarkTask(
        "sort",
        "examples/python_optimization/initial_code.py",
        "examples.python_optimization.evaluator:SortEvaluator",
        "runtime_optimization",
    ),
)

DEFAULT_VARIANTS = (
    AblationVariant("full", "Full OmniEvolve system."),
    AblationVariant(
        "random_search",
        "Random parent search without novelty, crossover, or slow loop.",
        {
            "selection.parent_selector": "random",
            "evolution.novelty_enabled": False,
            "evolution.crossover_rate": 0.0,
            "evolution.self_evolve_enabled": False,
            "evolution.island_count": 1,
        },
        ("--no-self-evolve",),
    ),
    AblationVariant(
        "single_agent",
        "One proposal and one island, with crossover and slow loop disabled.",
        {
            "evolution.population_size": 1,
            "evolution.island_count": 1,
            "evolution.crossover_rate": 0.0,
            "evolution.self_evolve_enabled": False,
            "evolution.single_agent_mode": True,
            "models.routing.role_conditioned": False,
        },
        ("--no-self-evolve",),
    ),
    AblationVariant(
        "no_novelty",
        "Full system with the novelty gate disabled.",
        {"evolution.novelty_enabled": False},
    ),
    AblationVariant(
        "no_slow_loop",
        "Full fast loop with controlled self-evolution disabled.",
        {"evolution.self_evolve_enabled": False},
        ("--no-self-evolve",),
    ),
)


def _run_id(task: str, variant: str, seed: int) -> str:
    raw = f"v1:{task}:{variant}:{seed}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def build_default_matrix(
    *,
    seeds: range | tuple[int, ...] = range(5),
    repetitions: int = 1,
) -> list[BenchmarkJob]:
    """Build the canonical 9-task, 5+-seed ablation matrix."""
    seed_values = tuple(seeds)
    if not 5 <= len(seed_values) <= 10:
        raise ValueError("research benchmark requires 5 to 10 seeds")
    if len(set(seed_values)) != len(seed_values) or any(seed < 0 for seed in seed_values):
        raise ValueError("seeds must be unique non-negative integers")
    if repetitions < 1:
        raise ValueError("repetitions must be positive")

    return [
        BenchmarkJob(
            run_id=_run_id(task.name, variant.name, seed),
            task=task,
            variant=variant,
            seed=seed,
            repetitions=repetitions,
        )
        for task in DEFAULT_TASKS
        for variant in DEFAULT_VARIANTS
        for seed in seed_values
    ]


def write_manifest(jobs: list[BenchmarkJob], output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "task_count": len({job.task.name for job in jobs}),
        "variant_count": len({job.variant.name for job in jobs}),
        "seed_count": len({job.seed for job in jobs}),
        "run_count": len(jobs),
        "jobs": [job.to_dict() for job in jobs],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def enqueue_matrix(
    jobs: list[BenchmarkJob],
    store: Any,
    experiment_id: str,
    *,
    max_attempts: int = 3,
) -> list[str]:
    """Idempotently enqueue a matrix in the existing local JobStore."""
    ids = []
    for job in jobs:
        queued = store.create_job(
            experiment_id,
            "research_benchmark",
            job.to_dict(),
            max_attempts=max_attempts,
            job_id=f"research-{job.run_id}",
        )
        ids.append(queued.id)
    return ids


def summarize_results(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate completed results with deterministic bootstrap intervals."""
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    failures: dict[tuple[str, str], int] = defaultdict(int)
    for record in records:
        key = (str(record["task"]), str(record["variant"]))
        if record.get("status") == "completed" and record.get("score") is not None:
            grouped[key].append(float(record["score"]))
        else:
            failures[key] += 1

    cells = []
    for key in sorted(set(grouped) | set(failures)):
        samples = grouped[key]
        stats = summarize_samples(samples, seed=0).to_dict() if samples else None
        cells.append(
            {
                "task": key[0],
                "variant": key[1],
                "completed": len(samples),
                "failed": failures[key],
                "score": stats,
            }
        )
    comparisons = []
    tasks = sorted({task for task, _ in grouped})
    for task in tasks:
        baseline = grouped.get((task, "full"), [])
        if not baseline:
            continue
        for variant in sorted(name for current_task, name in grouped if current_task == task):
            if variant == "full":
                continue
            current = grouped[(task, variant)]
            if current:
                comparison = detect_regression(
                    baseline,
                    current,
                    direction="higher",
                    threshold=0.05,
                    seed=0,
                )
                comparisons.append(
                    {
                        "task": task,
                        "variant": variant,
                        "relative_to": "full",
                        **comparison.to_dict(),
                    }
                )
    return {"schema_version": 1, "cells": cells, "comparisons": comparisons}
