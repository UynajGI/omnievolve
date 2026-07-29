"""角色条件化模型路由.

S8-11: 冻结 RoleConditionalRouter 接口
S8-12: 实现 Sliding-window UCB
S8-13: 实现 Director/Coder/Critic 分离奖励
S8-14: 实现 budget-aware 路由约束
"""

from __future__ import annotations

import logging
import math
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSlot:
    """模型槽位."""

    name: str
    tier: str  # heavy / light
    cost_per_1k_input: float
    cost_per_1k_output: float
    avg_latency_ms: float
    capabilities: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class RouteContext:
    """路由上下文."""

    role: str  # director / coder / critic / meta
    generation: int
    stagnation_level: float
    novelty_deficit: float
    implementation_difficulty: float
    remaining_token_ratio: float
    remaining_compute_ratio: float
    required_capabilities: set[str] = field(default_factory=set)


class SlidingWindowUCB:
    """滑动窗口 UCB.

    使用时间窗口内的奖励历史，适应非平稳环境。
    """

    def __init__(
        self,
        slots: list[ModelSlot],
        *,
        window_size: int = 50,
        c: float = 1.414,
        cost_weight: float = 0.2,
        latency_weight: float = 0.1,
    ) -> None:
        self._slots = {s.name: s for s in slots}
        self._window_size = window_size
        self._c = c
        self._cost_weight = cost_weight
        self._latency_weight = latency_weight

        # 按角色维护历史
        self._rewards: dict[str, dict[str, deque]] = {}  # role -> model -> rewards
        self._total_pulls: dict[str, int] = {}  # role -> total

        for role in ["director", "coder", "critic", "meta"]:
            self._rewards[role] = {name: deque(maxlen=window_size) for name in self._slots}

    def select(self, ctx: RouteContext) -> str:
        """选择模型."""
        role_rewards = self._rewards[ctx.role]
        total = self._total_pulls.get(ctx.role, 0) + 1

        best_model = None
        best_score = -float("inf")

        for name, slot in self._slots.items():
            rewards = role_rewards[name]

            if len(rewards) == 0:
                # 未尝试过的模型给予高优先级
                ucb_score = float("inf")
            else:
                mean_reward = sum(rewards) / len(rewards)

                # 成本惩罚
                cost_penalty = self._cost_weight * (
                    slot.cost_per_1k_input + slot.cost_per_1k_output
                )

                # 延迟惩罚
                latency_penalty = self._latency_weight * (slot.avg_latency_ms / 1000)

                # UCB 探索项
                exploration = self._c * math.sqrt(math.log(total) / max(len(rewards), 1))

                ucb_score = mean_reward + exploration - cost_penalty - latency_penalty

            # Budget-aware 约束
            if ctx.remaining_token_ratio < 0.2 and slot.tier == "heavy":
                ucb_score *= 0.5  # 预算紧张时降低 heavy 模型权重

            if ucb_score > best_score:
                best_score = ucb_score
                best_model = name

        return best_model or list(self._slots.keys())[0]

    def update(self, model: str, role: str, reward: float) -> None:
        """更新模型奖励."""
        if role not in self._rewards:
            return
        if model not in self._rewards[role]:
            return

        self._rewards[role][model].append(reward)
        self._total_pulls[role] = self._total_pulls.get(role, 0) + 1


