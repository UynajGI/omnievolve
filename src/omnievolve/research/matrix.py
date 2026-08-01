"""Deterministic multi-task, multi-seed ablation benchmark matrix.

The matrix is deliberately a protocol rather than an eager API-spending runner.
Every run has a stable id, explicit configuration overrides, and a result schema
that can be resumed and independently audited.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

from omnievolve.eval.benchmark_stats import detect_regression, summarize_samples
from omnievolve.research.statistics import (
    assess_pilot_gate,
    cliffs_delta,
    holm_adjust,
    paired_randomization_p_value,
    paired_seed_power_analysis,
)


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
    eval_repetitions: int = 1
    protocol: str = "formal"

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

PILOT_TASK_NAMES = ("sort", "nqueens", "circle_packing")
PILOT_TASKS = tuple(
    next(task for task in DEFAULT_TASKS if task.name == name) for name in PILOT_TASK_NAMES
)

DEFAULT_VARIANTS = (
    AblationVariant(
        "full",
        "Full OmniEvolve system with the real controlled Slow Loop enabled.",
        {
            "evolution.self_evolve_enabled": True,
            "meta_evolution.enabled": True,
            "meta_evolution.meta_canary_budget_ratio": 0.5,
            # A research arm must actually execute a canary. Natural health
            # triggers are appropriate in production but would make `full`
            # silently identical to `no_slow_loop` on healthy short runs.
            "self_evaluator.roi_warn_threshold": 1_000_000_000.0,
        },
    ),
    AblationVariant(
        "random_search",
        "LLM-free deterministic AST random search.",
        {
            "selection.parent_selector": "random",
            "evolution.random_search_mode": True,
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
        {
            "evolution.novelty_enabled": False,
            "evolution.self_evolve_enabled": True,
            "meta_evolution.enabled": True,
            "meta_evolution.meta_canary_budget_ratio": 0.5,
            "self_evaluator.roi_warn_threshold": 1_000_000_000.0,
        },
    ),
    AblationVariant(
        "no_slow_loop",
        "Full fast loop with controlled self-evolution disabled.",
        {"evolution.self_evolve_enabled": False},
        ("--no-self-evolve",),
    ),
)

REFERENCE_CREDIT_VARIANTS = (
    AblationVariant(
        "reference_credit_on",
        "Full system with graph reference-edge credit enabled.",
        {"evolution.reference_credit_enabled": True},
    ),
    AblationVariant(
        "reference_credit_off",
        "Paired ablation with graph reference-edge credit disabled.",
        {"evolution.reference_credit_enabled": False},
    ),
)

OPERATOR_PORTFOLIO_VARIANTS = (
    AblationVariant(
        "operator_fixed",
        "Existing fixed/deterministic generation-mode mix without an operator bandit.",
        {
            "evolution.self_evolve_enabled": False,
            "evolution.operator_portfolio_enabled": False,
            "evolution.qd_archive_enabled": False,
        },
        ("--no-self-evolve",),
    ),
    AblationVariant(
        "operator_ucb",
        "Task/stage-conditioned UCB scheduling of point/diff/rewrite/crossover/repair.",
        {
            "evolution.self_evolve_enabled": False,
            "evolution.operator_portfolio_enabled": True,
            "evolution.operator_portfolio_algorithm": "ucb",
            "evolution.qd_archive_enabled": False,
        },
        ("--no-self-evolve",),
    ),
    AblationVariant(
        "operator_thompson",
        "Task/stage-conditioned Thompson scheduling of the same operator portfolio.",
        {
            "evolution.self_evolve_enabled": False,
            "evolution.operator_portfolio_enabled": True,
            "evolution.operator_portfolio_algorithm": "thompson",
            "evolution.qd_archive_enabled": False,
        },
        ("--no-self-evolve",),
    ),
)

QD_ARCHIVE_VARIANTS = (
    AblationVariant(
        "qd_off",
        "Existing island elite archive without behavior-cell parent sampling.",
        {
            "evolution.self_evolve_enabled": False,
            "evolution.qd_archive_enabled": False,
            "evolution.operator_portfolio_enabled": False,
        },
        ("--no-self-evolve",),
    ),
    AblationVariant(
        "qd_on",
        "Minimal island-local behavior-cell archive with bounded parent sampling.",
        {
            "evolution.self_evolve_enabled": False,
            "evolution.qd_archive_enabled": True,
            "evolution.operator_portfolio_enabled": False,
        },
        ("--no-self-evolve",),
    ),
)


def _run_id(
    task: str,
    variant: str,
    seed: int,
    *,
    protocol: str = "formal",
    repetitions: int = 1,
    eval_repetitions: int = 1,
) -> str:
    raw = (
        f"v3:{protocol}:{task}:{variant}:{seed}:"
        f"search-reps={repetitions}:eval-reps={eval_repetitions}"
    ).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _eval_repetitions_for_task(
    task_name: str,
    requested: int | Mapping[str, int],
) -> int:
    if isinstance(requested, Mapping):
        if task_name not in requested:
            raise ValueError(f"missing evaluator calibration for task {task_name!r}")
        value = int(requested[task_name])
    else:
        value = int(requested)
    if not 3 <= value <= 10:
        raise ValueError("evaluator repetitions must be between 3 and 10")
    return value


def load_calibration_repetitions(
    path: str | Path,
    *,
    required_tasks: Sequence[str],
) -> dict[str, int]:
    """Load audited per-task evaluator repeat counts from a calibration report."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    task_payloads = payload.get("tasks")
    if not isinstance(task_payloads, dict):
        raise ValueError("calibration report has no task results")
    repetitions: dict[str, int] = {}
    for task_name in required_tasks:
        task_result = task_payloads.get(task_name)
        if not isinstance(task_result, dict):
            raise ValueError(f"calibration report is missing task {task_name!r}")
        calibration = task_result.get("calibration", task_result)
        if not isinstance(calibration, dict) or "repeats" not in calibration:
            raise ValueError(f"calibration report has no repeat count for {task_name!r}")
        repetitions[task_name] = _eval_repetitions_for_task(
            task_name,
            {task_name: int(calibration["repeats"])},
        )
    return repetitions


