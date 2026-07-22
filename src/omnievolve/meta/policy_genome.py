"""SearchPolicyGenome.

S9-01: 冻结 SearchPolicyGenome schema
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SearchPolicyGenome:
    """搜索策略基因组.

    包含所有可进化的搜索参数。
    """

    parent_selector: str = "tournament"
    mutation_mix: dict[str, float] = field(
        default_factory=lambda: {"point": 0.5, "crossover": 0.3, "rewrite": 0.2}
    )
    crossover_policy: str = "single_point"
    retrieval_budget: int = 8
    memory_scope_weights: dict[str, float] = field(
        default_factory=lambda: {"L0": 1.0, "L1": 0.9, "L2": 0.6, "L3": 0.4, "L4": 0.2}
    )
    context_pruning_policy: str = "relevance"
    novelty_policy: str = "multi_stage"
    model_routing_policy: str = "sliding_window_ucb"
    director_prompt_version: str = "default"
    coder_prompt_version: str = "default"
    critic_prompt_version: str = "default"
    temperature_schedule: str = "constant"
    island_migration_policy: str = "periodic"
    backtracking_policy: str = "none"
    # Epiplexity 辅助适应度权重（可被 Slow Loop 自进化）
    # fitness = f_task + epiplexity_beta * S_φ(code)
    epiplexity_beta: float = 0.1

    def to_dict(self) -> dict:
        """转换为字典."""
        return {
            "parent_selector": self.parent_selector,
            "mutation_mix": self.mutation_mix,
            "crossover_policy": self.crossover_policy,
            "retrieval_budget": self.retrieval_budget,
            "memory_scope_weights": self.memory_scope_weights,
            "context_pruning_policy": self.context_pruning_policy,
            "novelty_policy": self.novelty_policy,
            "model_routing_policy": self.model_routing_policy,
            "director_prompt_version": self.director_prompt_version,
            "coder_prompt_version": self.coder_prompt_version,
            "critic_prompt_version": self.critic_prompt_version,
            "temperature_schedule": self.temperature_schedule,
            "island_migration_policy": self.island_migration_policy,
            "backtracking_policy": self.backtracking_policy,
            "epiplexity_beta": self.epiplexity_beta,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SearchPolicyGenome:
        """从字典创建."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# L0 可自动调整的参数
L0_MUTABLE_FIELDS = {
    "parent_selector",
    "mutation_mix",
    "retrieval_budget",
    "memory_scope_weights",
    "temperature_schedule",
    "island_migration_policy",
}

# L1 需要 Replay/Canary 的参数
L1_FIELDS = {
    "director_prompt_version",
    "coder_prompt_version",
    "critic_prompt_version",
    "context_pruning_policy",
    "crossover_policy",
    "backtracking_policy",
}

# L2 默认禁止修改
L2_FORBIDDEN_FIELDS = {
    "novelty_policy",  # 影响评估语义
}