class DiscountedUCB:
    """折扣 UCB.

    使用折扣因子衰减旧奖励。
    """

    def __init__(
        self,
        slots: list[ModelSlot],
        *,
        discount: float = 0.95,
        c: float = 1.414,
    ) -> None:
        self._slots = {s.name: s for s in slots}
        self._discount = discount
        self._c = c

        self._discounted_sums: dict[str, dict[str, float]] = {}
        self._discounted_counts: dict[str, dict[str, float]] = {}

        for role in ["director", "coder", "critic", "meta"]:
            self._discounted_sums[role] = {name: 0.0 for name in self._slots}
            self._discounted_counts[role] = {name: 0.0 for name in self._slots}

    def select(self, ctx: RouteContext) -> str:
        """选择模型."""
        best_model = None
        best_score = -float("inf")

        sums = self._discounted_sums[ctx.role]
        counts = self._discounted_counts[ctx.role]
        total = sum(counts.values()) + 1

        for name in self._slots:
            if counts[name] < 1:
                score = float("inf")
            else:
                mean = sums[name] / max(counts[name], 0.001)
                exploration = self._c * math.sqrt(math.log(total) / max(counts[name], 1))
                score = mean + exploration

            if score > best_score:
                best_score = score
                best_model = name

        return best_model or list(self._slots.keys())[0]

    def update(self, model: str, role: str, reward: float) -> None:
        """更新奖励（应用折扣）."""
        for name in self._slots:
            self._discounted_sums[role][name] *= self._discount
            self._discounted_counts[role][name] *= self._discount

        self._discounted_sums[role][model] += reward
        self._discounted_counts[role][model] += 1


class ThompsonSampling:
    """Thompson Sampling 路由.

    使用 Beta 分布采样，自然平衡探索与利用。
    参考 MLEvolve 的 Beta(alpha, beta) 更新模式。
    """

    def __init__(
        self,
        slots: list[ModelSlot],
        *,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
    ) -> None:
        self._slots = {s.name: s for s in slots}
        # 每个 (role, model) 维护 Beta 分布参数
        self._alpha: dict[str, dict[str, float]] = {}
        self._beta: dict[str, dict[str, float]] = {}
        for role in ["director", "coder", "critic", "meta"]:
            self._alpha[role] = {name: prior_alpha for name in self._slots}
            self._beta[role] = {name: prior_beta for name in self._slots}

    def select(self, ctx: RouteContext) -> str:
        """从 Beta 分布采样，选择最高样本值的模型."""
        best_model = None
        best_sample = -float("inf")

        for name in self._slots:
            a = self._alpha[ctx.role][name]
            b = self._beta[ctx.role][name]
            sample = random.betavariate(a, b)
            if sample > best_sample:
                best_sample = sample
                best_model = name

        return best_model or list(self._slots.keys())[0]

    def update(self, model: str, role: str, reward: float) -> None:
        """Beta 分布更新：reward 视为成功概率."""
        r = max(0.0, min(1.0, reward))
        self._alpha[role][model] += r
        self._beta[role][model] += 1.0 - r