def build_default_matrix(
    *,
    seeds: range | tuple[int, ...] = range(5),
    repetitions: int = 1,
    eval_repetitions: int | Mapping[str, int] = 3,
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
            run_id=_run_id(
                task.name,
                variant.name,
                seed,
                protocol="formal",
                repetitions=repetitions,
                eval_repetitions=_eval_repetitions_for_task(task.name, eval_repetitions),
            ),
            task=task,
            variant=variant,
            seed=seed,
            repetitions=repetitions,
            eval_repetitions=_eval_repetitions_for_task(task.name, eval_repetitions),
            protocol="formal",
        )
        for task in DEFAULT_TASKS
        for variant in DEFAULT_VARIANTS
        for seed in seed_values
    ]


def build_pilot_matrix(
    *,
    seeds: tuple[int, ...] = (0, 1, 2),
    repetitions: int = 1,
    eval_repetitions: int | Mapping[str, int] = 3,
) -> list[BenchmarkJob]:
    """Build the fixed 3-task × 5-variant × 3-paired-seed pilot (45 runs)."""
    if len(seeds) != 3 or len(set(seeds)) != 3 or any(seed < 0 for seed in seeds):
        raise ValueError("pilot requires exactly three unique non-negative paired seeds")
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    return [
        BenchmarkJob(
            run_id=_run_id(
                task.name,
                variant.name,
                seed,
                protocol="pilot",
                repetitions=repetitions,
                eval_repetitions=_eval_repetitions_for_task(task.name, eval_repetitions),
            ),
            task=task,
            variant=variant,
            seed=seed,
            repetitions=repetitions,
            eval_repetitions=_eval_repetitions_for_task(task.name, eval_repetitions),
            protocol="pilot",
        )
        for task in PILOT_TASKS
        for variant in DEFAULT_VARIANTS
        for seed in seeds
    ]


