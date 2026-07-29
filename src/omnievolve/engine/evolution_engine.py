"""EvolutionEngine - 完整进化引擎.

Fast Loop（单代候选进化，11 步）+ Slow Loop（策略窗口评估与受控元进化）。

Fast Loop 每一代：
    1. Router.select      → 按角色分配模型
    2. ParentSelector     → MCTS 引导选择父代
    3. (可选) Crossover   → 多父代跨分支融合
    4. Director           → 进化思想
    5. NoveltyGate        → 多级新颖性门
    6. Coder              → 生成代码
    7. Critic             → 静态审查（带重试）
    8. ArtifactStore      → 保存 source / lineage / vector_index_job
    9. TaskEvaluator      → build_plan
    10. SandboxBackend    → execute
    11. parse_result      → 更新 best / island / MCTS / memory / router / budget

Slow Loop 每 health_window_gens 代：
    TelemetryAggregator → HealthPolicy.assess → MetaPlanner.propose
    → Governance 分类 → 创建 Challenger → Replay/Canary 比较 → Promote/Reject

参考 OpenEvolve: 支持 SIGINT/SIGTERM 优雅关闭，保存当前状态后退出。
"""

from __future__ import annotations

import logging
import random
import signal
import time
import warnings
from dataclasses import dataclass, field, replace
from typing import Any

from omnievolve.agents.coder import Coder
from omnievolve.agents.context_builder import ContextBuilder
from omnievolve.agents.critic import Critic
from omnievolve.agents.director import Director
from omnievolve.agents.llm_gateway import LLMGateway
from omnievolve.agents.router import ModelRouter, ModelSlot, RouteContext
from omnievolve.engine.crossover import CrossoverOperator
from omnievolve.engine.island import IslandManager
from omnievolve.engine.mcts import LineageUCB
from omnievolve.engine.memory import MemoryStore
from omnievolve.engine.novelty import NoveltyGate
from omnievolve.engine.selection import ParentSelector
from omnievolve.eval.evaluation_run import EvaluationRunRepository
from omnievolve.eval.evaluator_registry import EvaluatorRegistry
from omnievolve.eval.task_evaluator import (
    EvalOutput,
    TaskEvaluator,
)
from omnievolve.eval.telemetry import HealthOutput, SelfEvaluator
from omnievolve.exceptions import (
    EvolutionError,
    LLMError,
    SandboxError,
    StorageError,
)
from omnievolve.meta.governance import (
    GovernancePolicy,
    L0PolicyMutator,
    MetaPlanner,
    ReplayEvaluator,
)
from omnievolve.meta.policy_archive import PolicyArchive
from omnievolve.meta.policy_genome import SearchPolicyGenome
from omnievolve.sandbox.base import (
    SandboxBackend,
)
from omnievolve.storage.db import Database
from omnievolve.storage.graph_store import GraphStore
from omnievolve.storage.repositories.candidate_repo import CandidateRepository
from omnievolve.storage.repositories.experiment_repo import ExperimentRepository
from omnievolve.storage.repositories.prompt_repo import PromptVersionRepository
from omnievolve.storage.vector_indexer import VectorIndexer
from omnievolve.utils.token_counter import BudgetGuard, BudgetState

logger = logging.getLogger(__name__)


def _nested_tuple(value: Any) -> Any:
    """Convert JSON arrays back to tuples for ``random.setstate``."""
    if isinstance(value, list):
        return tuple(_nested_tuple(item) for item in value)
    return value


@dataclass
class EvolutionConfig:
    """进化配置."""

    max_generations: int = 50
    population_size: int = 8
    island_count: int = 4
    novelty_threshold: float = 0.92
    novelty_retry_limit: int = 3
    mutation_rate: float = 0.3
    crossover_rate: float = 0.15
    max_stagnation_gens: int = 5
    token_budget: int = 2_000_000
    compute_budget_sec: float | None = None
    sandbox_timeout: float = 30.0
    sandbox_mem_limit_mb: int = 4096
    health_window_gens: int = 3
    meta_canary_budget_ratio: float = 0.1
    parent_selector: str = "lineage_ucb"
    tournament_size: int = 3
    island_migration_interval: int = 5
    ucb_c: float = 1.414
    uct_decay_progress: float = 0.5  # P1-1: 探索衰减完成点
    uct_c_min: float = 0.2  # P1-1: 探索常数下限
    progressive_eval_enabled: bool = False  # Phase 3: 渐进式评估
    eval_repetitions: int = 1
    eval_confidence: float = 0.95
    fusion_mode: str = "mechanical"  # 2.2: mechanical / llm
    epiplexity_beta: float = 0.0  # 辅助适应度权重（0=关闭）
    self_evolve_enabled: bool = False
    leakage_score_threshold: float = 0.9  # 触发泄漏检测的分数阈值
    leakage_penalty_factor: float = 0.5  # 泄漏嫌疑时的分数惩罚系数
    git_auto_gc_interval: int = 10  # Git 后端周期性 GC 代数间隔
    seed: int = 42
    novelty_enabled: bool = True
    single_agent_mode: bool = False
    random_search_mode: bool = False
    reference_credit_enabled: bool = True
    reference_credit_weight: float = 0.25


@dataclass
class EvolutionResult:
    """进化结果."""

    best_candidate_id: str | None
    best_artifact_hash: str | None
    best_score: float | None
    champion_policy_id: str
    total_generations: int
    total_candidates: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_compute_sec: float = 0.0
    evolution_graph_path: str | None = None
    final_health: HealthOutput | None = field(default=None, repr=False)


