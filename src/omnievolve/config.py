"""OmniEvolve 配置管理.

S1-16: pydantic-settings 配置
- omnievolve.toml 加载
- 分层覆盖
- 类型安全
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EvolutionSettings(BaseSettings):
    """进化引擎配置."""

    max_generations: int = 50
    population_size: int = 8
    island_count: int = 4
    novelty_threshold: float = 0.92
    novelty_retry_limit: int = 3
    mutation_rate: float = 0.3
    crossover_rate: float = 0.15
    max_stagnation_gens: int = 5
    token_budget: int = 2_000_000
    compute_budget_sec: float = 0  # 0 表示不单独限制
    health_window_gens: int = 3


class SelectionSettings(BaseSettings):
    """选择策略配置."""

    parent_selector: str = "progressive_mcgs"
    tournament_size: int = 3
    pareto_enabled: bool = True
    island_migration_interval: int = 5


class ModelRoutingSettings(BaseSettings):
    """模型路由配置."""

    algorithm: str = "sliding_window_ucb"
    window_size: int = 50
    ucb_c: float = 1.414
    cost_weight: float = 0.2
    latency_weight: float = 0.1
    role_conditioned: bool = True


class ModelsSettings(BaseSettings):
    """模型配置."""

    heavy: list[str] = Field(default_factory=lambda: ["reasoning-model-primary"])
    light: list[str] = Field(default_factory=lambda: ["fast-model-primary"])
    routing: ModelRoutingSettings = Field(default_factory=ModelRoutingSettings)


class EmbeddingCodeSettings(BaseSettings):
    """代码嵌入配置."""

    provider: str = "voyage"
    model: str = "voyage-code-3"
    revision: str = "default"
    dimension: int = 1024
    normalization: str = "provider_default"
    input_type: str = "document"


class EmbeddingThoughtSettings(BaseSettings):
    """思想嵌入配置."""

    provider: str = "local"
    model: str = "bge-m3"
    revision: str = "default"
    dimension: int = 1024
    normalization: str = "l2"
    input_type: str = "document"


class EmbeddingSettings(BaseSettings):
    """嵌入配置."""

    code: EmbeddingCodeSettings = Field(default_factory=EmbeddingCodeSettings)
    thought: EmbeddingThoughtSettings = Field(default_factory=EmbeddingThoughtSettings)


class NoveltySettings(BaseSettings):
    """新颖性门配置."""

    embedding_gate: bool = True
    ast_gate: bool = True
    behavior_gate: bool = False
    llm_judge_on_borderline: bool = True
    borderline_low: float = 0.88
    borderline_high: float = 0.96


class SandboxDockerSettings(BaseSettings):
    """Docker 沙箱配置."""

    image: str = "omnievolve/python-runner:latest"
    tmpfs_mb: int = 256
    inherit_host_env: bool = False


class SandboxSettings(BaseSettings):
    """沙箱配置."""

    backend: str = "docker"  # docker / trusted_subprocess / hardened
    timeout_sec: float = 30
    mem_limit_mb: int = 512
    cpu_limit: float = 1.0
    pids_limit: int = 64
    network_mode: str = "none"
    read_only_root: bool = True
    run_as_non_root: bool = True
    drop_capabilities: bool = True
    no_new_privileges: bool = True
    language: str = "python"
    docker: SandboxDockerSettings = Field(default_factory=SandboxDockerSettings)


class StorageJobsSettings(BaseSettings):
    """任务租约配置."""

    lease_sec: int = 120
    heartbeat_sec: int = 20
    max_attempts: int = 3


class StorageSettings(BaseSettings):
    """存储配置."""

    db_path: str = ".omnievolve/omnievolve.db"
    vector_dir: str = ".omnievolve/vectors"
    artifact_dir: str = ".omnievolve/artifacts"
    export_dir: str = ".omnievolve/exports"
    jobs: StorageJobsSettings = Field(default_factory=StorageJobsSettings)


class MemorySettings(BaseSettings):
    """记忆配置."""

    default_top_k: int = 8
    scope_weights: dict[str, float] = Field(
        default_factory=lambda: {"L0": 1.0, "L1": 0.9, "L2": 0.6, "L3": 0.4, "L4": 0.2}
    )
    ablation_interval_gens: int = 10


class SelfEvaluatorSettings(BaseSettings):
    """自评估器配置."""

    roi_warn_threshold: float = 0.001
    entropy_warn_threshold: float = 0.35
    stagnation_trigger: int = 3
    window_gens: int = 3
    require_confidence_interval: bool = True


class MetaEvolutionSettings(BaseSettings):
    """元进化配置."""

    enabled: bool = True
    prompt_mutation_rate: float = 0.2
    meta_canary_budget_ratio: float = 0.1
    promotion_min_gain: float = 0.02
    promotion_max_regression: float = 0.005
    require_replay_for_l1: bool = True
    auto_apply_l0: bool = True
    allow_l2_actions: bool = False


class EvaluationGovernanceSettings(BaseSettings):
    """评估治理配置."""

    immutable_task_semantics: bool = True
    immutable_correctness_tests: bool = True
    immutable_hidden_data: bool = True
    immutable_score_formula: bool = True
    allow_environment_adaptation: bool = True
    require_baseline_recheck: bool = True
    require_elite_rank_stability: bool = True


class OmniEvolveSettings(BaseSettings):
    """OmniEvolve 主配置.

    支持从 omnievolve.toml 加载配置。
    """

    model_config = SettingsConfigDict(
        env_prefix="OMNIEVOLVE_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    evolution: EvolutionSettings = Field(default_factory=EvolutionSettings)
    selection: SelectionSettings = Field(default_factory=SelectionSettings)
    models: ModelsSettings = Field(default_factory=ModelsSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    novelty: NoveltySettings = Field(default_factory=NoveltySettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    self_evaluator: SelfEvaluatorSettings = Field(default_factory=SelfEvaluatorSettings)
    meta_evolution: MetaEvolutionSettings = Field(default_factory=MetaEvolutionSettings)
    evaluation_governance: EvaluationGovernanceSettings = Field(
        default_factory=EvaluationGovernanceSettings
    )


def load_settings(config_path: str | Path | None = None) -> OmniEvolveSettings:
    """加载配置.

    优先级：环境变量 > 配置文件 > 默认值

    Args:
        config_path: 配置文件路径（omnievolve.toml）

    Returns:
        OmniEvolveSettings 实例
    """
    if config_path is None:
        # 尝试默认路径
        default_paths = [
            Path("omnievolve.toml"),
            Path(".omnievolve/omnievolve.toml"),
        ]
        for path in default_paths:
            if path.exists():
                config_path = path
                break

    if config_path and Path(config_path).exists():
        return _load_from_toml(config_path)

    return OmniEvolveSettings()


def _load_from_toml(config_path: str | Path) -> OmniEvolveSettings:
    """从 TOML 文件加载配置."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    return _build_settings(data)