def build_reference_credit_matrix(
    *,
    seeds: range | tuple[int, ...] = range(5),
    repetitions: int = 1,
    eval_repetitions: int | Mapping[str, int] = 3,
) -> list[BenchmarkJob]:
    """Build the separate paired reference-edge-credit ablation matrix."""
    seed_values = tuple(seeds)
    if not seed_values or len(set(seed_values)) != len(seed_values):
        raise ValueError("seeds must be a non-empty unique sequence")
    if any(seed < 0 for seed in seed_values):
        raise ValueError("seeds must be non-negative")
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    return [
        BenchmarkJob(
            run_id=_run_id(
                task.name,
                variant.name,
                seed,
                protocol="reference_credit",
                repetitions=repetitions,
                eval_repetitions=_eval_repetitions_for_task(task.name, eval_repetitions),
            ),
            task=task,
            variant=variant,
            seed=seed,
            repetitions=repetitions,
            eval_repetitions=_eval_repetitions_for_task(task.name, eval_repetitions),
            protocol="reference_credit",
        )
        for task in DEFAULT_TASKS
        for variant in REFERENCE_CREDIT_VARIANTS
        for seed in seed_values
    ]


def _build_independent_ablation_matrix(
    *,
    variants: tuple[AblationVariant, ...],
    protocol: str,
    seeds: range | tuple[int, ...],
    repetitions: int,
    eval_repetitions: int | Mapping[str, int],
) -> list[BenchmarkJob]:
    seed_values = tuple(seeds)
    if not 5 <= len(seed_values) <= 10:
        raise ValueError("independent ablation requires 5 to 10 paired seeds")
    if len(set(seed_values)) != len(seed_values) or any(seed < 0 for seed in seed_values):
        raise ValueError("seeds must be unique non-negative integers")
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    return [
        BenchmarkJob(
            run_id=_run_id(
                task.name,
                variant.name,
                seed,
                protocol=protocol,
                repetitions=repetitions,
                eval_repetitions=_eval_repetitions_for_task(task.name, eval_repetitions),
            ),
            task=task,
            variant=variant,
            seed=seed,
            repetitions=repetitions,
            eval_repetitions=_eval_repetitions_for_task(task.name, eval_repetitions),
            protocol=protocol,
        )
        for task in DEFAULT_TASKS
        for variant in variants
        for seed in seed_values
    ]


def build_operator_portfolio_matrix(
    *,
    seeds: range | tuple[int, ...] = range(5),
    repetitions: int = 1,
    eval_repetitions: int | Mapping[str, int] = 3,
) -> list[BenchmarkJob]:
    """Build the separate fixed-vs-UCB-vs-Thompson operator experiment."""

    return _build_independent_ablation_matrix(
        variants=OPERATOR_PORTFOLIO_VARIANTS,
        protocol="operator_portfolio",
        seeds=seeds,
        repetitions=repetitions,
        eval_repetitions=eval_repetitions,
    )


def build_qd_archive_matrix(
    *,
    seeds: range | tuple[int, ...] = range(5),
    repetitions: int = 1,
    eval_repetitions: int | Mapping[str, int] = 3,
) -> list[BenchmarkJob]:
    """Build the separate minimal behavior-archive ablation."""

    return _build_independent_ablation_matrix(
        variants=QD_ARCHIVE_VARIANTS,
        protocol="qd_archive",
        seeds=seeds,
        repetitions=repetitions,
        eval_repetitions=eval_repetitions,
    )


def write_manifest(
    jobs: list[BenchmarkJob],
    output: str | Path,
    *,
    metadata: dict[str, Any] | None = None,
) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "task_count": len({job.task.name for job in jobs}),
        "variant_count": len({job.variant.name for job in jobs}),
        "seed_count": len({job.seed for job in jobs}),
        "run_count": len(jobs),
        "eval_repetitions": {
            task_name: sorted({job.eval_repetitions for job in jobs if job.task.name == task_name})
            for task_name in sorted({job.task.name for job in jobs})
        },
        "metadata": metadata or {},
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


