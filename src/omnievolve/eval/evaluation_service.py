"""Unified, auditable candidate evaluation pipeline."""

from __future__ import annotations

import ast
import statistics
from dataclasses import dataclass
from typing import Any, cast

from omnievolve.eval.anti_cheat import (
    AntiCheatFinding,
    scan_candidate_source,
    verify_hidden_mounts,
)
from omnievolve.eval.benchmark_stats import summarize_samples
from omnievolve.eval.plan_validator import EvaluationPlanValidator, EvaluationStage
from omnievolve.eval.task_evaluator import EvalOutput, EvaluationContext, TaskEvaluator
from omnievolve.sandbox.base import (
    CandidateArtifact,
    SandboxBackend,
    SandboxExecutionResult,
    SandboxPolicy,
)


@dataclass(frozen=True)
class EvaluationMeasurement:
    """One stage/repetition measurement."""

    stage: int
    repetition: int
    score: float
    passed: bool
    execution_time_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "repetition": self.repetition,
            "score": self.score,
            "passed": self.passed,
            "execution_time_ms": self.execution_time_ms,
        }


@dataclass(frozen=True)
class EvaluationOutcome:
    """Pure evaluation result; shared-state commit happens elsewhere."""

    output: EvalOutput
    results: tuple[SandboxExecutionResult, ...]
    measurements: tuple[EvaluationMeasurement, ...]
    early_stopped: bool = False

    @property
    def last_result(self) -> SandboxExecutionResult | None:
        return self.results[-1] if self.results else None

    @property
    def total_execution_time_ms(self) -> float:
        return sum(result.execution_time_ms for result in self.results)

    @property
    def execution_time_ms(self) -> float:
        """Compatibility alias consumed by budget accounting."""
        return self.total_execution_time_ms

    @property
    def memory_peak_kb(self) -> int:
        return max((result.memory_peak_kb for result in self.results), default=0)

    @property
    def cpu_time_ms(self) -> float:
        return sum(result.cpu_time_ms for result in self.results)

    @property
    def stdout(self) -> str:
        return self.last_result.stdout if self.last_result else ""

    @property
    def stderr(self) -> str:
        return self.last_result.stderr if self.last_result else ""


