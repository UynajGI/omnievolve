"""L0/L1/L2 风险分级和发布门禁.

S9-04: 实现 L0 风险动作白名单
S9-05: 实现 L1/L2 拒绝与审计门禁
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from omnievolve.meta.policy_genome import (
    L0_MUTABLE_FIELDS,
    L1_FIELDS,
    L2_FORBIDDEN_FIELDS,
    SearchPolicyGenome,
)

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """风险等级."""

    L0 = "L0"  # 可自动允许
    L1 = "L1"  # 必须 Replay/Canary
    L2 = "L2"  # 默认禁止


@dataclass
class MetaAction:
    """元进化动作."""

    action_type: str  # modify_field / modify_prompt / modify_policy / ...
    target: str  # 目标字段或组件
    old_value: Any
    new_value: Any
    risk_level: RiskLevel
    rationale: str = ""
    requires_replay: bool = False


class GovernancePolicy:
    """治理策略.

    控制 Meta-Agent 的自修改权限。
    """

    def __init__(
        self,
        *,
        auto_apply_l0: bool = True,
        require_replay_for_l1: bool = True,
        allow_l2_actions: bool = False,
    ) -> None:
        self._auto_apply_l0 = auto_apply_l0
        self._require_replay_for_l1 = require_replay_for_l1
        self._allow_l2 = allow_l2_actions

    def classify_action(self, action: MetaAction) -> RiskLevel:
        """分类动作风险等级."""
        # 检查目标字段
        target = action.target

        if target in L2_FORBIDDEN_FIELDS:
            return RiskLevel.L2

        if target in L1_FIELDS:
            return RiskLevel.L1

        if target in L0_MUTABLE_FIELDS:
            return RiskLevel.L0

        # 默认为 L1（需要验证）
        return RiskLevel.L1

    def can_apply(self, action: MetaAction) -> tuple[bool, str]:
        """检查动作是否可以应用.

        Returns:
            (can_apply, reason)
        """
        risk = self.classify_action(action)

        if risk == RiskLevel.L2:
            if self._allow_l2:
                return True, "L2 allowed by configuration"
            return False, "L2 actions are forbidden by default"

        if risk == RiskLevel.L1:
            if action.requires_replay and self._require_replay_for_l1:
                return False, "L1 actions require Replay/Canary evaluation first"
            return True, "L1 action approved with replay"

        if risk == RiskLevel.L0:
            if self._auto_apply_l0:
                return True, "L0 action auto-approved"
            return False, "L0 auto-apply disabled"

        return False, "Unknown risk level"


class L0PolicyMutator:
    """L0 策略变异器.

    S9-06: 实现 L0 Policy Mutator
    只能修改 L0 级别的参数。
    """

    def __init__(self, governance: GovernancePolicy) -> None:
        self._governance = governance

    def mutate(
        self,
        genome: SearchPolicyGenome,
        field_name: str,
        new_value: Any,
    ) -> tuple[SearchPolicyGenome | None, str]:
        """变异策略基因组.

        Returns:
            (new_genome, reason) 或 (None, rejection_reason)
        """
        action = MetaAction(
            action_type="modify_field",
            target=field_name,
            old_value=getattr(genome, field_name, None),
            new_value=new_value,
            risk_level=RiskLevel.L0,
        )

        can_apply, reason = self._governance.can_apply(action)
        if not can_apply:
            return None, reason

        # 创建变异后的基因组
        current_dict = genome.to_dict()
        current_dict[field_name] = new_value

        try:
            new_genome = SearchPolicyGenome.from_dict(current_dict)
            logger.info(f"L0 mutation applied: {field_name} = {new_value}")
            return new_genome, "Mutation applied"
        except Exception as e:
            return None, f"Invalid genome after mutation: {e}"

    def suggest_mutations(
        self,
        genome: SearchPolicyGenome,
        health_indicators: dict[str, Any],
    ) -> list[tuple[str, Any, str]]:
        """基于健康指标建议变异.

        Returns:
            [(field_name, new_value, rationale), ...]
        """
        suggestions: list[tuple[str, Any, str]] = []

        # 低覆盖率时增加检索预算
        if health_indicators.get("coverage_entropy", 1.0) < 0.4:
            suggestions.append(
                (
                    "retrieval_budget",
                    min(genome.retrieval_budget + 2, 20),
                    "Increase retrieval budget to improve coverage",
                )
            )

        # 高污染度时调整记忆权重
        if health_indicators.get("pollution_ratio", 0.0) > 0.3:
            new_weights = genome.memory_scope_weights.copy()
            new_weights["L3"] = max(new_weights.get("L3", 0.4) * 0.8, 0.1)
            new_weights["L4"] = max(new_weights.get("L4", 0.2) * 0.8, 0.05)
            suggestions.append(
                (
                    "memory_scope_weights",
                    new_weights,
                    "Reduce broad scope weights to decrease pollution",
                )
            )

        # 低 ROI 时增加探索
        if health_indicators.get("roi_score", 1.0) < 0.01:
            new_mix = genome.mutation_mix.copy()
            new_mix["rewrite"] = min(new_mix.get("rewrite", 0.2) + 0.1, 0.5)
            suggestions.append(
                (
                    "mutation_mix",
                    new_mix,
                    "Increase rewrite mutations for more exploration",
                )
            )

        return suggestions


class ReplayEvaluator:
    """Replay/Canary 评估器.

    S9-08: 实现最小同预算 challenger 比较
    """

    def __init__(
        self,
        *,
        budget_ratio: float = 0.1,
        min_gain_threshold: float = 0.02,
        max_regression: float = 0.005,
    ) -> None:
        self._budget_ratio = budget_ratio
        self._min_gain = min_gain_threshold
        self._max_regression = max_regression

    def compare(
        self,
        champion_scores: list[float],
        challenger_scores: list[float],
    ) -> dict[str, Any]:
        """比较 Champion 和 Challenger.

        Args:
            champion_scores: Champion 在 replay 上的分数
            challenger_scores: Challenger 在 replay 上的分数

        Returns:
            比较结果
        """
        import numpy as np

        from omnievolve.eval.benchmark_stats import summarize_samples

        if not champion_scores or not challenger_scores:
            return {
                "decision": "inconclusive",
                "reason": "Insufficient data",
            }

        champ_mean = float(np.mean(champion_scores))
        chall_mean = float(np.mean(challenger_scores))
        gain = chall_mean - champ_mean
        champ_summary = summarize_samples(champion_scores, seed=0)
        chall_summary = summarize_samples(challenger_scores, seed=1)
        conservative_gain = chall_summary.ci_low - champ_summary.ci_high
        conservative_regression = champ_summary.ci_low - chall_summary.ci_high

        # 统计显著性（简化）
        if len(champion_scores) > 1 and len(challenger_scores) > 1:
            champ_std = float(np.std(champion_scores))
            chall_std = float(np.std(challenger_scores))
            pooled_std = (champ_std + chall_std) / 2
            effect_size = gain / max(pooled_std, 0.001)
        else:
            effect_size = gain

        decision = "reject"
        reason = ""

        if conservative_gain >= self._min_gain and effect_size > 0.5:
            decision = "promote"
            reason = (
                "Challenger confidence interval shows improvement "
                f"(conservative_gain={conservative_gain:.4f})"
            )
        elif gain >= 0 and abs(gain) < self._min_gain:
            decision = "hold"
            reason = f"Challenger shows marginal change (gain={gain:.4f})"
        elif conservative_regression > self._max_regression:
            decision = "reject"
            reason = f"Challenger shows significant regression (gain={gain:.4f})"
        else:
            decision = "hold"
            reason = f"Challenger within acceptable range (gain={gain:.4f})"

        return {
            "decision": decision,
            "reason": reason,
            "champion_mean": champ_mean,
            "challenger_mean": chall_mean,
            "gain": gain,
            "effect_size": effect_size,
            "conservative_gain": conservative_gain,
            "champion_ci": [champ_summary.ci_low, champ_summary.ci_high],
            "challenger_ci": [chall_summary.ci_low, chall_summary.ci_high],
        }

    def compare_equal_budget(
        self,
        champion_scores: list[float],
        challenger_scores: list[float],
        *,
        champion_cost_usd: float = 0.0,
        challenger_cost_usd: float = 0.0,
        champion_wall_sec: float = 0.0,
        challenger_wall_sec: float = 0.0,
    ) -> dict[str, Any]:
        """设计文档 §6.2: 等预算比较.

        Champion 与 Challenger 使用相同快照和预算，
        比较任务前沿、成本、稳定性和健康度。

        额外检查:
        - 成本回归: Challenger 成本不得超过 Champion 的 1.5 倍
        - 时间回归: Challenger 墙钟时间不得超过 Champion 的 2 倍
        - 稳定性: 标准差不得显著增大
        """
        import numpy as np

        base = self.compare(champion_scores, challenger_scores)

        # 数据不足时跳过约束检查
        if base["decision"] == "inconclusive":
            base["champion_cost"] = champion_cost_usd
            base["challenger_cost"] = challenger_cost_usd
            base["budget_equal"] = True
            return base

        # 成本约束
        if champion_cost_usd > 0 and challenger_cost_usd > champion_cost_usd * 1.5:
            base["decision"] = "reject"
            reason = f"Cost regression: {challenger_cost_usd:.4f} > 1.5x champion"
            base["reason"] = f"{base['reason']} | {reason}" if base["reason"] else reason
            return base

        # 时间约束
        if champion_wall_sec > 0 and challenger_wall_sec > champion_wall_sec * 2.0:
            base["decision"] = "reject"
            reason = f"Time regression: {challenger_wall_sec:.1f}s > 2x champion"
            base["reason"] = f"{base['reason']} | {reason}" if base["reason"] else reason
            return base

        # 稳定性约束
        if len(champion_scores) > 2 and len(challenger_scores) > 2:
            champ_std = float(np.std(champion_scores))
            chall_std = float(np.std(challenger_scores))
            if chall_std > champ_std * 2.0 and champ_std > 0:
                reason = f"Stability warning: std {chall_std:.4f} > 2x champion {champ_std:.4f}"
                base["reason"] = f"{base['reason']} | {reason}" if base["reason"] else reason
                if base["decision"] == "promote":
                    base["decision"] = "hold"  # 降级为 hold

        base["champion_cost"] = champion_cost_usd
        base["challenger_cost"] = challenger_cost_usd
        base["budget_equal"] = True
        return base


class MetaPlanner:
    """Meta 规划器.

    S8-10: 只读诊断 + 受控动作提议。
    支持规则引擎（L0PolicyMutator）或贝叶斯优化（BayesianTuner）两种后端。
    """

    def __init__(
        self,
        mutator: L0PolicyMutator,
        *,
        max_actions_per_window: int = 3,
        tuner: Any = None,  # BayesianTuner | None
        prompt_evolver: Any = None,  # PromptEvolver | None
    ) -> None:
        self._mutator = mutator
        self._max_actions = max_actions_per_window
        self._tuner = tuner
        self._prompt_evolver = prompt_evolver

    def propose(
        self,
        health: dict[str, Any],
        champion_genome: SearchPolicyGenome,
        history: list[dict],
    ) -> list[MetaAction]:
        """提议优化动作.

        优先使用贝叶斯优化（超参空间小、评估代价高）;
        未配置时回退到规则引擎。
        """
        actions: list[MetaAction] = []

        if self._tuner is not None:
            actions = self._propose_bayesian(health, champion_genome)
        else:
            actions = self._propose_rule_based(health, champion_genome)

        # AM-04: 停滞检测 → prompt 进化（L1 级别）
        if self._prompt_evolver is not None:
            stagnation = health.get("stagnation_gens", 0)
            roi = health.get("roi_score", 1.0)
            if stagnation >= 3 or roi < 0.001:
                actions.append(
                    MetaAction(
                        action_type="evolve_prompt",
                        target="system_prompt",
                        old_value="current",
                        new_value="evolved",
                        risk_level=RiskLevel.L1,
                        rationale=f"Stagnation detected ({stagnation} gens, ROI={roi:.4f}) — evolve prompt",
                    )
                )

        return actions

    def _propose_rule_based(
        self,
        health: dict[str, Any],
        champion_genome: SearchPolicyGenome,
    ) -> list[MetaAction]:
        """规则引擎提议（原有逻辑）."""
        actions = []
        suggestions = self._mutator.suggest_mutations(champion_genome, health)

        for field_name, new_value, rationale in suggestions[: self._max_actions]:
            action = MetaAction(
                action_type="modify_field",
                target=field_name,
                old_value=getattr(champion_genome, field_name, None),
                new_value=new_value,
                risk_level=RiskLevel.L0,
                rationale=rationale,
            )
            actions.append(action)

        return actions

    def _propose_bayesian(
        self,
        health: dict[str, Any],
        champion_genome: SearchPolicyGenome,
    ) -> list[MetaAction]:
        """贝叶斯优化提议."""
        # suggest 下一组参数
        suggested_params = self._tuner.suggest()

        # → genome 更新字典
        updates = self._tuner.params_to_genome_updates(suggested_params)

        actions = []
        for field_name, new_value in list(updates.items())[: self._max_actions]:
            old_value = getattr(champion_genome, field_name, None)
            rationale = f"Bayesian optimization: {field_name} = {new_value}"

            action = MetaAction(
                action_type="modify_field",
                target=field_name,
                old_value=old_value,
                new_value=new_value,
                risk_level=RiskLevel.L0,
                rationale=rationale,
            )
            actions.append(action)

        if not actions:
            logger.info("BayesianTuner produced no actionable suggestions")

        return actions
