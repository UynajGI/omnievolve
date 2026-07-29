"""Isolated single-machine execution adapter for policy canary arms."""

from __future__ import annotations

import json
import math
import statistics
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from omnievolve.meta.policy_replay import (
    PolicyArmResult,
    PolicyReplayRequest,
)
from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.cas_code_store import CASCodeStore
from omnievolve.storage.db import Database
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.repositories.experiment_repo import ExperimentRepository


class LocalPolicyArmRunner:
    """Run every arm in a fresh DB and CAS over the same frozen frontier."""

    def __init__(
        self,
        *,
        source_store: Any,
        task_evaluator: Any,
        sandbox: Any,
        llm: Any,
        evolution_config: Any,
        model_slots: list[Any] | None = None,
    ) -> None:
        if getattr(source_store, "backend_name", None) != "cas":
            raise ValueError("production policy canary currently requires the CAS backend")
        if not hasattr(llm, "fork"):
            raise ValueError("policy canary LLM must support independent fork() contexts")
        if not hasattr(sandbox, "fork"):
            raise ValueError("policy canary sandbox must support isolated fork() contexts")
        self._source_store = source_store
        self._task_evaluator = task_evaluator
        self._sandbox = sandbox
        self._llm = llm
        self._config = evolution_config
        self._model_slots = list(model_slots or [])

    def run_arm(
        self,
        *,
        request: PolicyReplayRequest,
        policy: Any,
        policy_id: str,
        seed: int,
        arm: str,
    ) -> PolicyArmResult:
        del arm
        if not request.frontier_refs:
            raise ValueError("policy canary request has no frozen frontier artifacts")
        if not request.task_name:
            raise ValueError("policy canary request has no task name")

        # Paired seeds deterministically sample the same frozen frontier member
        # in each arm. Across seeds the canary covers more than only the champion.
        frontier_ref = request.frontier_refs[seed % len(request.frontier_refs)]
        if not self._source_store.exists(frontier_ref):
            raise ValueError(f"frozen frontier artifact is missing: {frontier_ref}")
        if hasattr(self._source_store, "load_snapshot_files"):
            initial_code: str | dict[str, str] = self._source_store.load_snapshot_files(
                frontier_ref
            )
        else:
            initial_code = self._source_store.load_text(frontier_ref)

        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="omnievolve-canary-") as temporary:
            root = Path(temporary)
            db = Database(root / "arm.db")
            initialize_database(db)
            local_artifacts = ArtifactStore(root / "artifacts", db)
            local_store = CASCodeStore(local_artifacts, root / "work")
            arm_llm = self._llm.fork(db)
            arm_sandbox = self._sandbox.fork(
                artifact_store=local_store,
                work_dir=root / "sandbox",
            )
            experiment = ExperimentRepository(db).create(
                task_id=request.task_name,
                task_name=request.task_name,
                config_snapshot={
                    "policy_canary": True,
                    "snapshot_id": request.snapshot_id,
                    "policy_id": policy_id,
                    "seed": seed,
                },
            )
            arm_config = replace(
                self._config,
                max_generations=request.generations_per_seed,
                self_evolve_enabled=False,
                token_budget=request.token_budget_per_seed,
                compute_budget_sec=request.wall_budget_sec_per_seed,
                seed=seed,
            )
            from omnievolve.engine.evolution_engine import EvolutionEngine

            engine = EvolutionEngine(
                db,
                local_store,
                self._task_evaluator,
                arm_sandbox,
                arm_llm,
                experiment_id=experiment.id,
                evaluator_version_id=getattr(self._task_evaluator, "version_id", ""),
                environment_version_id=getattr(arm_sandbox, "environment_version_id", ""),
                config=arm_config,
                search_policy=policy,
                model_slots=self._model_slots,
                policy_replay_executor=None,
            )
            engine.run(initial_code, request.task_name)
            result = self._measure_arm(
                db,
                experiment.id,
                requested_generations=request.generations_per_seed,
            )
            db.close()
        return replace(result, wall_sec=time.monotonic() - started)

    @staticmethod
    def _measure_arm(
        db: Database,
        experiment_id: str,
        *,
        requested_generations: int,
    ) -> PolicyArmResult:
        rows = db.fetchall(
            """
            SELECT c.generation, er.primary_score, er.passed
            FROM evaluation_run er
            JOIN candidate c ON c.id = er.candidate_id
            WHERE c.experiment_id = ?
              AND c.status != 'aborted'
              AND er.status = 'completed'
              AND er.primary_score IS NOT NULL
            ORDER BY c.generation, er.id
            """,
            (experiment_id,),
        )
        if not rows:
            raise ValueError("policy canary arm produced no completed evaluation")
        generation_best: dict[int, float] = {}
        for row in rows:
            generation = int(row["generation"])
            score = float(row["primary_score"])
            generation_best[generation] = max(
                generation_best.get(generation, -float("inf")), score
            )
        running = -float("inf")
        frontier = []
        for generation in range(requested_generations + 1):
            if generation in generation_best:
                running = max(running, generation_best[generation])
            if math.isfinite(running):
                frontier.append(running)
        experiment = db.fetchone(
            "SELECT status, checkpoint_data FROM experiment WHERE id = ?",
            (experiment_id,),
        )
        checkpoint = json.loads(experiment["checkpoint_data"] or "{}") if experiment else {}
        integrity = bool(
            experiment
            and experiment["status"] == "completed"
            and int(checkpoint.get("generation", -1)) >= requested_generations
        )
        ledger = db.fetchone(
            """
            SELECT COUNT(*) AS calls, COUNT(cost_usd) AS priced,
                   COALESCE(SUM(total_tokens), 0) AS tokens, SUM(cost_usd) AS cost
            FROM llm_call_ledger WHERE experiment_id = ?
            """,
            (experiment_id,),
        )
        calls = int(ledger["calls"] if ledger else 0)
        priced = int(ledger["priced"] if ledger else 0)
        cost = (
            float(ledger["cost"] or 0.0)
            if calls == priced
            else None
        )
        return PolicyArmResult(
            frontier_auc=statistics.fmean(frontier),
            best_score=max(float(row["primary_score"]) for row in rows),
            success_rate=statistics.fmean(float(bool(row["passed"])) for row in rows),
            tokens=int(ledger["tokens"] if ledger else 0),
            wall_sec=0.0,
            cost_usd=cost,
            integrity_passed=integrity,
            anti_cheat_passed=True,
        )