class EvaluationService:
    """Run validation, anti-cheat, progressive stages and repeated benchmark.

    The service deliberately does not mutate repositories, archives or search
    state.  Both synchronous evaluation and prepare/commit use this same entry.
    """

    def __init__(
        self,
        evaluator: TaskEvaluator,
        sandbox: SandboxBackend,
        artifact_store: Any,
        *,
        progressive: bool = False,
        repetitions: int = 1,
        confidence: float = 0.95,
    ) -> None:
        if repetitions < 1:
            raise ValueError("evaluation repetitions must be positive")
        if not 0.0 < confidence < 1.0:
            raise ValueError("evaluation confidence must be between 0 and 1")
        self._evaluator = evaluator
        self._sandbox = sandbox
        self._artifact_store = artifact_store
        self._progressive = progressive
        self._repetitions = repetitions
        self._confidence = confidence

    def evaluate(
        self,
        candidate: CandidateArtifact,
        context: EvaluationContext,
        policy: SandboxPolicy,
        *,
        extra_metrics: dict[str, object] | None = None,
    ) -> EvaluationOutcome:
        """Execute the complete evaluation policy through one entry point."""
        source = self._artifact_store.load_text(candidate.source_hash) or ""
        build_stage = getattr(self._evaluator, "build_stage_plan", None)
        stages: tuple[EvaluationStage | None, ...]
        if self._progressive and build_stage is not None:
            stages = tuple(EvaluationStage)
        else:
            stages = (None,)

        results: list[SandboxExecutionResult] = []
        outputs: list[EvalOutput] = []
        measurements: list[EvaluationMeasurement] = []
        stage_evidence: list[dict[str, object]] = []
        early_stopped = False

        for stage in stages:
            repeat_count = (
                self._repetitions
                if stage is None or stage == EvaluationStage.STAGE_3_BENCHMARK
                else 1
            )
            stage_outputs: list[EvalOutput] = []
            for repetition in range(repeat_count):
                plan = (
                    build_stage(candidate, context, stage.value)
                    if stage is not None and build_stage is not None
                    else self._evaluator.build_plan(candidate, context)
                )
                if plan is None:
                    plan = self._evaluator.build_plan(candidate, context)
                evidence = {
                    "stage": stage.value if stage is not None else 3,
                    "repetition": repetition,
                    "resource_profile": plan.resource_profile,
                    "hidden_mounts": [
                        {
                            "target": mount.target,
                            "read_only": mount.read_only,
                            "integrity_sha256": mount.integrity_sha256,
                        }
                        for mount in plan.mounts
                        if mount.visibility == "hidden"
                    ],
                }
                stage_evidence.append(evidence)
                findings = self._validate(plan, source, candidate.language)
                if findings:
                    reason = "; ".join(
                        f"{finding.rule}: {finding.detail}" for finding in findings[:5]
                    )
                    output = EvalOutput(
                        score=0.0,
                        metrics=cast(
                            dict[str, float],
                            {
                                "anti_cheat_findings": float(len(findings)),
                                "evaluation_integrity_findings": [
                                    {
                                        "rule": finding.rule,
                                        "detail": finding.detail,
                                    }
                                    for finding in findings
                                ],
                                "evaluation_stage_evidence": stage_evidence,
                                **(extra_metrics or {}),
                            },
                        ),
                        passed=False,
                        failure_reason=f"Evaluation integrity check failed: {reason}",
                        confidence=1.0,
                    )
                    return EvaluationOutcome(
                        output=output,
                        results=tuple(results),
                        measurements=tuple(measurements),
                        early_stopped=True,
                    )

                result = self._sandbox.execute(plan, candidate, policy)
                output = self._evaluator.parse_result(result, context)
                results.append(result)
                stage_outputs.append(output)
                measurements.append(
                    EvaluationMeasurement(
                        stage=stage.value if stage is not None else 3,
                        repetition=repetition,
                        score=output.score,
                        passed=output.passed,
                        execution_time_ms=result.execution_time_ms,
                    )
                )
            stage_output = self._aggregate(stage_outputs, extra_metrics=extra_metrics)
            outputs.append(stage_output)
            if not stage_output.passed and (
                stage is None or stage < EvaluationStage.STAGE_3_BENCHMARK
            ):
                early_stopped = True
                break

        final_output = outputs[-1]
        metrics: dict[str, object] = {
            **final_output.metrics,
            "evaluation_progressive": self._progressive and build_stage is not None,
            "evaluation_repetitions": (
                self._repetitions if len(stages) == 1 or len(outputs) == len(stages) else 1
            ),
            "evaluation_early_stopped": early_stopped,
            "evaluation_measurements": [item.to_dict() for item in measurements],
            "evaluation_stage_evidence": stage_evidence,
        }
        final_output = EvalOutput(
            score=final_output.score,
            metrics=metrics,  # type: ignore[arg-type]
            passed=final_output.passed,
            failure_reason=final_output.failure_reason,
            confidence=final_output.confidence,
        )
        return EvaluationOutcome(
            output=final_output,
            results=tuple(results),
            measurements=tuple(measurements),
            early_stopped=early_stopped,
        )

    @staticmethod
    def _validate(
        plan: Any,
        source: str,
        language: str = "python",
    ) -> list[AntiCheatFinding]:
        findings: list[AntiCheatFinding] = []
        if language.lower() in {"python", "py"}:
            try:
                ast.parse(source)
            except SyntaxError as exc:
                findings.append(
                    AntiCheatFinding(
                        "static_syntax_error",
                        f"line {exc.lineno or 0}: {exc.msg}",
                    )
                )
        try:
            if plan.commands:
                EvaluationPlanValidator().validate(plan)
            return findings + verify_hidden_mounts(plan) + scan_candidate_source(source)
        except Exception as exc:
            return findings + [AntiCheatFinding("invalid_evaluation_plan", str(exc))]

    def _aggregate(
        self,
        outputs: list[EvalOutput],
        *,
        extra_metrics: dict[str, object] | None,
    ) -> EvalOutput:
        if not outputs:
            raise RuntimeError("evaluation stage produced no measurements")
        scores = [output.score for output in outputs]
        passed = all(output.passed for output in outputs)
        metrics: dict[str, object] = {
            **outputs[-1].metrics,
            **(extra_metrics or {}),
        }
        if len(scores) > 1:
            summary = summarize_samples(scores, confidence=self._confidence, seed=0)
            metrics.update(
                {
                    "benchmark_scores": list(scores),
                    "benchmark_median": summary.median,
                    "benchmark_mean": summary.mean,
                    "benchmark_stdev": summary.stdev,
                    "benchmark_ci_low": summary.ci_low,
                    "benchmark_ci_high": summary.ci_high,
                }
            )
        failure_reason = next(
            (output.failure_reason for output in outputs if not output.passed),
            outputs[-1].failure_reason,
        )
        return EvalOutput(
            score=float(statistics.median(scores)),
            metrics=metrics,  # type: ignore[arg-type]
            passed=passed,
            failure_reason=failure_reason,
            confidence=self._confidence if len(scores) > 1 else outputs[-1].confidence,
        )


__all__ = [
    "EvaluationMeasurement",
    "EvaluationOutcome",
    "EvaluationService",
]
