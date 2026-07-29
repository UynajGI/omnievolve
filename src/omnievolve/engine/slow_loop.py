"""Slow Loop Controller — 提取自 EvolutionEngine.

T1 重构第二步：将 Slow Loop 逻辑从引擎中分离。
包含：健康评估 → 提议动作 → 治理分级 → Challenger 实验 → promote/reject。

引擎持有它的实例并委托调用。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from typing import TYPE_CHECKING

from omnievolve.meta.governance import MetaAction
from omnievolve.storage.repositories.base import generate_id

if TYPE_CHECKING:
    from omnievolve.eval.telemetry import SelfEvaluator
    from omnievolve.meta.governance import (
        GovernancePolicy,
        L0PolicyMutator,
        MetaPlanner,
        ReplayEvaluator,
    )
    from omnievolve.meta.policy_archive import PolicyArchive
    from omnievolve.meta.policy_genome import SearchPolicyGenome
    from omnievolve.meta.policy_replay import PolicyReplayExecutor
    from omnievolve.storage.artifact_store import ArtifactStore
    from omnievolve.storage.db import Database
    from omnievolve.storage.repositories.experiment_repo import ExperimentRepository
    from omnievolve.storage.repositories.prompt_repo import PromptVersionRepository

logger = logging.getLogger(__name__)

_MIN_CANARY_TOKENS_PER_SEED = 50_000


class SlowLoopController:
    """Slow Loop 控制器 — 策略窗口评估与受控元进化.

    每次调用 run_slow_loop() 执行完整周期：
    TelemetryAggregator → HealthPolicy → MetaPlanner → Governance → Champion/Challenger
    """

    def __init__(
        self,
        db: Database,
        *,
        self_evaluator: SelfEvaluator | None,
        meta_planner: MetaPlanner | None,
        governance: GovernancePolicy,
        l0_mutator: L0PolicyMutator,
        replay_evaluator: ReplayEvaluator,
        policy_archive: PolicyArchive,
        experiment_repo: ExperimentRepository,
        prompt_repo: PromptVersionRepository,
        artifact_store: ArtifactStore,
        policy_replay_executor: PolicyReplayExecutor | None = None,
    ) -> None:
        self._db = db
        self._self_evaluator = self_evaluator
        self._meta_planner = meta_planner
        self._governance = governance
        self._l0_mutator = l0_mutator
        self._replay_evaluator = replay_evaluator
        self._policy_archive = policy_archive
        self._experiment_repo = experiment_repo
        self._prompt_repo = prompt_repo
        self._artifact_store = artifact_store
        self._policy_replay_executor = policy_replay_executor

    def run(
        self,
        experiment_id: str,
        current_gen: int,
        health_window_gens: int,
        search_policy: SearchPolicyGenome,
        recent_scores: list[float],
        champion_policy_id: str,
        coder_system_prompt: str,
    ) -> tuple[SearchPolicyGenome | None, str | None, bool]:
        """执行 Slow Loop.

        Returns:
            (new_policy if promoted else None,
             new_champion_id if promoted else None,
             triggered)
        """
        if self._self_evaluator is None:
            return None, None, False

        window_start = max(0, current_gen - health_window_gens)
        try:
            health = self._self_evaluator.assess(experiment_id, window_start, current_gen)
        except Exception:
            logger.exception("Slow Loop telemetry failed at gen %d", current_gen)
            return None, None, False

        logger.info(
            "Slow Loop gen %d: alert=%s roi=%.4f trigger=%s",
            current_gen,
            health.alert_level.value,
            health.roi_score,
            health.should_trigger_meta,
        )

        if not health.should_trigger_meta:
            return None, None, True  # triggered but no meta needed

        if self._meta_planner is None:
            return None, None, True

        actions = self._meta_planner.propose(
            {
                "coverage_entropy": health.coverage_entropy,
                "pollution_ratio": health.pollution_ratio,
                "roi_score": health.roi_score,
            },
            search_policy,
            [],
        )

        promoted_policy = None
        promoted_id = None

        for action in actions:
            new_policy, new_id = self._apply_meta_action(
                action,
                current_gen,
                experiment_id,
                search_policy,
                champion_policy_id,
                recent_scores,
                health_window_gens,
                coder_system_prompt,
            )
            if new_policy is not None:
                promoted_policy = new_policy
                promoted_id = new_id

        return promoted_policy, promoted_id, True

    def _apply_meta_action(
        self,
        action: MetaAction,
        current_gen: int,
        experiment_id: str,
        search_policy: SearchPolicyGenome,
        champion_policy_id: str,
        recent_scores: list[float],
        health_window_gens: int,
        coder_system_prompt: str,
    ) -> tuple[SearchPolicyGenome | None, str | None]:
        """应用单个元进化动作。"""
        can_apply, reason = self._governance.can_apply(action)

        if not can_apply:
            logger.info("Meta action %s rejected: %s", action.target, reason)
            return None, None

        if action.action_type == "modify_field":
            return self._apply_modify_field(
                action,
                current_gen,
                experiment_id,
                search_policy,
                champion_policy_id,
                recent_scores,
                health_window_gens,
            )
        elif action.action_type == "evolve_prompt":
            self._apply_evolve_prompt(action, experiment_id, coder_system_prompt)
            return None, None

        return None, None

    def _apply_modify_field(
        self,
        action: MetaAction,
        current_gen: int,
        experiment_id: str,
        search_policy: SearchPolicyGenome,
        champion_policy_id: str,
        recent_scores: list[float],
        health_window_gens: int,
    ) -> tuple[SearchPolicyGenome | None, str | None]:
        """modify_field 动作 — L0 策略变异 + Challenger 实验."""
        new_genome, mut_reason = self._l0_mutator.mutate(
            search_policy, action.target, action.new_value
        )
        if new_genome is None:
            logger.info("Mutation failed: %s", mut_reason)
            return None, None
        from omnievolve.meta.policy_runtime import validate_policy_change

        live, inactive_changes = validate_policy_change(search_policy, new_genome)
        if not live:
            logger.warning(
                "Mutation rejected because inactive fields changed: %s",
                ", ".join(inactive_changes),
            )
            return None, None

        challenger = self._policy_archive.create_policy(
            new_genome,
            experiment_id=experiment_id,
            parent_policy_id=champion_policy_id,
            risk_level=self._governance.classify_action(action).value,
        )
        self._db.execute(
            "UPDATE search_policy_version SET status='challenger' WHERE id=?",
            (challenger.id,),
        )

        from omnievolve.meta.policy_replay import PolicyReplayRequest

        replay_seeds = tuple(range(max(3, health_window_gens)))
        frontier_refs = self._freeze_frontier(experiment_id, current_gen)
        snapshot_id = f"{experiment_id}:generation:{current_gen}"
        if frontier_refs:
            digest = hashlib.sha256("\n".join(frontier_refs).encode()).hexdigest()[:16]
            snapshot_id = f"{snapshot_id}:frontier:{digest}"
        experiment = self._experiment_repo.get(experiment_id)
        task_name = (
            experiment.task_name
            if experiment is not None and isinstance(experiment.task_name, str)
            else ""
        )
        requested_token_budget = max(
            1,
            int(100_000 * self._replay_evaluator._budget_ratio),
        )
        # A canary seed executes both Director and Coder. Their combined input
        # and output usage can legitimately exceed one model's 16k output cap,
        # so preserve the configured fraction while guaranteeing an executable
        # per-seed envelope. Champion and challenger still receive identical
        # ceilings, and PolicyReplayEvidence enforces the aggregate arm budget.
        token_budget_per_arm = max(
            requested_token_budget,
            _MIN_CANARY_TOKENS_PER_SEED * len(replay_seeds),
        )
        replay_request = PolicyReplayRequest(
            experiment_id=experiment_id,
            champion_policy_id=champion_policy_id,
            challenger_policy_id=challenger.id,
            champion=search_policy,
            challenger=new_genome,
            snapshot_id=snapshot_id,
            seeds=replay_seeds,
            token_budget_per_arm=token_budget_per_arm,
            wall_budget_sec_per_arm=float(300 * len(replay_seeds)),
            task_name=task_name,
            frontier_refs=frontier_refs,
            generations_per_seed=1,
        )
        policy_experiment_id = self._start_policy_experiment(replay_request)
        if self._policy_replay_executor is None:
            reason = "No independent equal-budget policy replay executor is configured"
            self._finish_policy_experiment(
                policy_experiment_id,
                status="failed",
                decision="reject",
                evidence={"error": reason},
            )
            self._policy_archive.reject(challenger.id, reason)
            logger.warning("Policy %s rejected: %s", challenger.id, reason)
            return None, None

        try:
            evidence = self._policy_replay_executor.run_paired(replay_request)
            evidence.validate_for(replay_request)
        except Exception as exc:
            reason = f"Independent policy replay failed validation: {exc}"
            self._finish_policy_experiment(
                policy_experiment_id,
                status="failed",
                decision="reject",
                evidence={"error": reason},
            )
            self._policy_archive.reject(challenger.id, reason)
            logger.exception("Policy %s rejected: replay failed", challenger.id)
            return None, None

        decision = self._replay_evaluator.compare_equal_budget(
            champion_scores=list(evidence.champion_scores),
            challenger_scores=list(evidence.challenger_scores),
            champion_cost_usd=evidence.champion_cost_usd,
            challenger_cost_usd=evidence.challenger_cost_usd,
            champion_wall_sec=evidence.champion_wall_sec,
            challenger_wall_sec=evidence.challenger_wall_sec,
            champion_best_scores=list(evidence.champion_best_scores),
            challenger_best_scores=list(evidence.challenger_best_scores),
            champion_success_rates=list(evidence.champion_success_rates),
            challenger_success_rates=list(evidence.challenger_success_rates),
            require_known_cost=replay_request.require_known_cost,
        )
        self._finish_policy_experiment(
            policy_experiment_id,
            status="completed",
            decision=str(decision.get("decision", "hold")),
            evidence={
                "request": {
                    "snapshot_id": replay_request.snapshot_id,
                    "seeds": list(replay_request.seeds),
                    "token_budget_per_arm": replay_request.token_budget_per_arm,
                    "wall_budget_sec_per_arm": replay_request.wall_budget_sec_per_arm,
                },
                "measurements": asdict(evidence),
                "decision": decision,
            },
        )

        if decision.get("decision") == "promote":
            self._policy_archive.promote_to_champion(challenger.id)
            self._experiment_repo.set_champion_policy(experiment_id, challenger.id)
            logger.info(
                "Policy %s promoted at gen %d: %s",
                challenger.id,
                current_gen,
                decision.get("reason"),
            )
            self._safe_tuner_feedback(action, decision.get("gain", 0.0))
            return new_genome, challenger.id
        elif decision.get("decision") == "reject":
            self._policy_archive.reject(challenger.id, decision.get("reason", ""))
            self._safe_tuner_feedback(action, decision.get("gain", -0.01))
            return None, None
        else:
            # Hold remains a challenger so more paired evidence may be attached;
            # it is never promoted automatically from an inconclusive interval.
            logger.info(
                "Policy %s held for more evidence: %s",
                challenger.id,
                decision.get("reason", ""),
            )
            self._safe_tuner_feedback(action, decision.get("gain", 0.0))
            return None, None

    def _freeze_frontier(self, experiment_id: str, current_gen: int) -> tuple[str, ...]:
        """Capture immutable, scored artifact refs for both canary arms."""
        rows = self._db.fetchall(
            """
            SELECT COALESCE(c.manifest_hash, c.artifact_hash) AS artifact_ref,
                   MAX(er.primary_score) AS score
            FROM candidate c
            JOIN evaluation_run er ON er.candidate_id = c.id
            WHERE c.experiment_id = ?
              AND c.generation <= ?
              AND c.status != 'aborted'
              AND er.status = 'completed'
              AND er.passed = 1
              AND er.primary_score IS NOT NULL
            GROUP BY c.id
            ORDER BY score DESC, c.id
            LIMIT 16
            """,
            (experiment_id, current_gen),
        )
        return tuple(str(row["artifact_ref"]) for row in rows if row["artifact_ref"])

    def _start_policy_experiment(self, request: object) -> str:
        """Persist the canary before execution so failures remain auditable."""
        policy_experiment_id = generate_id()
        self._db.execute(
            """
            INSERT INTO policy_experiment
                (id, experiment_id, champion_policy_id, challenger_policy_id,
                 evaluation_mode, budget_spec, status)
            VALUES (?, ?, ?, ?, 'canary', ?, 'running')
            """,
            (
                policy_experiment_id,
                request.experiment_id,
                request.champion_policy_id,
                request.challenger_policy_id,
                json.dumps(
                    {
                        "snapshot_id": request.snapshot_id,
                        "seeds": list(request.seeds),
                        "token_budget_per_arm": request.token_budget_per_arm,
                        "wall_budget_sec_per_arm": request.wall_budget_sec_per_arm,
                        "task_name": request.task_name,
                        "frontier_refs": list(request.frontier_refs),
                        "generations_per_seed": request.generations_per_seed,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        return policy_experiment_id

    def _finish_policy_experiment(
        self,
        policy_experiment_id: str,
        *,
        status: str,
        decision: str,
        evidence: dict,
    ) -> None:
        self._db.execute(
            """
            UPDATE policy_experiment
            SET status = ?, promotion_decision = ?, evidence = ?,
                finished_at = datetime('now')
            WHERE id = ?
            """,
            (
                status,
                decision,
                json.dumps(evidence, ensure_ascii=False, default=str),
                policy_experiment_id,
            ),
        )

    def _safe_tuner_feedback(self, action: MetaAction, gain: float) -> None:
        """安全记录 tuner feedback — DB 写入失败不影响 slow loop 主流程."""
        try:
            self._record_tuner_feedback(action, gain)
        except Exception:
            logger.debug("Tuner feedback recording failed", exc_info=True)

    def _apply_evolve_prompt(
        self,
        action: MetaAction,
        experiment_id: str,
        coder_system_prompt: str,
    ) -> None:
        """evolve_prompt 动作 — L1 级 prompt 变异."""
        if self._meta_planner is None or not hasattr(self._meta_planner, "_prompt_evolver"):
            return
        evolver = self._meta_planner._prompt_evolver  # noqa: SLF001
        if evolver is None or not coder_system_prompt:
            return

        champion = self._prompt_repo.get_latest("coder", "champion")
        parent_id = champion.id if champion else None
        new_prompt, mutations = evolver.evolve(coder_system_prompt)
        if mutations:
            self._prompt_repo.create(
                agent_role="coder",
                content=new_prompt,
                parent_id=parent_id,
                artifact_store=self._artifact_store,
            )
            logger.info("Prompt evolved with mutations: %s", mutations)

    def _record_tuner_feedback(self, action: MetaAction, gain: float) -> None:
        """将 meta 动作结果反馈给贝叶斯优化器."""
        if self._meta_planner is None or self._meta_planner._tuner is None:  # noqa: SLF001
            return
        try:
            params = {action.target: action.new_value}
            self._meta_planner._tuner.update(  # noqa: SLF001
                params,
                score=gain,
                generation=0,
            )
        except Exception:
            logger.warning("Failed to record tuner feedback", exc_info=True)
