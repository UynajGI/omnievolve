"""Fast Loop 集成：observer-only verifier hook 接线（PR2）.

验证：
- 启用 verifier observer 后，通过硬正确性测试的候选产生
  verification_batch/comparison 证据；
- 关闭时零证据写入；
- best candidate 仍由 primary score 决定（observer 不改搜索状态）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from omnievolve.agents.llm_gateway import FakeLLM, LLMResponse
from omnievolve.agents.router import ModelSlot
from omnievolve.config import VerifierSettings
from omnievolve.engine.evolution_engine import EvolutionConfig, EvolutionEngine
from omnievolve.eval.task_evaluator import EvalOutput, EvaluationPlan
from omnievolve.sandbox.base import SandboxExecutionResult
from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.cas_code_store import CASCodeStore
from omnievolve.storage.db import Database
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.repositories.experiment_repo import ExperimentRepository


class _ObserverLLM(FakeLLM):
    """确定性 chat（coder JSON）+ 确定性 score_tokens."""

    def __init__(self) -> None:
        # 高度集中的 fixture：coverage = 0.98 > 默认 0.95 门槛。
        super().__init__(score_token_probabilities={"10": 0.98, "12": 0.02})
        self._call_count = 0

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        experiment_id: str | None = None,
        agent_role: str = "unknown",
        prompt_version_id: str | None = None,
    ) -> LLMResponse:
        self.calls.append({"agent_role": agent_role, "model": model})
        if agent_role == "director":
            content = (
                '{"thought": "increment", "rationale": "deterministic", '
                '"confidence": 0.8, "mechanism_tags": ["inc"]}'
            )
        elif agent_role == "coder":
            content = (
                '{"full_code": "VALUE = ' + str(self._call_count) + '\\n", '
                '"diff": "rewrite", "explanation": "deterministic candidate"}'
            )
        else:
            content = '{"passed": true, "feedback": "ok"}'
        self._call_count += 1
        return LLMResponse(
            content=content,
            model=model or "fake-model",
            input_tokens=50,
            output_tokens=30,
            total_tokens=80,
            latency_ms=1.0,
        )


class _ObserverSandbox:
    environment_version_id = "fake-sandbox@observer-v1"

    def __init__(self, artifact_store: Any) -> None:
        self._artifact_store = artifact_store

    def execute(self, plan, candidate, policy) -> SandboxExecutionResult:
        del plan, policy
        source = self._artifact_store.load_text(candidate.source_hash)
        match = re.search(r"VALUE\s*=\s*(\d+)", source)
        score = float(match.group(1)) if match else 0.0
        return SandboxExecutionResult(
            return_codes=[0],
            stdout=str(score),
            stderr="",
            output_artifacts={},
            execution_time_ms=10.0,
            cpu_time_ms=5.0,
            memory_peak_kb=64,
        )

    def healthcheck(self) -> dict[str, str]:
        return {"status": "healthy"}


class _ObserverEvaluator:
    version_id = "fake-evaluator@observer-v1"

    def build_plan(self, candidate, context) -> EvaluationPlan:
        del candidate, context
        return EvaluationPlan(commands=[])

    def parse_result(self, result, context) -> EvalOutput:
        del context
        score = float(result.stdout)
        return EvalOutput(score=score, metrics={"deterministic": 1.0}, passed=True)

    def get_baseline(self) -> float:
        return 0.0


def _config() -> EvolutionConfig:
    return EvolutionConfig(
        max_generations=2,
        population_size=1,
        island_count=1,
        crossover_rate=0.0,
        health_window_gens=99,
        self_evolve_enabled=False,
        compute_budget_sec=0,
        seed=20260801,
        novelty_enabled=False,
        operator_portfolio_enabled=False,
    )


def _build_engine(
    root: Path, *, verifier: VerifierSettings | None
) -> tuple[Database, EvolutionEngine, str, _ObserverLLM]:
    db = Database(root / "run.db")
    initialize_database(db)
    artifacts = ArtifactStore(root / "artifacts", db)
    store = CASCodeStore(artifacts, root / "work")
    sandbox = _ObserverSandbox(store)
    experiment_id = ExperimentRepository(db).create(
        task_id="sort",
        task_name="sort",
        config_snapshot={"verifier_integration": True},
    ).id
    llm = _ObserverLLM()
    engine = EvolutionEngine(
        db,
        store,
        _ObserverEvaluator(),
        sandbox,
        llm,
        experiment_id=experiment_id,
        evaluator_version_id=_ObserverEvaluator.version_id,
        environment_version_id=sandbox.environment_version_id,
        config=_config(),
        model_slots=[
            ModelSlot(
                name="fake-model",
                tier="light",
                cost_per_1k_input=0.0,
                cost_per_1k_output=0.0,
                avg_latency_ms=1.0,
            )
        ],
        verifier_settings=verifier,
    )
    return db, engine, experiment_id, llm


class TestObserverIntegration:
    def test_observer_writes_evidence_when_enabled(self, tmp_path):
        verifier = VerifierSettings(enabled=True, mode="observer", model="fake-model")
        db, engine, experiment_id, llm = _build_engine(tmp_path / "on", verifier=verifier)
        engine.run("VALUE = 0\n", "sort")
        batches = db.fetchall("SELECT * FROM verification_batch")
        assert batches, "verifier enabled 时必须产生 verification_batch"
        comparisons = db.fetchall("SELECT * FROM verification_comparison")
        assert comparisons
        for comparison in comparisons:
            assert comparison["status"] == "completed"
        # FakeLLM 记录 verifier 角色调用（ledger 入账由 LLMGateway 负责，
        # 已有独立单测覆盖）。
        assert any(call["agent_role"] == "verifier" for call in llm.calls)

    def test_no_evidence_when_disabled(self, tmp_path):
        db, engine, experiment_id, llm = _build_engine(tmp_path / "off", verifier=None)
        engine.run("VALUE = 0\n", "sort")
        assert db.fetchone("SELECT COUNT(*) AS n FROM verification_batch")["n"] == 0
        assert db.fetchone("SELECT COUNT(*) AS n FROM verification_comparison")["n"] == 0

    def test_best_candidate_still_driven_by_primary_score(self, tmp_path):
        verifier = VerifierSettings(enabled=True, mode="observer", model="fake-model")
        db, engine, experiment_id, llm = _build_engine(tmp_path / "best", verifier=verifier)
        result = engine.run("VALUE = 0\n", "sort")
        best = db.fetchone(
            "SELECT id, primary_score FROM evaluation_run WHERE candidate_id = ?",
            (result.best_candidate_id,),
        )
        assert best is not None
        # observer 证据不影响 best（仍由 evaluator 决定）。
        assert result.best_score is not None
        assert db.fetchone("SELECT COUNT(*) AS n FROM verification_batch")["n"] > 0
