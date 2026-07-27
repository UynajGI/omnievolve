"""Sort evaluator consumes conservative repeated-benchmark statistics."""

from examples.python_optimization.evaluator import SortEvaluator
from omnievolve.eval.task_evaluator import EvaluationContext
from omnievolve.sandbox.base import SandboxExecutionResult


def _result(stdout: str) -> SandboxExecutionResult:
    return SandboxExecutionResult(
        return_codes=[0, 0],
        stdout=stdout,
        stderr="",
        output_artifacts={},
        execution_time_ms=123.0,
        cpu_time_ms=100.0,
        memory_peak_kb=1024,
    )


def _context() -> EvaluationContext:
    return EvaluationContext(
        experiment_id="exp",
        evaluator_version_id="eval",
        environment_version_id="env",
        seed=42,
    )


def test_uses_lower_confidence_bound_for_score():
    output = SortEvaluator().parse_result(
        _result(
            'noise\n{"speedup": 2.0, "speedup_ci_low": 1.5, '
            '"speedup_ci_high": 2.5, "time_ms": 3.0, "repetitions": 15}\n'
        ),
        _context(),
    )

    assert output.passed
    assert output.score == 0.575
    assert output.metrics["benchmark_repetitions"] == 15
    assert output.metrics["speedup_ci_low"] == 1.5


def test_missing_benchmark_json_fails_closed():
    output = SortEvaluator().parse_result(_result("not json"), _context())
    assert not output.passed
    assert output.score == 0.0
    assert "no valid JSON" in output.failure_reason
