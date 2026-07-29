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
        from omnievolve.meta.policy_runtime import active_policy_fields

        if field_name not in active_policy_fields():
            return None, f"Policy field {field_name!r} is inactive and frozen"

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

        return suggestions


class ReplayEvaluator:
    """Replay/Canary 评估器.

    S9-08: 实现最小同预算 challenger 比较
    """

    def __init__(
        self,
        *,
        budget_ratio: float = 0.1,
        min_gain_threshold: float = 0.0,
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
        import statistics

        from omnievolve.eval.benchmark_stats import bootstrap_confidence_interval

        if (
            len(champion_scores) < 3
            or len(challenger_scores) < 3
            or len(champion_scores) != len(challenger_scores)
        ):
            return {
                "decision": "inconclusive",
                "reason": "At least three paired seeds are required",
            }

        differences = [
            float(challenger - champion)
            for champion, challenger in zip(champion_scores, challenger_scores, strict=True)
        ]
        champ_mean = float(statistics.fmean(champion_scores))
        chall_mean = float(statistics.fmean(challenger_scores))
        gain = float(statistics.fmean(differences))
        # A two-sided 90% interval has the same lower/upper quantiles as
        # one-sided 95% bounds.
        ci_low, ci_high = bootstrap_confidence_interval(
            differences,
            confidence=0.90,
            seed=0,
            statistic=statistics.fmean,
        )
        diff_std = statistics.stdev(differences) if len(differences) > 1 else 0.0
        effect_size = gain / max(diff_std, 0.001)

        if ci_low > self._min_gain:
            decision = "promote"
            reason = (
                "Paired one-sided 95% lower bound is positive "
                f"(lower={ci_low:.4f})"
            )
        elif ci_high < 0:
            decision = "reject"
            reason = f"Paired one-sided 95% upper bound is negative ({ci_high:.4f})"
        else:
            decision = "hold"
            reason = f"Paired interval is inconclusive [{ci_low:.4f}, {ci_high:.4f}]"

        return {
            "decision": decision,
            "reason": reason,
            "champion_mean": champ_mean,
            "challenger_mean": chall_mean,
            "gain": gain,
            "effect_size": effect_size,
            "paired_differences": differences,
            "paired_ci": [ci_low, ci_high],
            "conservative_gain": ci_low,
        }

    def compare_equal_budget(
        self,
        champion_scores: list[float],
        challenger_scores: list[float],
        *,
        champion_cost_usd: float | None = None,
        challenger_cost_usd: float | None = None,
        champion_wall_sec: float = 0.0,
        challenger_wall_sec: float = 0.0,
        champion_best_scores: list[float] | None = None,
        challenger_best_scores: list[float] | None = None,
        champion_success_rates: list[float] | None = None,
        challenger_success_rates: list[float] | None = None,
        require_known_cost: bool = False,
    ) -> dict[str, Any]:
        """设计文档 §6.2: 等预算比较.

        Champion 与 Challenger 使用相同快照和预算，
        比较任务前沿、成本、稳定性和健康度。

        额外检查:
        - 成本回归: Challenger 成本不得超过 Champion 的 1.5 倍
        - 时间回归: Challenger 墙钟时间不得超过 Champion 的 2 倍
        - 稳定性: 标准差不得显著增大
        """
        import statistics

        base = self.compare(champion_scores, challenger_scores)

        # 数据不足时跳过约束检查
        if base["decision"] == "inconclusive":
            base["champion_cost"] = champion_cost_usd
            base["challenger_cost"] = challenger_cost_usd
            base["budget_equal"] = True
            return base

        cost_known = champion_cost_usd is not None and challenger_cost_usd is not None
        base["cost_known"] = cost_known
        if require_known_cost and not cost_known:
            base["decision"] = "hold"
            base["reason"] = "Cost-aware policy comparison has unknown arm cost"
            return base

        # 成本约束
        if (
            champion_cost_usd is not None
            and challenger_cost_usd is not None
            and champion_cost_usd > 0
            and challenger_cost_usd > champion_cost_usd * 1.5
        ):
            base["decision"] = "reject"
            reason = f"Cost regression: {challenger_cost_usd:.4f} > 1.5x champion"
            base["reason"] = f"{base['reason']} | {reason}" if base["reason"] else reason
            return base

        def mean_or_none(values: list[float] | None) -> float | None:
            return float(statistics.fmean(values)) if values else None

        champion_best = mean_or_none(champion_best_scores)
        challenger_best = mean_or_none(challenger_best_scores)
        if (
            champion_best is not None
            and challenger_best is not None
            and challenger_best < champion_best - self._max_regression
        ):
            base["decision"] = "reject"
            base["reason"] = (
                f"Best-of-budget regression: {challenger_best:.4f} < {champion_best:.4f}"
            )
            return base

        champion_success = mean_or_none(champion_success_rates)
        challenger_success = mean_or_none(challenger_success_rates)
        if (
            champion_success is not None
            and challenger_success is not None
            and challenger_success < champion_success - self._max_regression
        ):
            base["decision"] = "reject"
            base["reason"] = (
                f"Success-rate regression: {challenger_success:.4f} < {champion_success:.4f}"
            )
            return base

        # 时间约束
        if champion_wall_sec > 0 and challenger_wall_sec > champion_wall_sec * 2.0:
            base["decision"] = "reject"
            reason = f"Time regression: {challenger_wall_sec:.1f}s > 2x champion"
            base["reason"] = f"{base['reason']} | {reason}" if base["reason"] else reason
            return base

        # 稳定性约束
        if len(champion_scores) > 2 and len(challenger_scores) > 2:
            champ_std = float(statistics.stdev(champion_scores))
            chall_std = float(statistics.stdev(challenger_scores))
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
        from omnievolve.meta.policy_runtime import active_policy_fields

        actions = []
        active_fields = active_policy_fields()
        suggestions = self._mutator.suggest_mutations(champion_genome, health)

        for field_name, new_value, rationale in suggestions[: self._max_actions]:
            if field_name not in active_fields:
                logger.info("Ignoring inactive rule-based policy suggestion: %s", field_name)
                continue
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
        from omnievolve.meta.policy_runtime import active_policy_fields

        # suggest 下一组参数
        suggested_params = self._tuner.suggest()

        # → genome 更新字典
        updates = self._tuner.params_to_genome_updates(suggested_params)
        active_fields = active_policy_fields()

        actions = []
        for field_name, new_value in updates.items():
            if field_name not in active_fields:
                logger.info("Ignoring inactive Bayesian policy suggestion: %s", field_name)
                continue
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
            if len(actions) >= self._max_actions:
                break

        if not actions:
            logger.info("BayesianTuner produced no actionable suggestions")

        return actions
