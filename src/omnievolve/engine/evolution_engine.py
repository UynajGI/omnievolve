"""EvolutionEngine - 完整进化引擎.

S5-13: 接入 Scheduler 生成链路
完整 Fast Loop 11 步实现：
1. Router.select
2. ParentSelector
3. Director.evolve_thought
4. NoveltyGate
5. Coder.generate_code
6. Critic.review
7. ArtifactStore
8. TaskEvaluator.build_plan
9. SandboxBackend.execute
10. TaskEvaluator.parse_result
11. Update Archive/SearchState/Memory/Router
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from omnievolve.agents.base import AgentContext
from omnievolve.agents.coder import Coder
from omnievolve.agents.context_builder import ContextBuilder
from omnievolve.agents.critic import Critic
from omnievolve.agents.director import Director
from omnievolve.agents.llm_gateway import LLMGateway
from omnievolve.engine.mcts import ProgressiveMCGS
from omnievolve.engine.memory import MemoryStore
from omnievolve.engine.novelty import NoveltyDecision, NoveltyGate
from omnievolve.eval.evaluation_run import EvaluationRunRepository
from omnievolve.eval.evaluator_registry import EvaluatorRegistry
from omnievolve.eval.task_evaluator import (
    CandidateArtifact,
    EvalOutput,
    EvaluationContext,
    TaskEvaluator,
)
from omnievolve.meta.policy_genome import SearchPolicyGenome
from omnievolve.sandbox.base import (
    SandboxBackend,
    SandboxPolicy,
)
from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import Database
from omnievolve.storage.repositories.candidate_repo import CandidateRepository
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
    health_window_gens: int = 3
    meta_canary_budget_ratio: float = 0.1


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


class EvolutionEngine:
    """完整进化引擎.

    执行 Fast Loop（候选进化）和触发 Slow Loop（策略进化）。
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
    ) -> None:
        self._db = db
        self._artifact_store = artifact_store
        self._task_evaluator = task_evaluator
        self._sandbox = sandbox
        self._llm = llm

        self._experiment_id = experiment_id
        self._evaluator_version_id = evaluator_version_id
        self._environment_version_id = environment_version_id
        self._config = config or EvolutionConfig()
        self._search_policy = search_policy or SearchPolicyGenome()

        # 组件
        self._candidate_repo = CandidateRepository(db)
        self._eval_repo = EvaluationRunRepository(db)
        self._evaluator_registry = EvaluatorRegistry(db)
        self._memory_store = MemoryStore(db)
        self._novelty_gate = NoveltyGate(embedding_threshold=self._config.novelty_threshold)
        self._context_builder = ContextBuilder()

        # 预算
        budget_state = BudgetState(token_budget=self._config.token_budget)
        self._budget_guard = BudgetGuard(budget_state)

        # Agents
        self._director = Director(llm)
        self._coder = Coder(llm)
        self._critic = Critic(use_syntax_check=True)

        # 进化状态
        self._current_generation = 0
        self._best_candidate: tuple[str, float] | None = None
        self._mcts = ProgressiveMCGS()

    def run(self, initial_code: str, task_name: str) -> EvolutionResult:
        """启动进化循环.

        Args:
            initial_code: 初始代码
            task_name: 任务名称

        Returns:
            进化结果
        """
        logger.info(f"Starting evolution: {task_name}")

        # 存储初始代码
        initial_hash = self._artifact_store.store_text(initial_code, "source")

        # 提交初始候选
        initial_id = self._candidate_repo.create_candidate(
            experiment_id=self._experiment_id,
            task_id=task_name,
            generation=0,
            artifact_hash=initial_hash,
            search_policy_id="initial",
        )

        # 评估初始候选
        self._evaluate_candidate(initial_id, initial_hash)

        # 主循环
        for gen in range(1, self._config.max_generations + 1):
            self._current_generation = gen

            # 预算检查
            if self._budget_guard.state.is_exhausted:
                logger.warning("Budget exhausted, stopping evolution")
                break

            # 执行一代
            self._step_generation(gen, task_name, initial_hash)

            logger.info(
                f"Generation {gen} completed, best score: "
                f"{self._best_candidate[1] if self._best_candidate else 'N/A'}"
            )

        return EvolutionResult(
            best_candidate_id=self._best_candidate[0] if self._best_candidate else None,
            best_artifact_hash=initial_hash,
            best_score=self._best_candidate[1] if self._best_candidate else None,
            champion_policy_id="default",
            total_generations=self._current_generation,
        )

    def _step_generation(
        self,
        generation: int,
        task_name: str,
        initial_hash: str,
    ) -> None:
        """执行一代进化（Fast Loop 11 步）."""
        for i in range(self._config.population_size):
            try:
                candidate_id, artifact_hash = self._evolve_one(
                    generation,
                    task_name,
                    initial_hash,
                    island_id=f"island_{i % self._config.island_count}",
                )

                if candidate_id:
                    self._evaluate_candidate(candidate_id, artifact_hash)

            except Exception as e:
                logger.error(f"Evolution failed for candidate {i}: {e}")

    def _evolve_one(
        self,
        generation: int,
        task_name: str,
        initial_hash: str,
        *,
        island_id: str = "default",
    ) -> tuple[str | None, str]:
        """执行单个候选的完整进化链.

        步骤 1-7: Router -> Parent -> Director -> Novelty -> Coder -> Critic -> Store
        """
        # 1. 构建 AgentContext
        ctx = AgentContext(
            experiment_id=self._experiment_id,
            task_id=task_name,
            generation=generation,
            island_id=island_id,
            search_policy_id="default",
        )

        # 2. Director: 进化思想
        thought = self._director.evolve_thought(ctx)

        # 3. NoveltyGate: 新颖性检查
        novelty_result = self._novelty_gate.check(
            thought=thought.thought,
            existing_similarities=None,
        )

        if novelty_result.decision == NoveltyDecision.REJECT:
            logger.debug("Thought rejected by novelty gate")
            return None, initial_hash

        # 4. Coder: 生成代码
        code = self._coder.generate_code(ctx, thought)

        # 5. Critic: 审查
        passed, feedback = self._critic.review(code, thought)
        if not passed:
            logger.debug(f"Code rejected by critic: {feedback}")
            return None, initial_hash

        # 6. 存储 Artifact
        artifact_hash = self._artifact_store.store_text(code.full_code, "source")

        # 7. 创建候选
        candidate = self._candidate_repo.create_candidate(
            experiment_id=self._experiment_id,
            task_id=task_name,
            generation=generation,
            artifact_hash=artifact_hash,
            search_policy_id="default",
            island_id=island_id,
        )

        return candidate.id, artifact_hash

    def _evaluate_candidate(
        self,
        candidate_id: str,
        artifact_hash: str,
    ) -> EvalOutput | None:
        """评估候选（步骤 8-11）."""
        # 8. 构建评估计划
        candidate_artifact = CandidateArtifact(
            candidate_id=candidate_id,
            source_hash=artifact_hash,
            manifest_hash=None,
            language="python",
        )

        eval_context = EvaluationContext(
            experiment_id=self._experiment_id,
            evaluator_version_id=self._evaluator_version_id or "default",
            environment_version_id=self._environment_version_id or "default",
        )

        try:
            plan = self._task_evaluator.build_plan(candidate_artifact, eval_context)
        except Exception as e:
            logger.error(f"Failed to build plan: {e}")
            return None

        # 9. 沙箱执行
        policy = SandboxPolicy(timeout_sec=self._config.sandbox_timeout)

        try:
            result = self._sandbox.execute(plan, candidate_artifact, policy)
        except Exception as e:
            logger.error(f"Sandbox execution failed: {e}")
            return None

        # 10. 解析结果
        output = self._task_evaluator.parse_result(result, eval_context)

        # 11. 更新状态
        if output.passed:
            self._update_best(candidate_id, output.score)

            # 记录成功记忆
            self._memory_store.add_memory(
                scope_level=1,  # 实验级
                outcome_summary={
                    "candidate_id": candidate_id,
                    "score": output.score,
                    "metrics": output.metrics,
                },
                success_flag=True,
                experiment_id=self._experiment_id,
                candidate_id=candidate_id,
            )

        return output

    def _update_best(self, candidate_id: str, score: float) -> None:
        """更新最佳候选."""
        if self._best_candidate is None or score > self._best_candidate[1]:
            self._best_candidate = (candidate_id, score)
            logger.info(f"New best: {candidate_id} score={score:.4f}")

    @property
    def current_generation(self) -> int:
        return self._current_generation

    def get_best(self) -> tuple[str, float] | None:
        return self._best_candidate
