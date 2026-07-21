"""Slow Loop Controller — 提取自 EvolutionEngine.

T1 重构第二步：将 Slow Loop 逻辑从引擎中分离。
包含：健康评估 → 提议动作 → 治理分级 → Challenger 实验 → promote/reject。

引擎持有它的实例并委托调用。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from omnievolve.meta.governance import MetaAction

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
    from omnievolve.storage.artifact_store import ArtifactStore
    from omnievolve.storage.db import Database
    from omnievolve.storage.repositories.experiment_repo import ExperimentRepository
    from omnievolve.storage.repositories.prompt_repo import PromptVersionRepository

logger = logging.getLogger(__name__)


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

        decision = self._replay_evaluator.compare(
            champion_scores=recent_scores[-health_window_gens:],
            challenger_scores=recent_scores[-1:],
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
            self._record_tuner_feedback(action, decision.get("gain", 0.0))
            return new_genome, challenger.id
        else:
            self._policy_archive.reject(challenger.id, decision.get("reason", ""))
            self._record_tuner_feedback(action, decision.get("gain", -0.01))
            return None, None

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