def summarize_results(
    records: list[dict[str, Any]],
    *,
    include_cost_metric: bool = True,
    deterministic_replay_passed: bool = False,
) -> dict[str, Any]:
    """Aggregate paired research results without treating unknown cost as zero."""
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    failures: dict[tuple[str, str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for record in records:
        key = (
            str(record.get("protocol") or "formal"),
            str(record["task"]),
            str(record["variant"]),
        )
        if record.get("status") == "completed" and record.get("score") is not None:
            grouped[key].append(record)
        else:
            failures[key][str(record.get("failure_category") or "unknown")] += 1

    cells = []
    for key in sorted(set(grouped) | set(failures)):
        completed = grouped[key]

        def metric_stats(name: str, fallback: str | None = None) -> dict[str, Any] | None:
            values = [
                float(record[name] if record.get(name) is not None else record[fallback])
                for record in completed
                if record.get(name) is not None
                or (fallback is not None and record.get(fallback) is not None)
            ]
            return summarize_samples(values, seed=0).to_dict() if values else None

        known_costs = [
            float(record["cost_usd"])
            for record in completed
            if record.get("cost_known") is True and record.get("cost_usd") is not None
        ]
        cells.append(
            {
                "protocol": key[0],
                "task": key[1],
                "variant": key[2],
                "completed": len(completed),
                "failed": sum(failures[key].values()),
                "failure_categories": dict(sorted(failures[key].items())),
                "score": metric_stats("frontier_auc", "score"),
                "frontier_auc": metric_stats("frontier_auc", "score"),
                "best_of_budget": metric_stats("best_of_budget", "score"),
                "success_rate": metric_stats("success_rate"),
                "total_tokens": metric_stats("total_tokens"),
                "wall_sec": metric_stats("wall_sec"),
                "cost_usd": (
                    summarize_samples(known_costs, seed=0).to_dict() if known_costs else None
                ),
                "unknown_cost_runs": len(completed) - len(known_costs),
            }
        )
    comparisons = []
    baseline_names = {
        "operator_portfolio": "operator_fixed",
        "qd_archive": "qd_off",
        "reference_credit": "reference_credit_off",
    }
    protocols = sorted({protocol for protocol, _, _ in grouped})
    for protocol in protocols:
        baseline_name = baseline_names.get(protocol, "full")
        tasks = sorted(
            {task for current_protocol, task, _ in grouped if current_protocol == protocol}
        )
        for task in tasks:
            baseline_records = grouped.get((protocol, task, baseline_name), [])
            baseline = {
                int(record["seed"]): float(record.get("frontier_auc", record["score"]))
                for record in baseline_records
                if record.get("seed") is not None
            }
            if not baseline_records:
                continue
            variants = sorted(
                name
                for current_protocol, current_task, name in grouped
                if current_protocol == protocol and current_task == task
            )
            for variant in variants:
                if variant == baseline_name:
                    continue
                current_records = grouped[(protocol, task, variant)]
                current = {
                    int(record["seed"]): float(record.get("frontier_auc", record["score"]))
                    for record in current_records
                    if record.get("seed") is not None
                }
                paired_seeds = sorted(set(baseline) & set(current))
                if paired_seeds:
                    baseline_values = [baseline[seed] for seed in paired_seeds]
                    current_values = [current[seed] for seed in paired_seeds]
                    differences = [baseline[seed] - current[seed] for seed in paired_seeds]
                    effect = summarize_samples(differences, seed=0).to_dict()
                    deviation = statistics.stdev(differences) if len(differences) >= 2 else 0.0
                    comparison_record = {
                        "protocol": protocol,
                        "task": task,
                        "variant": variant,
                        "relative_to": baseline_name,
                        "paired_seeds": paired_seeds,
                        "effect_baseline_minus_variant": effect,
                        "cliffs_delta": cliffs_delta(
                            baseline_values,
                            current_values,
                        ),
                        "standardized_effect": (
                            statistics.fmean(differences) / deviation if deviation > 0 else None
                        ),
                        "p_value": paired_randomization_p_value(differences),
                        "power_analysis": (
                            paired_seed_power_analysis(differences).to_dict()
                            if len(differences) >= 2
                            else None
                        ),
                    }
                    if baseline_name == "full":
                        comparison_record["effect_full_minus_variant"] = effect
                    comparisons.append(comparison_record)
                elif not baseline and current_records:
                    # Schema-v1 compatibility only. New research records carry
                    # seeds and therefore take the paired path above.
                    comparison = detect_regression(
                        [float(record["score"]) for record in baseline_records],
                        [float(record["score"]) for record in current_records],
                        direction="higher",
                        threshold=0.05,
                        seed=0,
                    )
                    comparisons.append(
                        {
                            "protocol": protocol,
                            "task": task,
                            "variant": variant,
                            "relative_to": baseline_name,
                            **comparison.to_dict(),
                        }
                    )
    tested = [
        (index, comparison)
        for index, comparison in enumerate(comparisons)
        if comparison.get("p_value") is not None
    ]
    adjusted = holm_adjust([comparison["p_value"] for _, comparison in tested])
    for (index, _), adjusted_value in zip(tested, adjusted, strict=True):
        comparisons[index]["holm_adjusted_p"] = adjusted_value
    power_results = [
        comparison["power_analysis"]
        for comparison in comparisons
        if comparison.get("power_analysis") is not None
    ]
    formal_seed_recommendation = (
        {
            "recommended_seeds": max(int(result["recommended_seeds"]) for result in power_results),
            "required_seeds_unbounded": max(
                int(result["required_seeds_unbounded"]) for result in power_results
            ),
            "underpowered_at_ten": any(
                bool(result["underpowered_at_ten"]) for result in power_results
            ),
            "minimum_effect": 0.05,
            "power": 0.80,
            "alpha": 0.05,
        }
        if power_results
        else None
    )
    pilot_gate = (
        assess_pilot_gate(
            [record for record in records if record.get("protocol") == "pilot"],
            include_cost_metric=include_cost_metric,
            deterministic_replay_passed=deterministic_replay_passed,
        ).to_dict()
        if any(record.get("protocol") == "pilot" for record in records)
        else None
    )
    return {
        "schema_version": 2,
        "cells": cells,
        "comparisons": comparisons,
        "pilot_gate": pilot_gate,
        "formal_seed_recommendation": formal_seed_recommendation,
        "slow_loop_decision": _assess_slow_loop(records),
    }


def _assess_slow_loop(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Make a confidence-aware keep/simplify decision from paired runs."""
    completed: dict[tuple[str, str, int], float] = {}
    for record in records:
        if record.get("status") != "completed" or record.get("score") is None:
            continue
        completed[(str(record["task"]), str(record["variant"]), int(record.get("seed", -1)))] = (
            float(record["score"])
        )

    differences = []
    pair_ids = []
    task_seeds = sorted((task, seed) for task, variant, seed in completed if variant == "full")
    for task, seed in task_seeds:
        full = completed.get((task, "full", seed))
        no_slow = completed.get((task, "no_slow_loop", seed))
        if full is None or no_slow is None:
            continue
        differences.append(full - no_slow)
        pair_ids.append(f"{task}:{seed}")

    if len(differences) < 2:
        return {
            "decision": "insufficient_data",
            "paired_runs": len(differences),
            "reason": "At least two paired full/no_slow_loop runs are required.",
        }

    stats = summarize_samples(differences, seed=0).to_dict()
    lower = cast(float, stats["ci_low"])
    upper = cast(float, stats["ci_high"])
    if lower > 0:
        decision = "keep"
        reason = "Slow Loop has a positive paired effect with a CI entirely above zero."
    elif upper < 0:
        decision = "simplify"
        reason = "No-slow-loop is better with a CI entirely below zero."
    else:
        decision = "inconclusive"
        reason = "The paired effect CI crosses zero; keep the feature flag and gather more data."
    return {
        "decision": decision,
        "paired_runs": len(differences),
        "paired_ids": pair_ids,
        "effect_full_minus_no_slow_loop": stats,
        "reason": reason,
    }
