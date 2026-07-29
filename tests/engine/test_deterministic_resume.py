from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from omnievolve.agents.llm_gateway import LLMResponse
from omnievolve.agents.router import ModelSlot
from omnievolve.engine.evolution_engine import EvolutionConfig, EvolutionEngine
from omnievolve.engine.policy_canary import LocalPolicyArmRunner
from omnievolve.eval.task_evaluator import EvalOutput
from omnievolve.meta.policy_archive import PolicyArchive
from omnievolve.meta.policy_genome import SearchPolicyGenome
from omnievolve.meta.policy_replay import PolicyReplayRequest
from omnievolve.sandbox.base import EvaluationPlan, SandboxExecutionResult
from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.cas_code_store import CASCodeStore
from omnievolve.storage.db import Database
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.repositories.experiment_repo import ExperimentRepository

pytestmark = pytest.mark.e2e


class _DeterministicLLM:
    """Role-aware fake whose checkpointed call count determines every output."""

    def __init__(self) -> None:
        self._call_count = 0
        self.fork_kwargs: list[dict[str, Any]] = []

    def fork(self, db: Database, **kwargs: Any):
        del db
        self.fork_kwargs.append(kwargs)
        return type(self)()

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        agent_role: str = "unknown",
        **kwargs: Any,
    ) -> LLMResponse:
        del messages, kwargs
        self._call_count += 1
        if agent_role == "director":
            content = json.dumps(
                {
                    "thought": f"deterministic idea {self._call_count}",
                    "rationale": "exercise deterministic replay",
                    "confidence": 0.8,
                    "mechanism_tags": [f"step-{self._call_count}"],
                }
            )
        elif agent_role == "coder":
            content = json.dumps(
                {
                    "full_code": f"VALUE = {self._call_count}\n",
                    "diff": "rewrite",
                    "explanation": "deterministic candidate",
                }
            )
        else:
            content = '{"passed": true, "feedback": "ok"}'
        return LLMResponse(
            content=content,
            model=model or "fake-model",
            input_tokens=11,
            output_tokens=7,
            total_tokens=18,
            latency_ms=1.0,
        )


class _FailingLLM(_DeterministicLLM):
    def fork(self, db: Database, **kwargs: Any):
        del db
        self.fork_kwargs.append(kwargs)
        return type(self)()

    def chat(self, *args: Any, **kwargs: Any) -> LLMResponse:
        del args, kwargs
        raise RuntimeError("provider unavailable")


class _DeterministicSandbox:
    environment_version_id = "fake-sandbox@deterministic-v1"

    def __init__(self, artifact_store: Any) -> None:
        self._artifact_store = artifact_store

    def fork(self, *, artifact_store: Any, work_dir: str | Path):
        del work_dir
        return type(self)(artifact_store)

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


class _DeterministicEvaluator:
    version_id = "fake-evaluator@deterministic-v1"

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
        max_generations=3,
        population_size=1,
        island_count=1,
        crossover_rate=0.0,
        health_window_gens=99,
        self_evolve_enabled=False,
        compute_budget_sec=0,
        seed=20260729,
        qd_archive_enabled=True,
        qd_parent_probability=1.0,
        operator_portfolio_enabled=True,
    )


def _open_run(root: Path, experiment_id: str | None = None):
    db = Database(root / "run.db")
    initialize_database(db)
    artifacts = ArtifactStore(root / "artifacts", db)
    store = CASCodeStore(artifacts, root / "work")
    sandbox = _DeterministicSandbox(store)
    if experiment_id is None:
        experiment_id = ExperimentRepository(db).create(
            task_id="sort",
            task_name="sort",
            config_snapshot={"deterministic_replay": True},
        ).id
    engine = EvolutionEngine(
        db,
        store,
        _DeterministicEvaluator(),
        sandbox,
        _DeterministicLLM(),
        experiment_id=experiment_id,
        evaluator_version_id=_DeterministicEvaluator.version_id,
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
        policy_archive=PolicyArchive(db),
    )
    return db, engine, experiment_id


def _normalized_state(db: Database, experiment_id: str) -> dict[str, Any]:
    candidate_rows = db.fetchall(
        """
        SELECT c.id, c.generation, c.artifact_hash, c.manifest_hash, c.status,
               er.primary_score, er.passed
        FROM candidate c
        LEFT JOIN evaluation_run er ON er.candidate_id = c.id
        WHERE c.experiment_id = ? AND c.status != 'aborted'
        ORDER BY c.generation, c.artifact_hash, er.id
        """,
        (experiment_id,),
    )
    id_to_hash = {row["id"]: row["artifact_hash"] for row in candidate_rows}
    candidates = [
        (
            int(row["generation"]),
            row["artifact_hash"],
            row["manifest_hash"],
            row["status"],
            row["primary_score"],
            row["passed"],
        )
        for row in candidate_rows
    ]
    lineage = [
        (
            id_to_hash[row["child_id"]],
            id_to_hash[row["parent_id"]],
            row["relation_type"],
            int(row["parent_order"]),
        )
        for row in db.fetchall(
            """
            SELECT cl.child_id, cl.parent_id, cl.relation_type, cl.parent_order
            FROM candidate_lineage cl
            JOIN candidate c ON c.id = cl.child_id
            WHERE c.experiment_id = ?
            ORDER BY c.generation, cl.parent_order
            """,
            (experiment_id,),
        )
    ]
    experiment = db.fetchone(
        "SELECT checkpoint_data FROM experiment WHERE id = ?",
        (experiment_id,),
    )
    checkpoint = json.loads(experiment["checkpoint_data"])
    runtime = checkpoint["runtime_state"]
    behavior_archive = runtime["behavior_archive"]
    for cells in behavior_archive.get("cells", {}).values():
        for payload in cells.values():
            payload["candidate_id"] = id_to_hash[payload["candidate_id"]]
    stable_checkpoint = {
        "schema_version": checkpoint["schema_version"],
        "generation": checkpoint["generation"],
        "total_candidates": checkpoint["total_candidates"],
        "recent_scores": checkpoint["recent_scores"],
        "failed_directions": checkpoint["failed_directions"],
        "python_random_state": runtime["python_random_state"],
        "router": runtime["router"],
        "budget": runtime["budget"],
        "search_policy": runtime["search_policy"],
        "novelty_gate": runtime["novelty_gate"],
        "behavior_archive": behavior_archive,
        "operator_portfolio": runtime["operator_portfolio"],
        "selection_mode": runtime["selection_mode"],
        "slow_loop_triggered": runtime["slow_loop_triggered"],
    }
    return {
        "candidates": candidates,
        "lineage": lineage,
        "checkpoint": stable_checkpoint,
    }


