"""Reproducible benchmark protocols for OmniEvolve research."""

from omnievolve.research.matrix import (
    PILOT_TASK_NAMES,
    PILOT_TASKS,
    AblationVariant,
    BenchmarkJob,
    BenchmarkTask,
    build_default_matrix,
    build_pilot_matrix,
    build_reference_credit_matrix,
    enqueue_matrix,
    load_calibration_repetitions,
    summarize_results,
)
from omnievolve.research.statistics import (
    assess_pilot_gate,
    calibrate_evaluator_noise,
    paired_seed_power_analysis,
)

__all__ = [
    "AblationVariant",
    "BenchmarkJob",
    "BenchmarkTask",
    "PILOT_TASK_NAMES",
    "PILOT_TASKS",
    "build_default_matrix",
    "build_pilot_matrix",
    "build_reference_credit_matrix",
    "assess_pilot_gate",
    "calibrate_evaluator_noise",
    "enqueue_matrix",
    "load_calibration_repetitions",
    "paired_seed_power_analysis",
    "summarize_results",
]