def _build_settings(data: dict[str, Any]) -> OmniEvolveSettings:
    """从字典构建配置."""
    return OmniEvolveSettings(
        evolution=EvolutionSettings(**data.get("evolution", {})),
        selection=SelectionSettings(**data.get("selection", {})),
        models=ModelsSettings(
            heavy=data.get("models", {}).get("heavy", ["reasoning-model-primary"]),
            light=data.get("models", {}).get("light", ["fast-model-primary"]),
            routing=ModelRoutingSettings(**data.get("models", {}).get("routing", {})),
        ),
        embedding=EmbeddingSettings(
            code=EmbeddingCodeSettings(**data.get("embedding", {}).get("code", {})),
            thought=EmbeddingThoughtSettings(**data.get("embedding", {}).get("thought", {})),
        ),
        novelty=NoveltySettings(**data.get("novelty", {})),
        sandbox=SandboxSettings(
            **{k: v for k, v in data.get("sandbox", {}).items() if k != "docker"},
            docker=SandboxDockerSettings(**data.get("sandbox", {}).get("docker", {})),
        ),
        storage=StorageSettings(
            **{k: v for k, v in data.get("storage", {}).items() if k != "jobs"},
            jobs=StorageJobsSettings(**data.get("storage", {}).get("jobs", {})),
        ),
        memory=MemorySettings(**data.get("memory", {})),
        self_evaluator=SelfEvaluatorSettings(**data.get("self_evaluator", {})),
        meta_evolution=MetaEvolutionSettings(**data.get("meta_evolution", {})),
        evaluation_governance=EvaluationGovernanceSettings(**data.get("evaluation_governance", {})),
    )