class EvolutionEngine:
    """完整进化引擎.

    执行 Fast Loop（候选进化）并按窗口触发 Slow Loop（受控策略进化）。
    支持幂等恢复（resume）。
    """

    def __init__(
        self,
        db: Database,
        artifact_store: Any,
        task_evaluator: TaskEvaluator,
        sandbox: SandboxBackend,
        llm: LLMGateway,
        *,
        experiment_id: str = "",
        evaluator_version_id: str = "",
        environment_version_id: str = "",
        config: EvolutionConfig | None = None,
        search_policy: SearchPolicyGenome | None = None,
        model_slots: list[ModelSlot] | None = None,
        # 可注入的高级组件（便于测试；默认自动构造）
        router: ModelRouter | None = None,
        island_manager: IslandManager | None = None,
        parent_selector: ParentSelector | None = None,
        crossover: CrossoverOperator | None = None,
        policy_archive: PolicyArchive | None = None,
        governance: GovernancePolicy | None = None,
        self_evaluator: SelfEvaluator | None = None,
        meta_planner: MetaPlanner | None = None,
        replay_evaluator: ReplayEvaluator | None = None,
        policy_replay_executor: Any | None = None,
        graph_store: GraphStore | None = None,
        vector_indexer: VectorIndexer | None = None,
        prompt_repo: PromptVersionRepository | None = None,
    ) -> None:
        self._db = db
        self._artifact_store = artifact_store
        # CodeStore: 代码存储后端（如果有 CodeStore Protocol 能力则直接使用）
        # artifact_store 可能是 ArtifactStore / CASCodeStore / GitCodeStore
        # 所有通过 CodeStore Protocol 的调用点会检查 backend_name
        self._task_evaluator = task_evaluator
        self._sandbox = sandbox
        self._llm = llm

        self._experiment_id = experiment_id
        self._evaluator_version_id = evaluator_version_id or getattr(
            task_evaluator, "version_id", ""
        )
        self._environment_version_id = environment_version_id or getattr(
            sandbox, "environment_version_id", ""
        )
        self._config = config or EvolutionConfig()
        configured_selector = self._config.parent_selector
        if configured_selector == "progressive_mcgs":
            warnings.warn(
                "progressive_mcgs is deprecated; use lineage_ucb",
                DeprecationWarning,
                stacklevel=2,
            )
            configured_selector = "lineage_ucb"
        self._search_policy = search_policy or SearchPolicyGenome(
            parent_selector=configured_selector
        )
        # 配置中的 epiplexity_beta 覆盖 genome 默认值（允许不开 Slow Loop 也能用）
        if self._config.epiplexity_beta > 0:
            self._search_policy = replace(
                self._search_policy, epiplexity_beta=self._config.epiplexity_beta
            )

        # Repository / Store
        self._candidate_repo = CandidateRepository(db)
        self._eval_repo = EvaluationRunRepository(db)
        self._evaluator_registry = EvaluatorRegistry(db)
        self._experiment_repo = ExperimentRepository(db)
        self._memory_store = MemoryStore(db)
        self._graph_store = graph_store or GraphStore(db)
        self._novelty_gate = NoveltyGate(embedding_threshold=self._config.novelty_threshold)

        # Phase 4.4: Job Store — kill -9 恢复能力
        from omnievolve.storage.job_store import JobStore

        self._job_store = JobStore(db)

        # 预算
        budget_state = BudgetState(
            token_budget=self._config.token_budget,
            compute_budget_sec=self._config.compute_budget_sec,
        )
        self._budget_guard = BudgetGuard(budget_state)

        # 1.1: 将 BudgetGuard 注入 LLMGateway，使 LLM token 消耗传播到预算系统
        if hasattr(llm, "_budget_guard"):
            llm._budget_guard = self._budget_guard  # noqa: SLF001

        # Agents
        self._director = Director(llm)
        self._coder = Coder(llm)
        self._critic = Critic(use_syntax_check=True)

        # S5-05: ContextBuilder 按 token 预算裁剪上下文
        self._context_builder = ContextBuilder(
            total_token_budget=min(self._config.token_budget, 100_000),
        )

        # 搜索组件
        self._mcts = LineageUCB(
            exploration=self._config.ucb_c,
            schedule="progressive",
            c_min=self._config.uct_c_min,  # P1-1
            decay_point=self._config.uct_decay_progress,  # P1-1
        )
        self._island_manager = island_manager or IslandManager(
            num_islands=self._config.island_count,
            migration_interval=self._config.island_migration_interval,
        )
        policy_selector = self._search_policy.parent_selector
        selector_strategy = (
            "tournament"
            if policy_selector == "lineage_ucb"
            else policy_selector
        )
        self._parent_selector = parent_selector or ParentSelector(
            db,
            strategy=selector_strategy,
            tournament_size=self._config.tournament_size,
        )
        self._selection_injected = parent_selector is not None
        self._selection_mode = "injected" if parent_selector is not None else policy_selector
        self._crossover = crossover or CrossoverOperator()

        # 模型路由
        self._model_slots = list(model_slots or [])
        self._router_injected = router is not None
        self._router = router
        if self._router is None and model_slots:
            self._router = ModelRouter(
                model_slots,
                algorithm=self._search_policy.model_routing_policy,
            )

        # Slow Loop 组件
        self._policy_archive = policy_archive or PolicyArchive(db)
        self._governance = governance or GovernancePolicy()
        self._self_evaluator = self_evaluator
        self._meta_planner = meta_planner
        self._replay_evaluator = replay_evaluator or ReplayEvaluator(
            budget_ratio=self._config.meta_canary_budget_ratio,
        )
        self._l0_mutator = L0PolicyMutator(self._governance)

        if (
            policy_replay_executor is None
            and self._config.self_evolve_enabled
            and getattr(artifact_store, "backend_name", None) == "cas"
            and hasattr(llm, "fork")
        ):
            from omnievolve.engine.policy_canary import LocalPolicyArmRunner
            from omnievolve.meta.policy_replay import PolicyCanaryRunner

            policy_replay_executor = PolicyCanaryRunner(
                LocalPolicyArmRunner(
                    source_store=artifact_store,
                    task_evaluator=task_evaluator,
                    sandbox=sandbox,
                    llm=llm,
                    evolution_config=self._config,
                    model_slots=self._model_slots,
                )
            )

        # 插件自动发现 — EvoX evox_ext 模式: 启动时扫描并加载所有已安装插件
        from omnievolve.plugins.discovery import discover_plugins

        discover_plugins()
        logger.info("Engine initialized, plugins loaded")

        # 向量 Outbox + Prompt 版本化
        self._vector_indexer = vector_indexer
        if self._vector_indexer:
            self._vector_indexer.set_artifact_store(artifact_store)
        self._prompt_repo = prompt_repo or PromptVersionRepository(db)
        self._code_profile_id: str | None = None  # run() 时注册
        self._profiler: Any = None  # PipelineProfiler 挂载点（None=零开销）

        # 向量混合检索器（读路径 — 与 VectorIndexer 共享 backend/embedder）
        self._hybrid_retriever = None
        if vector_indexer is not None:
            from omnievolve.storage.vector_store import HybridRetriever

            self._hybrid_retriever = HybridRetriever(
                db,
                vector_indexer._backend,  # noqa: SLF001
                vector_indexer._embedder,  # noqa: SLF001
            )

        # T1: 提取 InspirationCollector
        from omnievolve.engine.inspiration import InspirationCollector

        self._inspiration = InspirationCollector(db, self._candidate_repo, artifact_store)

        # T1: 提取 FastLoopStep — 11步候选进化委托给独立组件
        from omnievolve.engine.fast_loop import FastLoopStep

        self._fast_loop: FastLoopStep | None = None  # 延迟设置（需要 self 引用）

        # T1: 提取 SlowLoopController — 慢循环逻辑委托给独立组件
        from omnievolve.engine.slow_loop import SlowLoopController

        self._slow_loop = SlowLoopController(
            db,
            self_evaluator=self_evaluator,
            meta_planner=meta_planner,
            governance=self._governance,
            l0_mutator=self._l0_mutator,
            replay_evaluator=self._replay_evaluator,
            policy_archive=self._policy_archive,
            experiment_repo=self._experiment_repo,
            prompt_repo=self._prompt_repo,
            artifact_store=artifact_store,
            policy_replay_executor=policy_replay_executor,
        )

        # T1: 提取 CheckpointManager + EngineSetup
        from omnievolve.engine.checkpoint import CheckpointManager
        from omnievolve.engine.setup import EngineSetup

        self._checkpoint = CheckpointManager(db)
        self._setup = EngineSetup(db, self._experiment_repo, self._policy_archive)

        # 进化状态
        self._current_generation = 0
        self._checkpoint_loaded = False
        self._best_candidate: tuple[str, float] | None = None
        self._champion_policy_id = "default"
        self._total_candidates = 0
        self._start_time = 0.0
        self._recent_scores: list[float] = []  # 最近窗口分数（供 Slow Loop 比较）
        self._slow_loop_triggered = False
        self._last_selection_trace: dict[str, Any] | None = None
        # ShinkaEvolve: meta-scratchpad 跨代累积全局洞察
        self._meta_scratchpad: str = ""
        # 失败方向追踪（用于 meta-scratchpad 更新）
        self._failed_directions: list[str] = []
        # OpenEvolve: graceful shutdown flag (SIGINT/SIGTERM)
        self._shutdown_requested = False
        # Epiplexity 估算器（延迟初始化）
        self._epiplexity_est: Any = None

        # T1: FastLoopStep 需要完整的 self，在所有字段初始化后创建
        self._fast_loop = FastLoopStep(self)

    # ------------------------------------------------------------------ #
    #  公共 API
    # ------------------------------------------------------------------ #

    @property
    def current_generation(self) -> int:
        return self._current_generation

    def get_best(self) -> tuple[str, float] | None:
        return self._best_candidate

    @property
    def champion_policy_id(self) -> str:
        return self._champion_policy_id

    def run(
        self, initial_code: str | dict[str, str], task_name: str
    ) -> EvolutionResult:
        """启动进化循环（Fast Loop + 按窗口触发 Slow Loop）.

        支持 SIGINT/SIGTERM 优雅关闭（参考 OpenEvolve）。
        """
        from omnievolve.utils.seed import set_global_seed

        set_global_seed(self._config.seed)
        self._start_time = time.time()
        self._shutdown_requested = False

        # OpenEvolve: 信号处理器 — 优雅关闭
        def _handle_shutdown(signum: int, frame: object) -> None:
            logger.info("Received signal %d, initiating graceful shutdown...", signum)
            self._shutdown_requested = True

        prev_int = signal.signal(signal.SIGINT, _handle_shutdown)
        prev_term = signal.signal(signal.SIGTERM, _handle_shutdown)
        try:
            result = self._run_evolution(initial_code, task_name)
        finally:
            signal.signal(signal.SIGINT, prev_int)
            signal.signal(signal.SIGTERM, prev_term)
        return result

    def _run_evolution(
        self, initial_code: str | dict[str, str], task_name: str
    ) -> EvolutionResult:
        """进化主循环（内部实现）."""
        logger.info("Starting evolution: %s", task_name)

        # Git 后端: 绑定到当前 task（确保正确的 per-task 仓库）
        store = self._artifact_store
        if hasattr(store, "bind_experiment"):
            store.bind_experiment(self._experiment_id, task_name=task_name)

        # 注册初始 Champion Policy
        self._ensure_champion_policy()
        self._ensure_version_rows()

        # 存储并评估初始代码
        initial_manifest_hash = None
        if hasattr(store, "store_snapshot"):
            from omnievolve.storage.code_store import resolve_snapshot_refs

            initial_ref = store.store_snapshot(
                initial_code,
                message="initial candidate",
                meta={"entrypoint": "main.py"} if isinstance(initial_code, dict) else None,
            )
            initial_hash, initial_manifest_hash = resolve_snapshot_refs(store, initial_ref)
        else:
            if not isinstance(initial_code, str):
                raise TypeError("This storage backend does not support multi-file snapshots")
            initial_hash = store.store_text(initial_code, "source")
        initial_candidate = self._candidate_repo.create_candidate(
            experiment_id=self._experiment_id,
            task_id=task_name,
            generation=0,
            artifact_hash=initial_hash,
            manifest_hash=initial_manifest_hash,
            search_policy_id=self._champion_policy_id,
        )
        initial_id = initial_candidate.id
        self._mcts.add_node(initial_id, parent=None, prior=1.0)
        self._total_candidates += 1
        self._evaluate_candidate(initial_id, initial_hash, initial_manifest_hash)
        self._island_manager.assign_candidate(initial_id, "island_0")

        # 设置 baseline
        self._experiment_repo.set_baseline(self._experiment_id, initial_id)

        # 主循环
        for gen in range(1, self._config.max_generations + 1):
            if self._shutdown_requested:
                logger.warning("Shutdown requested, stopping evolution at gen %d", gen - 1)
                break

            if self._budget_guard.state.is_exhausted:
                logger.warning("Budget exhausted, stopping evolution")
                break

            self._current_generation = gen

            # P1: 更新 MCTS 探索进度（渐进衰减）
            self._mcts.set_progress(gen, self._config.max_generations)

            self._step_generation(gen, task_name)

            # 岛间迁移
            if self._island_manager.should_migrate(gen):
                self._island_manager.migrate(gen)

            # Slow Loop：每 health_window_gens 代触发
            if self._config.self_evolve_enabled and gen % self._config.health_window_gens == 0:
                self._run_slow_loop(gen)

            logger.info(
                "Generation %d done, best=%s",
                gen,
                f"{self._best_candidate[1]:.4f}" if self._best_candidate else "N/A",
            )

            # P1: 检查点 — 每代结束时持久化易失状态（崩溃恢复）
            self._save_checkpoint()

            # T2: MCTS 内存修剪 — 超过 max_nodes 时删除 closed/pruned 叶子
            if gen % 10 == 0:  # 每 10 代修剪一次（避免频繁 DB 查询）
                self._mcts.prune(self._db)

        return self._finalize(task_name)

    def resume(self, experiment_id: str) -> EvolutionResult:
        """恢复实验：重载状态，从中断处继续.

        重新认领租约过期的任务，从最大 generation + 1 继续。
        """
        self._experiment_id = experiment_id

        # P1: 恢复检查点状态（meta_scratchpad 等易失状态）
        self._load_checkpoint()

        exp = self._experiment_repo.get(experiment_id)
        if exp is None:
            raise ValueError(f"Experiment not found: {experiment_id}")

        store = self._artifact_store
        if hasattr(store, "bind_experiment"):
            store.bind_experiment(experiment_id, task_name=exp.task_name)

        if self._checkpoint_loaded:
            # The checkpoint generation is the last fully committed boundary.
            # Rows from a crashed partial next generation remain auditable but
            # are excluded from future selection/replay.
            self._db.execute(
                "UPDATE candidate SET status = 'aborted' "
                "WHERE experiment_id = ? AND generation > ?",
                (experiment_id, self._current_generation),
            )
        else:
            # Backward compatibility for schema-v1 experiments.
            row = self._db.fetchone(
                "SELECT MAX(generation) as max_gen FROM candidate WHERE experiment_id = ?",
                (experiment_id,),
            )
            self._current_generation = row["max_gen"] if row and row["max_gen"] else 0

        # 恢复 best
        bests = self._candidate_repo.get_best_candidates(
            experiment_id,
            self._evaluator_version_id,
            self._environment_version_id,
            limit=1,
        )
        if bests:
            cand, score = bests[0]
            self._best_candidate = (cand.id, score)

        # 恢复 champion policy
        champ = self._policy_archive.get_champion(experiment_id)
        if champ:
            self._champion_policy_id = champ.id
            self._search_policy = champ.genome
            self._apply_search_policy_runtime()

        # 恢复 MCTS 图
        self._rebuild_mcts(experiment_id)

        # Phase 4.4: 恢复孤立任务（租约过期的 Job 重新入队）
        try:
            recovered = self._job_store.recover_orphan_jobs()
            if recovered:
                logger.info("Recovered %d orphan jobs on resume", recovered)
        except Exception:
            logger.debug("Job recovery failed", exc_info=True)

        logger.info(
            "Resumed experiment %s at generation %d", experiment_id, self._current_generation
        )

        task_name = exp.task_name
        # 从下一代继续
        for gen in range(self._current_generation + 1, self._config.max_generations + 1):
            if self._budget_guard.state.is_exhausted:
                logger.warning("Budget exhausted, stopping resume before gen %d", gen)
                break
            self._current_generation = gen
            self._mcts.set_progress(gen, self._config.max_generations)
            self._step_generation(gen, task_name)
            if self._island_manager.should_migrate(gen):
                self._island_manager.migrate(gen)
            if self._config.self_evolve_enabled and gen % self._config.health_window_gens == 0:
                self._run_slow_loop(gen)
            self._save_checkpoint()

        return self._finalize(task_name)

    # ------------------------------------------------------------------ #
    #  设计文档 5.4 节公共 API
    # ------------------------------------------------------------------ #

    def step(self, task_name: str | None = None) -> dict:
        """执行单代候选进化.

        设计文档 5.4 节: `step() -> GenerationResult`
        """
        gen = self._current_generation + 1
        self._current_generation = gen
        self._mcts.set_progress(gen, self._config.max_generations)
        name = task_name or "default"
        self._step_generation(gen, name)
        return {
            "generation": gen,
            "total_candidates": self._total_candidates,
            "best_score": self._best_candidate[1] if self._best_candidate else None,
        }

    def assess_policy_window(self) -> HealthOutput | None:
        """聚合当前 SearchPolicyVersion 在窗口内的轨道 B 指标.

        设计文档 5.4 节: `assess_policy_window() -> HealthOutput`
        """
        if self._self_evaluator is None:
            return None
        from omnievolve.eval.telemetry import TelemetryAggregator

        aggregator = TelemetryAggregator(self._db)
        window_start = max(1, self._current_generation - self._config.health_window_gens)
        metrics = aggregator.aggregate(
            experiment_id=self._experiment_id,
            generation_start=window_start,
            generation_end=self._current_generation,
        )
        from omnievolve.eval.telemetry import HealthPolicy

        policy = HealthPolicy(self._db)
        return policy.assess(
            metrics,
            experiment_id=self._experiment_id,
            generation_start=window_start,
            generation_end=self._current_generation,
            search_policy_id=self._champion_policy_id,
        )

    def run_policy_challenger(self, actions: list) -> dict:
        """创建 Challenger，执行等预算 Replay/Canary.

        设计文档 5.4 节: `run_policy_challenger(actions) -> PolicyExperimentResult`
        """
        new_policy, new_id, triggered = self._slow_loop.run(
            experiment_id=self._experiment_id,
            current_gen=self._current_generation,
            health_window_gens=self._config.health_window_gens,
            search_policy=self._search_policy,
            recent_scores=self._recent_scores,
            champion_policy_id=self._champion_policy_id,
            coder_system_prompt=getattr(self._coder, "_system_prompt", ""),  # noqa: SLF001
        )
        return {
            "triggered": triggered,
            "new_policy_id": new_id,
            "promoted": new_policy is not None,
        }

    # ------------------------------------------------------------------ #
    #  Fast Loop
    # ------------------------------------------------------------------ #

    def _step_generation(self, generation: int, task_name: str) -> None:
        """执行一代进化（Fast Loop 11 步 × population_size 个候选）."""
        for i in range(self._config.population_size):
            if self._shutdown_requested or not self._budget_guard.can_proceed():
                break
            try:
                island_id = f"island_{i % self._config.island_count}"
                self._evolve_one(generation, task_name, island_id, slot=i)
            except (EvolutionError, LLMError, SandboxError, StorageError):
                logger.exception("Evolution failed for candidate slot %d", i)

        # Stagnation is a generation-level signal, never a per-candidate pass flag.
        stagnation_updates = self._island_manager.finalize_generation(generation)
        logger.info(
            "generation_stagnation generation=%d improvements=%s",
            generation,
            {key: value for key, value in stagnation_updates.items() if value},
        )

        # 设计文档 §4.2: 每代后消费向量索引 Outbox
        if self._vector_indexer:
            try:
                self._vector_indexer.process_batch()
            except Exception:
                logger.debug("Vector index batch processing failed", exc_info=True)

    def _select_parents(self, island_id: str) -> tuple[list[str], str]:
        """选择父代（步骤 2）：P1-2 软切换 + MCTS 引导 + ParentSelector 兖底.

        P1-2: 探索-利用软切换
        - w(t) 概率用 MCTS 探索（前期）
        - 1-w(t) 概率用 Top-K 利用（后期）

        Returns:
            (parent_ids, relation_type)  relation_type ∈ {mutate, crossover}
        """
        import random

        from omnievolve.engine.selection import (
            compute_exploration_weight,
            select_top_k_exploitation,
        )

        # P1-2: 计算探索权重
        w = compute_exploration_weight(self._mcts._progress)  # noqa: SLF001

        def finish(ids: list[str], relation: str, mechanism: str) -> tuple[list[str], str]:
            self._last_selection_trace = {
                "experiment_id": self._experiment_id,
                "generation": self._current_generation,
                "island_id": island_id,
                "configured_strategy": self._selection_mode,
                "mechanism": mechanism,
                "exploration_weight": w,
                "parent_ids": list(ids),
                "relation_type": relation,
            }
            logger.info("parent_selection %s", self._last_selection_trace)
            return ids, relation

        island = self._island_manager.get_island(island_id)
        if island is not None and not island.candidates:
            experiment = self._experiment_repo.get(self._experiment_id)
            baseline_id = experiment.baseline_candidate_id if experiment else None
            if baseline_id:
                island.add_candidate(baseline_id)
                return finish([baseline_id], "mutate", "baseline_bootstrap")

        local_candidate_ids = list(island.candidates) if island else []
        min_parents = getattr(self._crossover, "min_parents", 2)
        if self._selection_mode != "lineage_ucb":
            selected = self._parent_selector.select(
                self._experiment_id,
                self._evaluator_version_id,
                self._environment_version_id,
                count=min_parents,
                island_id=island_id,
                candidate_ids=local_candidate_ids,
            )
            if len(selected) >= 2 and random.random() < self._config.crossover_rate:
                return finish(selected, "crossover", self._selection_mode)
            return finish(selected[:1], "mutate", self._selection_mode)

        # 1. 尝试 MCTS 选择：从该岛屿的最佳候选出发下降到叶节点
        mcts_parent: str | None = None
        if island and island.elite_archive:
            root = island.elite_archive[0][0]
            if root in self._mcts._nodes:  # noqa: SLF001 - 检查节点是否已注册
                mcts_parent = self._mcts.select(root)

        # 2. ParentSelector 兖底（需要有评估分数的候选）
        scored = self._parent_selector.select(
            self._experiment_id,
            self._evaluator_version_id,
            self._environment_version_id,
            count=min_parents,
            island_id=island_id,
            candidate_ids=local_candidate_ids,
        )

        # 3. P1-2: 软切换决策
        use_exploitation = random.random() > w and scored

        if use_exploitation:
            # Top-K 利用模式：从全局最高分中加权选择
            # Fix 3: MCTS select() 已加虚拟损失但不会被 backprop，立即回滚
            self._mcts.rollback_last_select()  # noqa: SLF001
            all_scored = self._parent_selector._get_scored_candidates(  # noqa: SLF001
                self._experiment_id,
                self._evaluator_version_id,
                self._environment_version_id,
                None,
                island_id=island_id,
                candidate_ids=local_candidate_ids,
            )
            top_k_id = select_top_k_exploitation(all_scored, k=5)
            if top_k_id:
                return finish([top_k_id], "mutate", "top_k_exploitation")

        # 4. 探索模式（默认）
        use_crossover = len(scored) >= 2 and random.random() < self._config.crossover_rate

        if use_crossover:
            # Fix 3: crossover 使用 ParentSelector 结果而非 MCTS 路径，回滚虚拟损失
            self._mcts.rollback_last_select()  # noqa: SLF001
            return finish(scored, "crossover", "tournament_crossover")
        if mcts_parent:
            return finish([mcts_parent], "mutate", "lineage_ucb")
        if scored:
            # Fix 3: ParentSelector fallback 非 MCTS 路径，回滚虚拟损失
            self._mcts.rollback_last_select()  # noqa: SLF001
            return finish(scored[:1], "mutate", "tournament_fallback")
        return finish([], "mutate", "empty")

    def _evolve_one(
        self,
        generation: int,
        task_name: str,
        island_id: str,
        *,
        slot: int = 0,
    ) -> tuple[str | None, str]:
        """执行单个候选的完整进化链（T1: 委托给 FastLoopStep）."""
        assert self._fast_loop is not None
        return self._fast_loop.evolve_one(generation, task_name, island_id, slot=slot)

    def _evaluate_candidate(
        self,
        candidate_id: str,
        artifact_hash: str,
        manifest_hash: str | None = None,
    ) -> EvalOutput | None:
        """评估候选（T1: 委托给 FastLoopStep）."""
        assert self._fast_loop is not None
        return self._fast_loop.evaluate_candidate(
            candidate_id, artifact_hash, manifest_hash
        )

    # ------------------------------------------------------------------ #
    #  Slow Loop
    # ------------------------------------------------------------------ #

    def _run_slow_loop(self, current_gen: int) -> None:
        """执行 Slow Loop（T1: 委托给 SlowLoopController）."""
        new_policy, new_id, triggered = self._slow_loop.run(
            experiment_id=self._experiment_id,
            current_gen=current_gen,
            health_window_gens=self._config.health_window_gens,
            search_policy=self._search_policy,
            recent_scores=self._recent_scores,
            champion_policy_id=self._champion_policy_id,
            coder_system_prompt=getattr(self._coder, "_system_prompt", ""),  # noqa: SLF001
        )
        if triggered:
            self._slow_loop_triggered = True
        if new_policy is not None:
            self._search_policy = new_policy
            self._champion_policy_id = new_id  # type: ignore[assignment]
            self._apply_search_policy_runtime()

    # ------------------------------------------------------------------ #
    #  辅助方法
    # Setup + Checkpoint — T1 委托
    # ------------------------------------------------------------------ #

    def _ensure_champion_policy(self) -> None:
        """确保实验存在初始 Champion Policy（T1: 委托给 EngineSetup）."""
        self._champion_policy_id, self._search_policy = self._setup.ensure_champion_policy(
            self._experiment_id, self._search_policy
        )
        self._apply_search_policy_runtime()

    def _apply_search_policy_runtime(self) -> None:
        """Bind every live genome field to its runtime consumer."""
        if not self._selection_injected:
            selector = self._search_policy.parent_selector
            if selector == "progressive_mcgs":
                selector = "lineage_ucb"
            self._selection_mode = selector
            self._parent_selector._strategy = (  # noqa: SLF001
                "tournament" if selector == "lineage_ucb" else selector
            )

        if (
            not self._router_injected
            and self._model_slots
            and (
                self._router is None
                or self._router.get_stats().get("algorithm")
                != self._search_policy.model_routing_policy
            )
        ):
            self._router = ModelRouter(
                self._model_slots,
                algorithm=self._search_policy.model_routing_policy,
            )

    def _ensure_version_rows(self) -> None:
        """确保 version 行存在 + L2 验证（T1: 委托给 EngineSetup）."""
        _, code_profile_id = self._setup.ensure_version_rows(
            self._evaluator_version_id, self._environment_version_id, self._task_evaluator
        )
        self._code_profile_id = code_profile_id

    def _ensure_embedding_profile(self, purpose: str) -> str:
        """T1: 委托给 EngineSetup."""
        return self._setup.ensure_embedding_profile(self._db, purpose)

    def _save_checkpoint(self) -> None:
        """持久化检查点（T1: 委托给 CheckpointManager）."""
        job_rows = self._db.fetchall(
            "SELECT id, status, attempt, max_attempts FROM job "
            "WHERE experiment_id = ? AND status IN ('queued', 'running', 'failed')",
            (self._experiment_id,),
        )
        runtime_state: dict[str, Any] = {
            "python_random_state": random.getstate(),
            "lineage_ucb": self._mcts.snapshot_state(),
            "islands": self._island_manager.snapshot_state(),
            "router": self._router.snapshot_state() if self._router is not None else None,
            "budget": self._budget_guard.snapshot_state(),
            "search_policy": self._search_policy.to_dict(),
            "champion_policy_id": self._champion_policy_id,
            "best_candidate": list(self._best_candidate) if self._best_candidate else None,
            "novelty_gate": self._novelty_gate.snapshot_state(),
            "slow_loop_triggered": self._slow_loop_triggered,
            "selection_mode": self._selection_mode,
            "jobs": [dict(row) for row in job_rows],
        }
        if hasattr(self._llm, "_call_count"):
            runtime_state["llm_call_count"] = int(self._llm._call_count)  # noqa: SLF001
        self._checkpoint.save(
            experiment_id=self._experiment_id,
            generation=self._current_generation,
            total_candidates=self._total_candidates,
            meta_scratchpad=self._meta_scratchpad,
            failed_directions=self._failed_directions,
            recent_scores=self._recent_scores,
            runtime_state=runtime_state,
        )

    def _load_checkpoint(self) -> None:
        """恢复检查点（T1: 委托给 CheckpointManager）."""
        checkpoint = self._checkpoint.load(self._experiment_id)
        if checkpoint:
            self._checkpoint_loaded = True
            self._current_generation = int(checkpoint.get("generation", 0))
            self._meta_scratchpad = checkpoint.get("meta_scratchpad", "")
            self._failed_directions = checkpoint.get("failed_directions", [])
            self._recent_scores = checkpoint.get("recent_scores", [])
            self._total_candidates = checkpoint.get("total_candidates", self._total_candidates)
            runtime = checkpoint.get("runtime_state", {})
            policy_payload = runtime.get("search_policy")
            if policy_payload:
                self._search_policy = SearchPolicyGenome.from_dict(policy_payload)
            self._champion_policy_id = runtime.get(
                "champion_policy_id",
                self._champion_policy_id,
            )
            self._apply_search_policy_runtime()
            self._mcts.restore_state(runtime.get("lineage_ucb"))
            self._island_manager.restore_state(runtime.get("islands"))
            if self._router is not None and runtime.get("router"):
                self._router.restore_state(runtime["router"])
            self._budget_guard.restore_state(runtime.get("budget"))
            self._novelty_gate.restore_state(runtime.get("novelty_gate"))
            best = runtime.get("best_candidate")
            if best:
                self._best_candidate = (str(best[0]), float(best[1]))
            self._slow_loop_triggered = bool(
                runtime.get("slow_loop_triggered", self._slow_loop_triggered)
            )
            if "python_random_state" in runtime:
                random.setstate(_nested_tuple(runtime["python_random_state"]))
            if "llm_call_count" in runtime and hasattr(self._llm, "_call_count"):
                self._llm._call_count = int(runtime["llm_call_count"])  # noqa: SLF001

    def _batch_load_artifacts(self, artifact_hashes: list[str]) -> list[str]:
        """批量加载 artifact 内容."""
        results: list[str] = []
        for h in artifact_hashes:
            try:
                results.append(self._artifact_store.load_text(h))
            except Exception:
                results.append("")
        return results

    def _enqueue_vector_index(
        self,
        entity_type: str,
        entity_id: str,
        content_hash: str,
    ) -> None:
        """向 Outbox 写入向量索引任务（S6-08）.

        在 candidate/thought 创建后调用，确保最终一致地向向量后端写入 embedding。
        若无 vector_indexer 或 profile，静默跳过（core 模式不需要向量）。
        """
        if not self._code_profile_id:
            return
        try:
            self._db.execute(
                "INSERT OR IGNORE INTO vector_index_job"
                "(entity_type, entity_id, embedding_profile_id, content_hash,"
                " operation, status) "
                "VALUES (?, ?, ?, ?, 'upsert', 'pending')",
                (entity_type, entity_id, self._code_profile_id, content_hash),
            )
        except Exception:
            logger.warning("vector_index_job insert failed (P0 outbox)", exc_info=True)

    def _load_champion_prompt(self, role: str) -> str:
        """加载角色的 Champion Prompt（S5-04 Prompt 版本化）.

        优先级：genome 的 prompt_version 字段 → PromptVersionRepository champion → "".
        """
        version_field = f"{role}_prompt_version"
        prompt_version_id = getattr(self._search_policy, version_field, "default")
        if prompt_version_id == "default":
            try:
                champion = self._prompt_repo.get_latest(role, "champion")
                if champion:
                    return champion.id
            except Exception:
                logger.debug("Failed to load champion prompt for role %s", role, exc_info=True)
            return ""
        return prompt_version_id

    def _select_model(
        self,
        generation: int,
        role: str = "coder",
        *,
        stagnation_level: float = 0.0,
        novelty_deficit: float = 0.0,
        implementation_difficulty: float = 0.5,
    ) -> str:
        """Select a model for one role; rewards are updated per actual call."""
        if self._router is None:
            return ""
        remaining_compute_ratio = 1.0
        state = self._budget_guard.state
        if state.compute_budget_sec:
            remaining_compute_ratio = max(
                0.0,
                1.0 - state.used_compute_sec / state.compute_budget_sec,
            )
        ctx = RouteContext(
            role=role,
            generation=generation,
            stagnation_level=stagnation_level,
            novelty_deficit=novelty_deficit,
            implementation_difficulty=implementation_difficulty,
            remaining_token_ratio=1.0 - state.token_ratio,
            remaining_compute_ratio=remaining_compute_ratio,
        )
        try:
            return self._router.select(ctx)
        except Exception:
            return ""

    def _get_candidate_score(self, candidate_id: str) -> float:
        """获取候选的评估分数（用于 ShinkaEvolve reward 计算）."""
        row = self._db.fetchone(
            """
            SELECT MAX(primary_score) as score
            FROM evaluation_run
            WHERE candidate_id = ? AND status = 'completed'
            """,
            (candidate_id,),
        )
        return float(row["score"]) if row and row["score"] else 0.0

    def _get_baseline_score(self) -> float:
        """获取实验基线分数（初始候选的分数）."""
        exp = self._experiment_repo.get(self._experiment_id)
        if exp and exp.baseline_candidate_id:
            return self._get_candidate_score(exp.baseline_candidate_id)
        return 0.0

    def _load_parents(self, parent_ids: list[str]) -> tuple[list[str], list[str], list[str]]:
        """加载父代代码、思想、评估失败信息（T1: 委托给 InspirationCollector）."""
        return self._inspiration.load_parents(parent_ids)

    def _write_reference_edges(
        self,
        child_id: str,
        inspiration: list[dict],
        *,
        parent_ids: list[str],
    ) -> None:
        """P0: 写入跨分支引用边（T1: 委托给 InspirationCollector）."""
        self._inspiration.write_reference_edges(child_id, inspiration, parent_ids=parent_ids)

    def _collect_inspiration_programs(
        self,
        exclude_parent_ids: list[str],
        *,
        top_k: int = 3,
        random_k: int = 2,
    ) -> list[dict]:
        """ShinkaEvolve/AlphaEvolve inspiration programs（T1: 委托给 InspirationCollector）."""
        return self._inspiration.collect_inspiration(
            self._experiment_id,
            self._evaluator_version_id,
            self._environment_version_id,
            exclude_parent_ids,
            top_k=top_k,
            random_k=random_k,
        )

    def _update_meta_scratchpad(self, thought: str, score: float) -> None:
        """ShinkaEvolve meta-scratchpad: 跨代累积全局洞察.

        当某方向连续失败时记录到 scratchpad，供后续 Director 参考。
        保持 scratchpad 有界（最近 N 条洞察）。
        """
        if score < 0.1 and thought:
            # 提取思想关键词（简化）
            keyword = thought[:80]
            if keyword not in self._failed_directions:
                self._failed_directions.append(keyword)
                # 只保留最近 5 条失败方向
                self._failed_directions = self._failed_directions[-5:]

        # 重建 scratchpad
        if self._failed_directions:
            self._meta_scratchpad = "Previously failed directions to avoid:\n" + "\n".join(
                f"- {d}" for d in self._failed_directions
            )

    def _lookup_island(self, candidate_id: str) -> str | None:
        """查询候选所属岛屿."""
        cand = self._candidate_repo.get_candidate(candidate_id)
        return cand.island_id if cand else None

    def _rebuild_mcts(self, experiment_id: str) -> None:
        """从血缘图重建 MCTS 节点（保留父子关系）."""
        rows = self._db.fetchall(
            "SELECT id FROM candidate WHERE experiment_id = ? "
            "AND generation <= ? AND status != 'aborted' ORDER BY generation",
            (experiment_id, self._current_generation),
        )
        for row in rows:
            child_id = row["id"]
            parent_rows = self._db.fetchall(
                "SELECT parent_id FROM candidate_lineage WHERE child_id = ? ORDER BY parent_order LIMIT 1",
                (child_id,),
            )
            parent_id = parent_rows[0]["parent_id"] if parent_rows else None
            self._mcts.add_node(child_id, parent=parent_id, prior=0.5)

    # P1: 检查点持久化 — 每代结束时保存易失状态

    def _update_best(self, candidate_id: str, score: float) -> None:
        if self._best_candidate is None or score > self._best_candidate[1]:
            self._best_candidate = (candidate_id, score)
            logger.info("New best: %s score=%.4f", candidate_id, score)

    def _finalize(self, task_name: str) -> EvolutionResult:
        """P1: 持久化最终检查点状态."""
        # 确保最终检查点已写入
        self._save_checkpoint()
        return self._finalize_inner(task_name)

    def _finalize_inner(self, task_name: str) -> EvolutionResult:
        """收尾：更新实验状态，构造 EvolutionResult."""
        elapsed = time.time() - self._start_time if self._start_time else 0.0
        stats = self._budget_guard.counter.get_stats()

        self._experiment_repo.update_costs(
            self._experiment_id,
            tokens=stats["total_tokens"],
            cost_usd=stats["total_cost_usd"],
            compute_sec=elapsed,
        )
        self._experiment_repo.update_status(self._experiment_id, "completed", finished=True)

        final_health = None
        if self._self_evaluator is not None:
            try:
                final_health = self._self_evaluator.assess(
                    self._experiment_id,
                    max(0, self._current_generation - self._config.health_window_gens),
                    self._current_generation,
                )
            except Exception:
                logger.warning("Slow loop trigger failed", exc_info=True)

        best_artifact_hash: str | None = None
        if self._best_candidate:
            best_cand = self._candidate_repo.get_candidate(self._best_candidate[0])
            if best_cand:
                best_artifact_hash = best_cand.artifact_hash

        return EvolutionResult(
            best_candidate_id=self._best_candidate[0] if self._best_candidate else None,
            best_artifact_hash=best_artifact_hash,
            best_score=self._best_candidate[1] if self._best_candidate else None,
            champion_policy_id=self._champion_policy_id,
            total_generations=self._current_generation,
            total_candidates=self._total_candidates,
            total_tokens=stats["total_tokens"],
            total_cost_usd=stats["total_cost_usd"],
            total_compute_sec=elapsed,
            final_health=final_health,
        )
