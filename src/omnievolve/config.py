"""OmniEvolve 配置管理.

S1-16: pydantic-settings 配置
- omnievolve.toml 加载
- 分层覆盖
- 类型安全
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EvolutionSettings(BaseSettings):
    """进化引擎配置."""

    max_generations: int = Field(default=50, gt=0)
    population_size: int = Field(default=8, gt=0)
    island_count: int = Field(default=4, gt=0)
    novelty_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    novelty_retry_limit: int = Field(default=3, ge=0)
    mutation_rate: float = Field(default=0.3, ge=0.0, le=1.0)
    crossover_rate: float = Field(default=0.15, ge=0.0, le=1.0)
    max_stagnation_gens: int = Field(default=5, gt=0)
    token_budget: int = Field(default=2_000_000, gt=0)
    compute_budget_sec: float = Field(default=0, ge=0)  # 0 表示不单独限制
    sandbox_timeout: float = Field(default=30.0, gt=0)
    sandbox_mem_limit_mb: int = Field(default=4096, gt=0)
    sandbox_pids_limit: int = Field(
        default=0, ge=0
    )  # 0=不施加 RLIMIT_NPROC（科学计算线程需要）；可设有限值收紧
    health_window_gens: int = Field(default=3, gt=0)
    # Fail closed until an independent equal-budget PolicyReplayExecutor is configured.
    self_evolve_enabled: bool = False
    async_pipeline_enabled: bool = False  # Phase 4: 原生异步流水线
    seed: int = Field(default=42, ge=0)
    novelty_enabled: bool = True
    progressive_eval_enabled: bool = False
    eval_repetitions: int = Field(default=1, ge=1, le=100)
    eval_confidence: float = Field(default=0.95, gt=0.0, lt=1.0)
    retrieval_budget: int = Field(default=8, ge=1, le=100)
    single_agent_mode: bool = False
    random_search_mode: bool = False
    reference_credit_enabled: bool = True
    reference_credit_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    qd_archive_enabled: bool = False
    qd_parent_probability: float = Field(default=0.15, ge=0.0, le=1.0)
    qd_max_cells_per_island: int = Field(default=128, gt=0)
    operator_portfolio_enabled: bool = False
    operator_portfolio_algorithm: Literal["ucb", "thompson"] = "ucb"
    operator_portfolio_ucb_c: float = Field(default=1.414, ge=0.0)
    # 3.1: 确定性去重 — 相同 artifact_hash 且已有完成评估时直接复用结果，
    # 跳过昂贵 sandbox（通过候选 mini-CV 均 16.4s）。关闭即回退重复评估。
    dedup_reuse_enabled: bool = True


class SelectionSettings(BaseSettings):
    """选择策略配置."""

    parent_selector: Literal[
        "lineage_ucb",
        "progressive_mcgs",
        "best",
        "tournament",
        "random",
        "power_law",
        "weighted",
    ] = "lineage_ucb"
    tournament_size: int = 3
    pareto_enabled: bool = True
    island_migration_interval: int = 5


class ModelRoutingSettings(BaseSettings):
    """模型路由配置."""

    algorithm: Literal["sliding_window_ucb", "discounted_ucb", "thompson"] = "sliding_window_ucb"
    window_size: int = 50
    ucb_c: float = 1.414
    cost_weight: float = 0.2
    latency_weight: float = 0.1
    role_conditioned: bool = True


# 1.1: 角色级输出 token 预算（默认，均低于全局 max_tokens）。
# 推理/输出 token 占 GLM 实测开销 63%，按角色差异化上限可显著降本；
# 截断由 LLMGateway 输出完整性守卫自动扩容到全局上限兜底。
DEFAULT_ROLE_MAX_TOKENS: dict[str, int] = {
    "director": 2048,
    "coder": 4096,
    "critic": 1024,
    "meta": 2048,
}


class ModelsSettings(BaseSettings):
    """模型配置."""

    heavy: list[str] = Field(default_factory=lambda: ["reasoning-model-primary"])
    light: list[str] = Field(default_factory=lambda: ["fast-model-primary"])
    max_tokens: int = Field(default=16384, gt=0)
    role_max_tokens: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_ROLE_MAX_TOKENS))
    routing: ModelRoutingSettings = Field(default_factory=ModelRoutingSettings)


class EmbeddingCodeSettings(BaseSettings):
    """代码嵌入配置."""

    provider: str = "local"
    model: str = "Qwen/Qwen3-Embedding-0.6B"
    revision: str = "default"
    dimension: int = 1024
    normalization: str = "provider_default"
    input_type: str = "document"
    device: Literal["cpu", "cuda"] = "cpu"  # 本地嵌入设备: "cpu" 或 "cuda"（GPU 环境设为 cuda）


class EmbeddingThoughtSettings(BaseSettings):
    """思想嵌入配置."""

    provider: str = "local"
    model: str = "Qwen/Qwen3-Embedding-0.6B"
    revision: str = "default"
    dimension: int = 1024
    normalization: str = "l2"
    input_type: str = "document"
    # 注意: thought embedder 尚未在 CLI/引擎中接线，device 等字段待贯通后再添加，
    # 避免死配置。


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
    # Epiplexity 辅助适应度（任务无关评估）
    # > 0 时启用: fitness = f_task + β * S_φ(code)
    epiplexity_beta: float = 0.0


class SandboxDockerSettings(BaseSettings):
    """Docker 沙箱配置."""

    image: str = "omnievolve/python-runner:latest"
    tmpfs_mb: int = 256
    inherit_host_env: bool = False


class SandboxSettings(BaseSettings):
    """沙箱配置."""

    backend: str = "docker"  # docker / trusted_subprocess / monty
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
    # ── Git 代码存储后端 ──
    code_backend: str = "cas"  # "cas" (default) | "git" (optional lineage backend)
    git_repo_path: str = ".omnievolve/code.git"  # bare repo
    git_worktree_dir: str = ".omnievolve/worktrees"  # worktree 根
    git_auto_gc_interval: int = 50  # 每 N 代 GC


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


class VerifierSettings(BaseSettings):
    """概率 LLM-as-a-Verifier 配置（第一轮：observer-only）.

    默认全部关闭；observer 是第一个可启用模式。
    live tie-breaker、adaptive allocation、PPT 分别独立开关。
    G/K/C 与预算必须进入 config snapshot 与 replay hash。
    """

    enabled: bool = False
    mode: Literal["observer", "parent_pair", "island_ppt"] = "observer"
    model: str = ""
    criteria: tuple[str, ...] = (
        "specification_fidelity",
        "mechanism_realization",
        "evidence_consistency",
    )
    granularity: int = Field(default=5, gt=0)
    repetitions: int = Field(default=1, ge=1, le=10)
    live_min_repetitions: int = Field(default=2, ge=1, le=10)
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    minimum_probability_coverage: float = Field(default=0.95, gt=0.0, le=1.0)
    search_bonus_cap: float = Field(default=0.01, ge=0.0, le=1.0)
    task_tie_tolerance: float = Field(default=0.01, ge=0.0, le=1.0)
    max_calls_per_candidate: int = Field(default=6, gt=0)
    token_budget_ratio: float = Field(default=0.10, gt=0.0, le=1.0)
    fail_closed_in_research: bool = True
    ppt_min_candidates: int = Field(default=8, gt=0)
    ppt_pivots: int = Field(default=3, gt=0)
    adaptive_benchmark_enabled: bool = False


class TieBreakerSettings(BaseSettings):
    """2.4: 离散集成 tie-breaker 配置（logprobs-free，默认关闭）.

    任务分数打平时用 K 次 A/B 成对比较（奇偶交换位置）聚合偏好，
    给 search_score 加有界 bonus，只影响 LineageUCB 搜索信用；
    不触碰 passed/primary_score。
    """

    enabled: bool = False
    tolerance: float = Field(default=0.01, ge=0.0, lt=1.0)
    repetitions: int = Field(default=3, ge=1, le=10)
    search_bonus_cap: float = Field(default=0.01, ge=0.0, le=1.0)
    model: str = ""


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
    verifier: VerifierSettings = Field(default_factory=VerifierSettings)
    tiebreaker: TieBreakerSettings = Field(default_factory=TieBreakerSettings)


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
            max_tokens=data.get("models", {}).get("max_tokens", 16384),
            role_max_tokens={
                **DEFAULT_ROLE_MAX_TOKENS,
                **data.get("models", {}).get("role_max_tokens", {}),
            },
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
        verifier=VerifierSettings(**data.get("verifier", {})),
        tiebreaker=TieBreakerSettings(**data.get("tiebreaker", {})),
    )


# --------------------------------------------------------------------------- #
#  组件配置构造器：OmniEvolveSettings → 引擎可用的配置对象
# --------------------------------------------------------------------------- #


def build_evolution_config(settings: OmniEvolveSettings):  # -> EvolutionConfig
    """从 OmniEvolveSettings 构造 EvolutionConfig.

    避免在引擎层重复定义默认值。
    """
    from omnievolve.engine.evolution_engine import EvolutionConfig

    e = settings.evolution
    return EvolutionConfig(
        max_generations=e.max_generations,
        population_size=e.population_size,
        island_count=e.island_count,
        novelty_threshold=e.novelty_threshold,
        novelty_retry_limit=e.novelty_retry_limit,
        mutation_rate=e.mutation_rate,
        crossover_rate=e.crossover_rate,
        max_stagnation_gens=e.max_stagnation_gens,
        token_budget=e.token_budget,
        compute_budget_sec=e.compute_budget_sec or None,
        sandbox_timeout=e.sandbox_timeout,
        sandbox_mem_limit_mb=e.sandbox_mem_limit_mb,
        sandbox_pids_limit=e.sandbox_pids_limit,
        health_window_gens=e.health_window_gens,
        meta_canary_budget_ratio=settings.meta_evolution.meta_canary_budget_ratio,
        parent_selector=settings.selection.parent_selector,
        tournament_size=settings.selection.tournament_size,
        island_migration_interval=settings.selection.island_migration_interval,
        ucb_c=settings.models.routing.ucb_c,
        self_evolve_enabled=e.self_evolve_enabled,
        seed=e.seed,
        novelty_enabled=e.novelty_enabled,
        progressive_eval_enabled=e.progressive_eval_enabled,
        eval_repetitions=e.eval_repetitions,
        eval_confidence=e.eval_confidence,
        retrieval_budget=e.retrieval_budget,
        single_agent_mode=e.single_agent_mode,
        random_search_mode=e.random_search_mode,
        reference_credit_enabled=e.reference_credit_enabled,
        reference_credit_weight=e.reference_credit_weight,
        qd_archive_enabled=e.qd_archive_enabled,
        qd_parent_probability=e.qd_parent_probability,
        qd_max_cells_per_island=e.qd_max_cells_per_island,
        operator_portfolio_enabled=e.operator_portfolio_enabled,
        operator_portfolio_algorithm=e.operator_portfolio_algorithm,
        operator_portfolio_ucb_c=e.operator_portfolio_ucb_c,
        dedup_reuse_enabled=e.dedup_reuse_enabled,
        tiebreaker_enabled=settings.tiebreaker.enabled,
        tiebreaker_tolerance=settings.tiebreaker.tolerance,
        tiebreaker_repetitions=settings.tiebreaker.repetitions,
        tiebreaker_search_bonus_cap=settings.tiebreaker.search_bonus_cap,
        tiebreaker_model=settings.tiebreaker.model,
    )


def build_sandbox_policy(settings: OmniEvolveSettings):  # -> SandboxPolicy
    """从 OmniEvolveSettings 构造 SandboxPolicy."""
    from omnievolve.sandbox.base import SandboxPolicy

    s = settings.sandbox
    return SandboxPolicy(
        timeout_sec=s.timeout_sec,
        mem_limit_mb=s.mem_limit_mb,
        cpu_limit=s.cpu_limit,
        pids_limit=s.pids_limit,
        network_mode=s.network_mode,
        read_only_root=s.read_only_root,
        run_as_non_root=s.run_as_non_root,
        drop_capabilities=s.drop_capabilities,
        no_new_privileges=s.no_new_privileges,
        tmpfs_mb=s.docker.tmpfs_mb,
    )


def build_model_slots(settings: OmniEvolveSettings):  # -> list[ModelSlot]
    """从 OmniEvolveSettings 构造 ModelSlot 列表.

    将配置中的 heavy/light 模型名映射为 ModelSlot。
    真实定价由用户在配置中提供或使用占位值。
    """
    from omnievolve.agents.router import ModelSlot

    slots: list[ModelSlot] = []
    for name in settings.models.heavy:
        slots.append(
            ModelSlot(
                name=name,
                tier="heavy",
                cost_per_1k_input=0.01,
                cost_per_1k_output=0.03,
                avg_latency_ms=2000.0,
                capabilities={"reasoning", "code"},
            )
        )
    for name in settings.models.light:
        slots.append(
            ModelSlot(
                name=name,
                tier="light",
                cost_per_1k_input=0.0002,
                cost_per_1k_output=0.0006,
                avg_latency_ms=500.0,
                capabilities={"code"},
            )
        )
    return slots


def load_evaluator(spec: str):
    """从 "module:Class" 或 "module.path.Class" 字符串加载评估器.

    Args:
        spec: 例如 "omnievolve.eval.demo_evaluator:PythonUnitTestEvaluator"

    Returns:
        评估器类（未实例化）
    """
    import importlib
    import sys

    if ":" in spec:
        module_path, class_name = spec.split(":", 1)
    elif "." in spec:
        module_path, class_name = spec.rsplit(".", 1)
    else:
        raise ValueError(
            f"Invalid evaluator spec {spec!r}; expected 'module:Class' or 'module.path.Class'"
        )

    # Console-script entry points set sys.path[0] to the scripts directory,
    # not necessarily the user's current project. Evaluators are intentionally
    # loaded from that project (for example examples.foo.evaluator:Evaluator).
    project_dir = str(Path.cwd())
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)

    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls
