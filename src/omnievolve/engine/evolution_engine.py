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
import signal
import time
from dataclasses import dataclass, field

from omnievolve.agents.base import AgentContext
from omnievolve.agents.coder import Coder
from omnievolve.agents.context_builder import ContextBuilder
from omnievolve.agents.critic import Critic
from omnievolve.agents.director import Director
from omnievolve.agents.llm_gateway import LLMGateway
from omnievolve.agents.router import ModelRouter, ModelSlot, RouteContext
from omnievolve.engine.crossover import CrossoverOperator
from omnievolve.engine.island import IslandManager
from omnievolve.engine.mcts import ProgressiveMCGS
from omnievolve.engine.memory import MemoryStore
from omnievolve.engine.novelty import NoveltyDecision, NoveltyGate
from omnievolve.engine.selection import ParentSelector
from omnievolve.eval.evaluation_run import EvaluationRunRepository
from omnievolve.eval.evaluator_registry import EvaluatorRegistry
from omnievolve.eval.task_evaluator import (
    CandidateArtifact,
    EvalOutput,
    EvaluationContext,
    TaskEvaluator,
)
from omnievolve.eval.telemetry import HealthOutput, SelfEvaluator
from omnievolve.exceptions import (
    EvaluatorError,
    EvolutionError,
    LLMError,
    SandboxError,
    StorageError,
)
from omnievolve.meta.governance import (
    GovernancePolicy,
    L0PolicyMutator,
    MetaAction,
    MetaPlanner,
    ReplayEvaluator,
)
from omnievolve.meta.policy_archive import PolicyArchive
from omnievolve.meta.policy_genome import SearchPolicyGenome
from omnievolve.sandbox.base import (
    SandboxBackend,
    SandboxPolicy,
)
from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import Database
from omnievolve.storage.graph_store import GraphStore
from omnievolve.storage.repositories.candidate_repo import CandidateRepository
from omnievolve.storage.repositories.experiment_repo import ExperimentRepository
from omnievolve.storage.repositories.prompt_repo import PromptVersionRepository
from omnievolve.storage.vector_indexer import VectorIndexer
from omnievolve.utils.token_counter import BudgetGuard, BudgetState

logger = logging.getLogger(__name__)


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
    tournament_size: int = 3
    island_migration_interval: int = 5
    ucb_c: float = 1.414
    self_evolve_enabled: bool = True


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
        artifact_store: ArtifactStore,
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
        graph_store: GraphStore | None = None,
        vector_indexer: VectorIndexer | None = None,
        prompt_repo: PromptVersionRepository | None = None,
    ) -> None:
        self._db = db
        self._artifact_store = artifact_store
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
        self._search_policy = search_policy or SearchPolicyGenome()

        # Repository / Store
        self._candidate_repo = CandidateRepository(db)
        self._eval_repo = EvaluationRunRepository(db)
        self._evaluator_registry = EvaluatorRegistry(db)
        self._experiment_repo = ExperimentRepository(db)
        self._memory_store = MemoryStore(db)
        self._graph_store = graph_store or GraphStore(db)
        self._novelty_gate = NoveltyGate(embedding_threshold=self._config.novelty_threshold)

        # 预算
        budget_state = BudgetState(
            token_budget=self._config.token_budget,
            compute_budget_sec=self._config.compute_budget_sec,
        )
        self._budget_guard = BudgetGuard(budget_state)

        # Agents
        self._director = Director(llm)
        self._coder = Coder(llm)
        self._critic = Critic(use_syntax_check=True)

        # S5-05: ContextBuilder 按 token 预算裁剪上下文
        self._context_builder = ContextBuilder(
            total_token_budget=min(self._config.token_budget, 100_000),
        )

        # 搜索组件
        self._mcts = ProgressiveMCGS(
            exploration=self._config.ucb_c,
            schedule="progressive",
            c_min=0.2,
        )
        self._island_manager = island_manager or IslandManager(
            num_islands=self._config.island_count,
            migration_interval=self._config.island_migration_interval,
        )
        self._parent_selector = parent_selector or ParentSelector(
            db,
            strategy="tournament",
            tournament_size=self._config.tournament_size,
        )
        self._crossover = crossover or CrossoverOperator()

        # 模型路由
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

        # 插件自动发现 — EvoX evox_ext 模式: 启动时扫描并加载所有已安装插件
        from omnievolve.plugins.discovery import discover_plugins

        discover_plugins()
        logger.info("Engine initialized, plugins loaded")

        # 向量 Outbox + Prompt 版本化（延迟激活：需显式注入或 run 时注册）
        self._vector_indexer = vector_indexer
        self._prompt_repo = prompt_repo or PromptVersionRepository(db)
        self._code_profile_id: str | None = None  # run() 时注册

        # 进化状态
        self._current_generation = 0
        self._best_candidate: tuple[str, float] | None = None
        self._champion_policy_id = "default"
        self._total_candidates = 0
        self._start_time = 0.0
        self._recent_scores: list[float] = []  # 最近窗口分数（供 Slow Loop 比较）
        self._slow_loop_triggered = False
        # ShinkaEvolve: meta-scratchpad 跨代累积全局洞察
        self._meta_scratchpad: str = ""
        # 失败方向追踪（用于 meta-scratchpad 更新）
        self._failed_directions: list[str] = []
        # OpenEvolve: graceful shutdown flag (SIGINT/SIGTERM)
        self._shutdown_requested = False

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

    def run(self, initial_code: str, task_name: str) -> EvolutionResult:
        """启动进化循环（Fast Loop + 按窗口触发 Slow Loop）.

        支持 SIGINT/SIGTERM 优雅关闭（参考 OpenEvolve）。
        """
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

    def _run_evolution(self, initial_code: str, task_name: str) -> EvolutionResult:
        """进化主循环（内部实现）."""
        logger.info("Starting evolution: %s", task_name)

        # 注册初始 Champion Policy
        self._ensure_champion_policy()
        self._ensure_version_rows()

        # 存储并评估初始代码
        initial_hash = self._artifact_store.store_text(initial_code, "source")
        initial_candidate = self._candidate_repo.create_candidate(
            experiment_id=self._experiment_id,
            task_id=task_name,
            generation=0,
            artifact_hash=initial_hash,
            search_policy_id=self._champion_policy_id,
        )
        initial_id = initial_candidate.id
        self._mcts.add_node(initial_id, parent=None, prior=1.0)
        self._total_candidates += 1
        self._evaluate_candidate(initial_id, initial_hash)
        self._island_manager.assign_candidate(initial_id, "island_0")

        # 设置 baseline
        self._experiment_repo.set_baseline(self._experiment_id, initial_id)

        # 主循环
        for gen in range(1, self._config.max_generations + 1):
            if self._shutdown_requested:
                logger.warning("Shutdown requested, stopping evolution at gen %d", gen - 1)
                break
            self._current_generation = gen

            # P1: 更新 MCTS 探索进度（渐进衰减）
            self._mcts.set_progress(gen, self._config.max_generations)

            if self._budget_guard.state.is_exhausted:
                logger.warning("Budget exhausted, stopping evolution")
                break

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

        return self._finalize(task_name)

    def resume(self, experiment_id: str) -> EvolutionResult:
        """恢复实验：重载状态，从中断处继续.

        重新认领租约过期的任务，从最大 generation + 1 继续。
        """
        self._experiment_id = experiment_id
        exp = self._experiment_repo.get(experiment_id)
        if exp is None:
            raise ValueError(f"Experiment not found: {experiment_id}")

        # 找到当前最大 generation
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

        # 恢复 MCTS 图
        self._rebuild_mcts(experiment_id)

        logger.info(
            "Resumed experiment %s at generation %d", experiment_id, self._current_generation
        )

        task_name = exp.task_name
        # 从下一代继续
        for gen in range(self._current_generation + 1, self._config.max_generations + 1):
            self._current_generation = gen
            self._mcts.set_progress(gen, self._config.max_generations)
            if self._budget_guard.state.is_exhausted:
                break
            self._step_generation(gen, task_name)
            if self._island_manager.should_migrate(gen):
                self._island_manager.migrate(gen)
            if self._config.self_evolve_enabled and gen % self._config.health_window_gens == 0:
                self._run_slow_loop(gen)

        return self._finalize(task_name)

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
                self._evolve_one(generation, task_name, island_id)
            except (EvolutionError, LLMError, SandboxError, StorageError):
                logger.exception("Evolution failed for candidate slot %d", i)

    def _select_parents(self, island_id: str) -> tuple[list[str], str]:
        """选择父代（步骤 2）：MCTS 引导 + ParentSelector 兜底.

        Returns:
            (parent_ids, relation_type)  relation_type ∈ {mutate, crossover}
        """
        # 1. 尝试 MCTS 选择：从该岛屿的最佳候选出发下降到叶节点
        island = self._island_manager.get_island(island_id)
        mcts_parent: str | None = None
        if island and island.elite_archive:
            root = island.elite_archive[0][0]
            if root in self._mcts._nodes:  # noqa: SLF001 - 检查节点是否已注册
                mcts_parent = self._mcts.select(root)

        # 2. ParentSelector 兜底（需要有评估分数的候选）
        min_parents = getattr(self._crossover, "min_parents", 2)
        scored = self._parent_selector.select(
            self._experiment_id,
            self._evaluator_version_id,
            self._environment_version_id,
            count=min_parents,
        )

        # 3. 决定 mutate vs crossover
        import random

        use_crossover = len(scored) >= 2 and random.random() < self._config.crossover_rate

        if use_crossover:
            return scored, "crossover"
        if mcts_parent:
            return [mcts_parent], "mutate"
        if scored:
            return scored[:1], "mutate"
        return [], "mutate"

    def _evolve_one(
        self,
        generation: int,
        task_name: str,
        island_id: str,
    ) -> tuple[str | None, str]:
        """执行单个候选的完整进化链（步骤 1-11）.

        包含生成、评估与全部状态更新。
        """
        # 步骤 2: 选择父代
        parent_ids, relation = self._select_parents(island_id)

        # 加载父代代码 / 思想
        parent_codes, parent_thoughts = self._load_parents(parent_ids)

        # 步骤 1: Router 选择模型
        model = self._select_model(generation)

        # 步骤 3/可选 crossover: 多父代融合产生基础代码
        base_code: str | None = None
        if relation == "crossover" and len(parent_codes) >= 2:
            base_code = self._crossover.combine(parent_codes, strategy="segment")

        # 检索记忆（步骤 1 上下文构建）
        memory_hits = self._memory_store.retrieve(
            experiment_id=self._experiment_id,
            task_id=task_name,
            success_only=True,
            limit=self._search_policy.retrieval_budget,
        )
        memory_summaries = [
            {
                "outcome_summary": str(m.outcome_summary)[:200],
                "scope_level": m.scope_level,
                "success": m.success_flag,
            }
            for m in memory_hits
        ]

        # 构建 AgentContext（S5-04: 注入 champion prompt 版本）
        # ShinkaEvolve/AlphaEvolve: inspiration programs（多样化的高分候选 + 随机样本）
        inspiration = self._collect_inspiration_programs(parent_ids)

        # AM-01: 注入父代码到 inspiration 中，Coder 使用它作为 diff 基础
        for i, pid in enumerate(parent_ids):
            if i < len(parent_codes):
                inspiration.insert(
                    0,
                    {
                        "is_parent": True,
                        "candidate_id": pid,
                        "score": 0.0,
                        "code": parent_codes[i],
                        "source": "parent",
                    },
                )

        ctx = AgentContext(
            experiment_id=self._experiment_id,
            task_id=task_name,
            generation=generation,
            island_id=island_id,
            parent_candidate_ids=parent_ids,
            parent_thoughts=parent_thoughts,
            parent_artifact_hashes=[],
            inspiration_programs=inspiration,
            memory_hits=memory_summaries,
            meta_scratchpad=self._meta_scratchpad,
            search_policy_id=self._champion_policy_id,
            evaluator_version_id=self._evaluator_version_id,
            environment_version_id=self._environment_version_id,
            model=model,
            prompt_version_id=self._load_champion_prompt("director"),
        )

        # 步骤 4: Director 进化思想
        thought = self._director.evolve_thought(ctx)

        # 步骤 5: NoveltyGate 多级新颖性检查
        novelty_result = self._novelty_gate.check(
            thought=thought.thought,
            code=base_code,
        )
        if novelty_result.decision == NoveltyDecision.REJECT:
            logger.debug("Thought rejected by novelty gate")
            return None, ""

        # 步骤 6: Coder 生成代码（带 critic 重试）
        code = self._coder.generate_code(ctx, thought)
        if not code.full_code.strip():
            # diff 可能已解析但无法 apply → 回退到父代码或 crossover 基线
            if base_code:
                code = type(code)(diff="", full_code=base_code, explanation="crossover baseline")
            elif parent_codes:
                code = type(code)(
                    diff="",
                    full_code=parent_codes[0],
                    explanation="fallback to parent code (diff could not be applied)",
                )

        passed, _ = self._critic.review(code, thought)
        retries = 0
        while not passed and retries < self._config.novelty_retry_limit:
            retries += 1
            code = self._coder.generate_code(ctx, thought)
            passed, _ = self._critic.review(code, thought)

        if not passed:
            logger.debug("Code rejected by critic after retries")
            return None, ""

        # 步骤 7: 存储 Artifact
        artifact_hash = self._artifact_store.store_text(code.full_code, "source")

        # 步骤 8: 创建候选（含多父代血缘）
        parents_with_relation = [(pid, relation) for pid in parent_ids]
        candidate = self._candidate_repo.create_candidate(
            experiment_id=self._experiment_id,
            task_id=task_name,
            generation=generation,
            artifact_hash=artifact_hash,
            search_policy_id=self._champion_policy_id,
            island_id=island_id,
            parents=parents_with_relation or None,
            meta={"thought": thought.thought[:500], "relation": relation, "model": model},
        )
        self._total_candidates += 1

        # S6-08: 向量 Outbox — 为候选代码入队索引任务
        self._enqueue_vector_index("candidate", candidate.id, artifact_hash)

        # 记录思想
        thought_record = self._candidate_repo.create_thought(
            experiment_id=self._experiment_id,
            task_id=task_name,
            content=thought.thought,
            rationale=thought.rationale,
            risk_notes=thought.risk_notes,
            confidence=thought.confidence,
            mechanism_tags=thought.mechanism_tags,
        )

        # S6-08: 为思想内容入队向量索引（novelty 语义检索依赖）
        thought_hash = self._artifact_store.store_text(thought.thought, "log")
        self._enqueue_vector_index("thought", thought_record.id, thought_hash)

        # P0: Reference edges — 跨分支信息流
        self._write_reference_edges(
            candidate.id,
            inspiration,
            parent_ids=parent_ids,
        )

        # MCTS 扩展（步骤 8 续）
        if parent_ids:
            self._mcts.expand(parent_ids[0], [(candidate.id, thought.confidence)])
        else:
            self._mcts.add_node(candidate.id, parent=None, prior=thought.confidence)

        # 步骤 9-11: 评估并更新状态
        output = self._evaluate_candidate(candidate.id, artifact_hash)
        self._island_manager.assign_candidate(candidate.id, island_id)

        # Router 奖励更新（ShinkaEvolve 相对奖励公式）
        if self._router is not None and model and output is not None:
            from omnievolve.agents.router import compute_shinka_reward

            # parent_score: 取所有父代的最高分
            parent_score = 0.0
            if parent_ids:
                parent_scores = [self._get_candidate_score(pid) for pid in parent_ids]
                parent_score = max(parent_scores) if parent_scores else 0.0

            # baseline_score: 初始候选分数
            baseline_score = self._get_baseline_score()

            reward = compute_shinka_reward(output.score, parent_score, baseline_score)
            self._router.update(model=model, role="coder", reward=reward)

        return candidate.id, artifact_hash

    def _evaluate_candidate(
        self,
        candidate_id: str,
        artifact_hash: str,
    ) -> EvalOutput | None:
        """评估候选（步骤 9-11）+ 记录 evaluation_run."""
        candidate_artifact = CandidateArtifact(
            candidate_id=candidate_id,
            source_hash=artifact_hash,
            manifest_hash=None,
            language="python",
        )
        eval_context = EvaluationContext(
            experiment_id=self._experiment_id,
            evaluator_version_id=self._evaluator_version_id,
            environment_version_id=self._environment_version_id,
        )

        # 创建评估运行记录
        try:
            run = self._eval_repo.create(
                experiment_id=self._experiment_id,
                candidate_id=candidate_id,
                evaluator_version_id=self._evaluator_version_id,
                environment_version_id=self._environment_version_id,
            )
            self._eval_repo.start(run.id)
        except StorageError:
            logger.debug("Could not create evaluation_run record", exc_info=True)
            run = None

        # 步骤 9: build_plan
        try:
            plan = self._task_evaluator.build_plan(candidate_artifact, eval_context)
        except EvaluatorError:
            logger.exception("Failed to build plan for %s", candidate_id)
            if run:
                self._eval_repo.fail(run.id, "build_plan error")
            return None

        # 步骤 10: sandbox 执行
        policy = SandboxPolicy(
            timeout_sec=self._config.sandbox_timeout,
            mem_limit_mb=self._config.sandbox_mem_limit_mb,
        )
        try:
            result = self._sandbox.execute(plan, candidate_artifact, policy)
        except SandboxError:
            logger.exception("Sandbox execution failed for %s", candidate_id)
            if run:
                self._eval_repo.fail(run.id, "sandbox execution error")
            return None

        # 步骤 11: parse + 更新状态
        output = self._task_evaluator.parse_result(result, eval_context)

        # 完成评估运行记录
        if run:
            try:
                self._eval_repo.complete(
                    run.id,
                    passed=output.passed,
                    primary_score=output.score,
                    metrics=output.metrics,
                    execution_time_ms=result.execution_time_ms,
                    memory_peak_kb=result.memory_peak_kb,
                    cpu_time_ms=result.cpu_time_ms,
                )
            except StorageError:
                logger.debug("Could not complete evaluation_run record", exc_info=True)

        # 更新 candidate 状态
        self._candidate_repo.update_status(candidate_id, "evaluated" if output.passed else "failed")

        # 更新 best
        if output.passed:
            self._update_best(candidate_id, output.score)

        # 记录分数供 Slow Loop
        self._recent_scores.append(output.score)

        # ShinkaEvolve meta-scratchpad: 更新失败方向追踪
        thought_text = ""
        cand_meta = self._candidate_repo.get_candidate(candidate_id)
        if cand_meta and cand_meta.meta:
            thought_text = cand_meta.meta.get("thought", "")
        self._update_meta_scratchpad(thought_text, output.score)

        # MCTS 回传
        self._mcts.backpropagate(candidate_id, output.score)

        # 岛屿精英更新
        island_id = self._lookup_island(candidate_id)
        if island_id:
            island = self._island_manager.get_island(island_id)
            if island:
                island.update_elite(candidate_id, output.score)
                if output.passed:
                    self._island_manager.reset_stagnation(island_id)
                else:
                    self._island_manager.increment_stagnation(island_id)

        # 搜索状态更新
        self._candidate_repo.update_search_state(
            candidate_id,
            visit_delta=1,
            value_delta=output.score,
            frontier_status="elite" if output.passed else "closed",
        )

        # 成功记忆
        if output.passed:
            self._memory_store.add_memory(
                scope_level=1,
                outcome_summary={
                    "candidate_id": candidate_id,
                    "score": output.score,
                    "metrics": output.metrics,
                },
                success_flag=True,
                experiment_id=self._experiment_id,
                candidate_id=candidate_id,
            )

        # 预算记账（沙箱执行耗时）
        self._budget_guard.consume(
            model="sandbox",
            input_tokens=0,
            output_tokens=0,
            compute_sec=result.execution_time_ms / 1000,
        )

        return output

    # ------------------------------------------------------------------ #
    #  Slow Loop
    # ------------------------------------------------------------------ #

    def _run_slow_loop(self, current_gen: int) -> None:
        """执行 Slow Loop：聚合 → 评估健康 → 提议动作 → 治理 → 策略实验."""
        if self._self_evaluator is None:
            return  # 未注入自评估器时跳过（保持核心 Fast Loop 可用）

        window_start = max(0, current_gen - self._config.health_window_gens)
        try:
            health = self._self_evaluator.assess(self._experiment_id, window_start, current_gen)
        except Exception:
            logger.exception("Slow Loop telemetry failed at gen %d", current_gen)
            return

        logger.info(
            "Slow Loop gen %d: alert=%s roi=%.4f trigger=%s",
            current_gen,
            health.alert_level.value,
            health.roi_score,
            health.should_trigger_meta,
        )

        if not health.should_trigger_meta:
            return

        self._slow_loop_triggered = True

        if self._meta_planner is None:
            return

        # 提议受控动作
        actions = self._meta_planner.propose(
            {
                "coverage_entropy": health.coverage_entropy,
                "pollution_ratio": health.pollution_ratio,
                "roi_score": health.roi_score,
            },
            self._search_policy,
            [],
        )

        for action in actions:
            self._apply_meta_action(action, current_gen)

    def _apply_meta_action(self, action: MetaAction, current_gen: int) -> None:
        """应用单个元进化动作（治理分级 + Challenger 实验）."""
        risk = self._governance.classify_action(action)
        can_apply, reason = self._governance.can_apply(action)

        if not can_apply:
            logger.info("Meta action %s rejected: %s", action.target, reason)
            return

        # 创建 Challenger 基因组
        if action.action_type == "modify_field":
            new_genome, mut_reason = self._l0_mutator.mutate(
                self._search_policy, action.target, action.new_value
            )
            if new_genome is None:
                logger.info("Mutation failed: %s", mut_reason)
                return

            challenger = self._policy_archive.create_policy(
                new_genome,
                experiment_id=self._experiment_id,
                parent_policy_id=self._champion_policy_id,
                risk_level=risk.value,
            )
            # 标记为 challenger
            self._db.execute(
                "UPDATE search_policy_version SET status='challenger' WHERE id=?",
                (challenger.id,),
            )

            # Canary 比较：用最近窗口分数作为 champion 基线
            decision = self._replay_evaluator.compare(
                champion_scores=self._recent_scores[-self._config.health_window_gens :],
                challenger_scores=self._recent_scores[-1:],
            )

            if decision.get("decision") == "promote":
                self._policy_archive.promote_to_champion(challenger.id)
                self._search_policy = new_genome
                self._champion_policy_id = challenger.id
                self._experiment_repo.set_champion_policy(self._experiment_id, challenger.id)
                logger.info(
                    "Policy %s promoted at gen %d: %s",
                    challenger.id,
                    current_gen,
                    decision.get("reason"),
                )
                # 反馈给贝叶斯优化器
                self._record_tuner_feedback(action, decision.get("gain", 0.0))
            else:
                self._policy_archive.reject(challenger.id, decision.get("reason", ""))
                # 反馈给贝叶斯优化器
                self._record_tuner_feedback(action, decision.get("gain", -0.01))

        elif action.action_type == "evolve_prompt":
            # AM-04: Prompt 进化 — 变异 system prompt（L1 级别）
            if self._meta_planner is not None and hasattr(self._meta_planner, "_prompt_evolver"):
                evolver = self._meta_planner._prompt_evolver  # noqa: SLF001
                if evolver is not None:
                    # 获取当前 champion prompt 版本（用于 parent_id）
                    champion = self._prompt_repo.get_latest("coder", "champion")
                    parent_id = champion.id if champion else None
                    # 获取实际 prompt 文本
                    current_prompt = getattr(self._coder, "_system_prompt", "")  # noqa: SLF001
                    if current_prompt:
                        new_prompt, mutations = evolver.evolve(current_prompt)
                        if mutations:
                            self._prompt_repo.create(
                                agent_role="coder",
                                content=new_prompt,
                                parent_id=parent_id,
                                artifact_store=self._artifact_store,
                            )
                            logger.info("Prompt evolved with mutations: %s", mutations)
            return  # evolve_prompt 不走 Challenger 实验路径

    def _record_tuner_feedback(self, action: MetaAction, gain: float) -> None:
        """将 meta 动作结果反馈给贝叶斯优化器."""
        if self._meta_planner is None or self._meta_planner._tuner is None:  # noqa: SLF001
            return
        try:
            params = {action.target: action.new_value}
            self._meta_planner._tuner.update(  # noqa: SLF001
                params, score=gain, generation=self._current_generation
            )
        except Exception:
            logger.debug("Failed to record tuner feedback", exc_info=True)

    # ------------------------------------------------------------------ #
    #  辅助方法
    # ------------------------------------------------------------------ #

    def _ensure_champion_policy(self) -> None:
        """确保实验存在一个初始 Champion Policy."""
        champ = self._policy_archive.get_champion(self._experiment_id)
        if champ is None:
            policy = self._policy_archive.create_policy(
                self._search_policy,
                experiment_id=self._experiment_id or None,
                risk_level="L0",
            )
            self._policy_archive.promote_to_champion(policy.id)
            self._champion_policy_id = policy.id
        else:
            self._champion_policy_id = champ.id
            self._search_policy = champ.genome

        # 关联到实验记录
        if self._experiment_id:
            try:
                self._experiment_repo.set_champion_policy(
                    self._experiment_id, self._champion_policy_id
                )
            except Exception:
                logger.debug("Could not set champion_policy_id on experiment")

    def _ensure_version_rows(self) -> None:
        """确保 evaluator/environment version 行存在以满足 FK 约束.

        若 CLI 已通过 EvaluatorRegistry 注册完整版本，INSERT OR IGNORE 不覆盖；
        若未注册（直接使用引擎），写入最小行满足外键。
        """
        if self._evaluator_version_id:
            name = (
                self._evaluator_version_id.split("@")[0]
                if "@" in self._evaluator_version_id
                else self._evaluator_version_id
            )
            self._db.execute(
                "INSERT OR IGNORE INTO task_evaluator_version"
                "(id, name, semantic_version, implementation_hash, "
                " task_semantics_hash, score_schema, immutable_core) "
                "VALUES (?, ?, '1.0.0', ?, ?, '{}', 1)",
                (
                    self._evaluator_version_id,
                    name,
                    self._evaluator_version_id,
                    self._evaluator_version_id,
                ),
            )
        if self._environment_version_id:
            self._db.execute(
                "INSERT OR IGNORE INTO execution_environment_version"
                "(id, backend, resource_policy, network_policy) "
                "VALUES (?, 'engine', '{}', 'none')",
                (self._environment_version_id,),
            )

        # 确保默认 code embedding profile 存在（向量 Outbox 依赖）
        self._code_profile_id = self._ensure_embedding_profile("code")

    def _ensure_embedding_profile(self, purpose: str) -> str:
        """确保 embedding_profile 行存在（S6-01 设计要求）.

        默认使用 fake/占位 profile；真实部署由 CLI/配置注入。
        """
        profile_id = f"profile-{purpose}-default"
        self._db.execute(
            "INSERT OR IGNORE INTO embedding_profile"
            "(id, purpose, provider, model, revision, dimension, normalization,"
            " input_type, chunking_policy, collection_path) "
            "VALUES (?, ?, 'fake', 'fake-embed', 'default', 64, 'l2', 'document',"
            " 'whole', ?)",
            (profile_id, purpose, f"collections/{purpose}"),
        )
        return profile_id

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
            logger.debug("vector_index_job insert failed", exc_info=True)

    def _load_champion_prompt(self, role: str) -> str:
        """加载角色的 Champion Prompt（S5-04 Prompt 版本化）.

        优先级：genome 的 prompt_version 字段 → PromptVersionRepository champion → "".
        """
        version_field = f"{role}_prompt_version"
        prompt_version_id = getattr(self._search_policy, version_field, "default")
        if prompt_version_id == "default":
            # 从 Repository 获取 champion prompt
            try:
                champion = self._prompt_repo.get_latest(role, "champion")
                if champion:
                    return ""  # content_hash 指向 artifact；实际内容由 Agent 自行加载
            except Exception:
                pass
            return ""
        return prompt_version_id

    def _select_model(self, generation: int) -> str:
        """Router 选择模型（步骤 1）."""
        if self._router is None:
            return ""
        ctx = RouteContext(
            role="coder",
            generation=generation,
            stagnation_level=0.0,
            novelty_deficit=0.0,
            implementation_difficulty=0.5,
            remaining_token_ratio=1.0 - self._budget_guard.state.token_ratio,
            remaining_compute_ratio=1.0,
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

    def _load_parents(self, parent_ids: list[str]) -> tuple[list[str], list[str]]:
        """加载父代代码与思想."""
        codes: list[str] = []
        thoughts: list[str] = []
        for pid in parent_ids:
            cand = self._candidate_repo.get_candidate(pid)
            if cand is None:
                continue
            try:
                code = self._artifact_store.load_text(cand.artifact_hash)
                codes.append(code)
            except Exception:
                logger.debug("Cannot load artifact %s", cand.artifact_hash)
            if cand.meta and isinstance(cand.meta.get("thought"), str):
                thoughts.append(cand.meta["thought"])
        return codes, thoughts

    def _write_reference_edges(
        self,
        child_id: str,
        inspiration: list[dict],
        *,
        parent_ids: list[str],
    ) -> None:
        """P0: 写入跨分支引用边.

        非父代来源的 inspiration（其他 island 的高分候选、memory 检索结果）
        作为 reference edge 写入，区分于主血缘边。
        """
        parent_set = set(parent_ids)
        for insp in inspiration:
            src_id = insp.get("candidate_id", "")
            if not src_id or src_id in parent_set or src_id == child_id:
                continue
            source = insp.get("source", "unknown")
            ref_type = {
                "top_k": "cross_branch",
                "random_k": "exploration",
                "memory": "memory",
            }.get(source, "reference")
            try:
                self._db.execute(
                    """
                    INSERT OR IGNORE INTO candidate_reference_edge
                        (src_candidate_id, dst_candidate_id, reference_type, detail)
                    VALUES (?, ?, ?, ?)
                    """,
                    (src_id, child_id, ref_type, f"source={source} score={insp.get('score', '?')}"),
                )
            except Exception:
                logger.debug("Failed to write reference edge", exc_info=True)

    def _collect_inspiration_programs(
        self,
        exclude_parent_ids: list[str],
        *,
        top_k: int = 3,
        random_k: int = 2,
    ) -> list[dict]:
        """ShinkaEvolve/AlphaEvolve inspiration programs.

        收集与直接父代不同的多样化候选：
        - top_k 个高分候选（exploitation）
        - random_k 个随机已评估候选（exploration）
        排除直接父代以提供真正不同的上下文。
        """
        inspirations: list[dict] = []
        exclude = set(exclude_parent_ids)

        # Top-K 高分候选
        try:
            bests = self._candidate_repo.get_best_candidates(
                self._experiment_id,
                self._evaluator_version_id,
                self._environment_version_id,
                limit=top_k * 2,
            )
            for cand, score in bests:
                if cand.id in exclude:
                    continue
                try:
                    code = self._artifact_store.load_text(cand.artifact_hash)
                    inspirations.append(
                        {
                            "candidate_id": cand.id,
                            "score": score,
                            "code_preview": code[:500],
                            "source": "top_k",
                        }
                    )
                except Exception:
                    pass
                if len([i for i in inspirations if i["source"] == "top_k"]) >= top_k:
                    break
        except Exception:
            logger.debug("Failed to collect top-K inspirations", exc_info=True)

        # Random-K 已评估候选
        try:
            rows = (
                self._db.fetchall(
                    """
                SELECT c.id, c.artifact_hash, er.primary_score
                FROM candidate c
                JOIN evaluation_run er ON c.id = er.candidate_id
                WHERE c.experiment_id = ? AND er.status = 'completed'
                  AND c.id NOT IN ({})
                ORDER BY RANDOM() LIMIT ?
                """.format(",".join(["?"] * len(exclude)) if exclude else "''"),
                    (self._experiment_id, *exclude, random_k * 3),
                )
                if exclude
                else self._db.fetchall(
                    """
                SELECT c.id, c.artifact_hash, er.primary_score
                FROM candidate c
                JOIN evaluation_run er ON c.id = er.candidate_id
                WHERE c.experiment_id = ? AND er.status = 'completed'
                ORDER BY RANDOM() LIMIT ?
                """,
                    (self._experiment_id, random_k * 3),
                )
            )
            count = 0
            for row in rows or []:
                try:
                    code = self._artifact_store.load_text(row["artifact_hash"])
                    inspirations.append(
                        {
                            "candidate_id": row["id"],
                            "score": row["primary_score"],
                            "code_preview": code[:300],
                            "source": "random",
                        }
                    )
                    count += 1
                    if count >= random_k:
                        break
                except Exception:
                    pass
        except Exception:
            logger.debug("Failed to collect random inspirations", exc_info=True)

        return inspirations

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
        """从血缘图重建 MCTS 节点."""
        rows = self._db.fetchall(
            "SELECT id FROM candidate WHERE experiment_id = ? ORDER BY generation",
            (experiment_id,),
        )
        for row in rows:
            self._mcts.add_node(row["id"], parent=None, prior=0.5)

    def _update_best(self, candidate_id: str, score: float) -> None:
        if self._best_candidate is None or score > self._best_candidate[1]:
            self._best_candidate = (candidate_id, score)
            logger.info("New best: %s score=%.4f", candidate_id, score)

    def _finalize(self, task_name: str) -> EvolutionResult:
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
                pass

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
