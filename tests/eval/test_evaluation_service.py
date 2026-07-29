from __future__ import annotations

from dataclasses import dataclass

import pytest

from omnievolve.eval.evaluation_service import EvaluationService
from omnievolve.eval.task_evaluator import EvalOutput, EvaluationContext
from omnievolve.sandbox.base import (
    CandidateArtifact,
    EvaluationPlan,
    SandboxExecutionResult,
    SandboxPolicy,
)


class _Artifacts:
    def load_text(self, artifact_hash: str) -> str:
        assert artifact_hash == "source"
        return "def solve(values):\n    return sorted(values)\n"


class _InvalidArtifacts:
    def load_text(self, artifact_hash: str) -> str:
        assert artifact_hash == "source"
        return "def broken(:\n"


class _Sandbox:
    environment_version_id = "fake-sandbox@1"

    def __init__(self, scores: list[float]) -> None:
        self._scores = iter(scores)
        self.calls = 0

    def execute(self, plan, candidate, policy) -> SandboxExecutionResult:
        del plan, candidate, policy
        self.calls += 1
        score = next(self._scores)
        return SandboxExecutionResult(
            return_codes=[0],
            stdout=str(score),
            stderr="",
            output_artifacts={},
            execution_time_ms=10.0,
            cpu_time_ms=5.0,
            memory_peak_kb=32,
        )


@dataclass
class _Evaluator:
    version_id: str = "fake-evaluator@1"

    def build_plan(self, candidate, context) -> EvaluationPlan:
        del candidate, context
        return EvaluationPlan(commands=[])

    def parse_result(self, result, context) -> EvalOutput:
        del context
        score = float(result.stdout)
        return EvalOutput(score=score, metrics={"raw": score}, passed=score > 0)

    def get_baseline(self) -> float:
        return 0.0


class _ProgressiveEvaluator(_Evaluator):
    def __init__(self) -> None:
        self.stages: list[int] = []

    def build_stage_plan(self, candidate, context, stage: int) -> EvaluationPlan:
        del candidate, context
        self.stages.append(stage)
        return EvaluationPlan(commands=[])


@pytest.fixture
def candidate() -> CandidateArtifact:
    return CandidateArtifact(
        candidate_id="candidate",
        source_hash="source",
        manifest_hash=None,
        language="python",
    )


@pytest.fixture
def context() -> EvaluationContext:
    return EvaluationContext(
        experiment_id="experiment",
        evaluator_version_id="fake-evaluator@1",
        environment_version_id="fake-sandbox@1",
        seed=7,
    )


def test_repeated_benchmark_uses_robust_aggregate_and_keeps_raw_evidence(
    candidate: CandidateArtifact,
    context: EvaluationContext,
) -> None:
    sandbox = _Sandbox([1.0, 100.0, 2.0])
    service = EvaluationService(
        _Evaluator(),
        sandbox,
        _Artifacts(),
        repetitions=3,
    )

    outcome = service.evaluate(
        candidate,
        context,
        SandboxPolicy(),
        extra_metrics={
            "candidate_novelty_penalty": 0.4,
            "candidate_novelty_objective": 0.2,
        },
    )

    assert sandbox.calls == 3
    assert outcome.output.score == 2.0
    assert outcome.output.metrics["benchmark_scores"] == [1.0, 100.0, 2.0]
    assert outcome.output.metrics["benchmark_median"] == 2.0
    assert outcome.output.metrics["candidate_novelty_penalty"] == 0.4
    assert outcome.output.metrics["candidate_novelty_objective"] == 0.2
    assert outcome.output.metrics["benchmark_ci_low"] <= outcome.output.score
    assert outcome.output.metrics["benchmark_ci_high"] >= outcome.output.score
    assert len(outcome.output.metrics["evaluation_stage_evidence"]) == 3
    assert len(outcome.measurements) == 3


def test_progressive_evaluation_repeats_only_benchmark_stage(
    candidate: CandidateArtifact,
    context: EvaluationContext,
) -> None:
    evaluator = _ProgressiveEvaluator()
    sandbox = _Sandbox([1.0, 1.0, 1.0, 3.0, 4.0, 5.0])
    service = EvaluationService(
        evaluator,
        sandbox,
        _Artifacts(),
        progressive=True,
        repetitions=3,
    )

    outcome = service.evaluate(candidate, context, SandboxPolicy())

    assert evaluator.stages == [0, 1, 2, 3, 3, 3]
    assert [measurement.stage for measurement in outcome.measurements] == [0, 1, 2, 3, 3, 3]
    assert outcome.output.score == 4.0
    assert outcome.output.metrics["evaluation_progressive"] is True
    assert outcome.output.metrics["evaluation_early_stopped"] is False


def test_progressive_failure_early_stops_before_hidden_benchmark(
    candidate: CandidateArtifact,
    context: EvaluationContext,
) -> None:
    evaluator = _ProgressiveEvaluator()
    sandbox = _Sandbox([0.0, 99.0])
    service = EvaluationService(
        evaluator,
        sandbox,
        _Artifacts(),
        progressive=True,
        repetitions=3,
    )

    outcome = service.evaluate(candidate, context, SandboxPolicy())

    assert evaluator.stages == [0]
    assert sandbox.calls == 1
    assert outcome.early_stopped is True
    assert outcome.output.passed is False


def test_static_syntax_validation_prevents_sandbox_execution(
    candidate: CandidateArtifact,
    context: EvaluationContext,
) -> None:
    sandbox = _Sandbox([1.0])
    service = EvaluationService(
        _Evaluator(),
        sandbox,
        _InvalidArtifacts(),
    )

    outcome = service.evaluate(candidate, context, SandboxPolicy())

    assert sandbox.calls == 0
    assert outcome.early_stopped is True
    assert outcome.output.passed is False
    assert outcome.output.metrics["evaluation_integrity_findings"][0]["rule"] == (
        "static_syntax_error"
    )
    assert len(outcome.output.metrics["evaluation_stage_evidence"]) == 1