class ModelRouter:
    """模型路由器.

    S8-11: 角色条件化的非平稳 Bandit 路由。
    """

    def __init__(
        self,
        slots: list[ModelSlot],
        *,
        algorithm: str = "sliding_window_ucb",
        **kwargs: Any,
    ) -> None:
        self._slots = slots
        self._configured_algorithm = algorithm

        if algorithm == "sliding_window_ucb":
            self._strategy: SlidingWindowUCB | DiscountedUCB | ThompsonSampling = SlidingWindowUCB(
                slots, **kwargs
            )
        elif algorithm == "discounted_ucb":
            self._strategy = DiscountedUCB(slots, **kwargs)
        elif algorithm == "thompson":
            self._strategy = ThompsonSampling(slots, **kwargs)
        else:
            raise ValueError(f"unsupported model routing algorithm: {algorithm!r}")

    def select(self, ctx: RouteContext) -> str:
        """选择模型."""
        return self._strategy.select(ctx)

    def update(self, model: str, role: str, reward: float) -> None:
        """更新模型表现."""
        self._strategy.update(model, role, reward)

    def get_stats(self) -> dict[str, Any]:
        """获取路由统计."""
        return {
            "algorithm": self._configured_algorithm,
            "strategy_class": type(self._strategy).__name__,
            "slots": [s.name for s in self._slots],
        }

    def snapshot_state(self) -> dict[str, Any]:
        """Serialize role-conditioned bandit state for deterministic resume."""
        strategy = self._strategy
        state: dict[str, Any] = {
            "algorithm": self._configured_algorithm,
            "slots": [slot.name for slot in self._slots],
        }
        if isinstance(strategy, SlidingWindowUCB):
            state["rewards"] = {
                role: {model: list(values) for model, values in models.items()}
                for role, models in strategy._rewards.items()
            }
            state["total_pulls"] = dict(strategy._total_pulls)
        elif isinstance(strategy, DiscountedUCB):
            state["discounted_sums"] = {
                role: dict(models) for role, models in strategy._discounted_sums.items()
            }
            state["discounted_counts"] = {
                role: dict(models) for role, models in strategy._discounted_counts.items()
            }
        elif isinstance(strategy, ThompsonSampling):
            state["alpha"] = {role: dict(models) for role, models in strategy._alpha.items()}
            state["beta"] = {role: dict(models) for role, models in strategy._beta.items()}
        return state

    def restore_state(self, state: dict[str, Any] | None) -> None:
        """Restore matching slots/algorithm; incompatible snapshots fail closed."""
        if not state:
            return
        if state.get("algorithm") != self._configured_algorithm:
            raise ValueError("router checkpoint algorithm does not match runtime policy")
        if list(state.get("slots", [])) != [slot.name for slot in self._slots]:
            raise ValueError("router checkpoint slots do not match runtime configuration")

        strategy = self._strategy
        if isinstance(strategy, SlidingWindowUCB):
            for role, models in state.get("rewards", {}).items():
                if role not in strategy._rewards:
                    continue
                for model, values in models.items():
                    if model in strategy._rewards[role]:
                        strategy._rewards[role][model].clear()
                        strategy._rewards[role][model].extend(float(value) for value in values)
            strategy._total_pulls = {
                role: int(value) for role, value in state.get("total_pulls", {}).items()
            }
        elif isinstance(strategy, DiscountedUCB):
            for attr, key in (
                ("_discounted_sums", "discounted_sums"),
                ("_discounted_counts", "discounted_counts"),
            ):
                target = getattr(strategy, attr)
                for role, models in state.get(key, {}).items():
                    if role in target:
                        target[role].update(
                            {
                                model: float(value)
                                for model, value in models.items()
                                if model in target[role]
                            }
                        )
        elif isinstance(strategy, ThompsonSampling):
            for attr, key in (("_alpha", "alpha"), ("_beta", "beta")):
                target = getattr(strategy, attr)
                for role, models in state.get(key, {}).items():
                    if role in target:
                        target[role].update(
                            {
                                model: float(value)
                                for model, value in models.items()
                                if model in target[role]
                            }
                        )


# 角色奖励计算
def compute_director_reward(
    thought_adopted: bool,
    mechanism_novelty: float,
    frontier_contribution: float,
) -> float:
    """计算 Director 奖励."""
    return (
        0.4 * (1.0 if thought_adopted else 0.0)
        + 0.3 * mechanism_novelty
        + 0.3 * frontier_contribution
    )


def compute_critic_reward(
    defect_recall: float,
    false_rejection_rate: float,
    evaluator_cost_saved: float,
) -> float:
    """计算 Critic 奖励."""
    return 0.5 * defect_recall - 0.3 * false_rejection_rate + 0.2 * evaluator_cost_saved


def compute_shinka_reward(
    score: float,
    parent_score: float,
    baseline_score: float,
) -> float:
    """ShinkaEvolve 相对奖励公式.

    r_u = exp(max(r_i - r_b, 0)) - 1
    其中 r_b = max(parent_score, baseline_score)

    奖励 LLM 产生大幅改进，惩罚 small tweaks。
    """
    import math

    baseline = max(parent_score, baseline_score)
    improvement = max(score - baseline, 0.0)
    return math.exp(improvement) - 1.0