def test_run_equals_interrupted_then_resumed_run(tmp_path: Path) -> None:
    full_db, full_engine, full_experiment = _open_run(tmp_path / "full")
    full_engine.run("VALUE = 0\n", "sort")
    full_state = _normalized_state(full_db, full_experiment)
    full_db.close_all()

    split_root = tmp_path / "split"
    split_db, split_engine, split_experiment = _open_run(split_root)
    original_step = split_engine._step_generation

    def stop_after_first_commit(generation: int, task_name: str) -> None:
        original_step(generation, task_name)
        if generation == 1:
            split_engine._shutdown_requested = True

    split_engine._step_generation = stop_after_first_commit
    split_engine.run("VALUE = 0\n", "sort")
    split_db.close_all()

    resumed_db, resumed_engine, _ = _open_run(split_root, split_experiment)
    resumed_engine.resume(split_experiment)
    resumed_state = _normalized_state(resumed_db, split_experiment)
    resumed_db.close_all()

    assert resumed_state == full_state
    assert resumed_state["checkpoint"]["budget"]["compute_budget_sec"] is None
    rewards = resumed_state["checkpoint"]["router"]["rewards"]
    assert rewards["director"]["fake-model"]
    assert rewards["coder"]["fake-model"]
    assert not rewards.get("critic", {}).get("fake-model", [])


def test_local_policy_arm_uses_isolated_cas_sandbox(tmp_path: Path) -> None:
    db = Database(tmp_path / "source.db")
    initialize_database(db)
    artifacts = ArtifactStore(tmp_path / "source-artifacts", db)
    store = CASCodeStore(artifacts, tmp_path / "source-work")
    frontier_ref = store.store_snapshot("VALUE = 0\n", message="frozen frontier")
    llm = _DeterministicLLM()
    runner = LocalPolicyArmRunner(
        source_store=store,
        task_evaluator=_DeterministicEvaluator(),
        sandbox=_DeterministicSandbox(store),
        llm=llm,
        evolution_config=_config(),
        model_slots=[],
    )
    policy = SearchPolicyGenome()
    request = PolicyReplayRequest(
        experiment_id="source-experiment",
        champion_policy_id="champion",
        challenger_policy_id="challenger",
        champion=policy,
        challenger=policy,
        snapshot_id="frozen-frontier-sha256",
        seeds=(3, 5, 7),
        token_budget_per_arm=3_000,
        wall_budget_sec_per_arm=90.0,
        task_name="sort",
        frontier_refs=(frontier_ref,),
        generations_per_seed=1,
    )

    result = runner.run_arm(
        request=request,
        policy=policy,
        policy_id="champion",
        seed=3,
        arm="champion",
    )

    assert result.integrity_passed is True
    assert result.anti_cheat_passed is True
    assert result.frontier_auc >= 0.0
    assert result.success_rate == 1.0
    assert len(llm.fork_kwargs) == 1
    assert llm.fork_kwargs[0]["max_retries"] == 1
    assert llm.fork_kwargs[0]["request_timeout"] == 24.0
    assert llm.fork_kwargs[0]["deadline_monotonic"] > 0
    db.close_all()


def test_local_policy_arm_closes_database_when_provider_fails(tmp_path: Path) -> None:
    db = Database(tmp_path / "source.db")
    initialize_database(db)
    artifacts = ArtifactStore(tmp_path / "source-artifacts", db)
    store = CASCodeStore(artifacts, tmp_path / "source-work")
    frontier_ref = store.store_snapshot("VALUE = 0\n", message="frozen frontier")
    runner = LocalPolicyArmRunner(
        source_store=store,
        task_evaluator=_DeterministicEvaluator(),
        sandbox=_DeterministicSandbox(store),
        llm=_FailingLLM(),
        evolution_config=_config(),
        model_slots=[],
    )
    policy = SearchPolicyGenome()
    request = PolicyReplayRequest(
        experiment_id="source-experiment",
        champion_policy_id="champion",
        challenger_policy_id="challenger",
        champion=policy,
        challenger=policy,
        snapshot_id="frozen-frontier-sha256",
        seeds=(3, 5, 7),
        token_budget_per_arm=3_000,
        wall_budget_sec_per_arm=90.0,
        task_name="sort",
        frontier_refs=(frontier_ref,),
        generations_per_seed=1,
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        runner.run_arm(
            request=request,
            policy=policy,
            policy_id="champion",
            seed=3,
            arm="champion",
        )

    db.close_all()
