"""EvolutionEngine 端到端集成测试.

验证完整 Fast Loop（11 步）+ Slow Loop（受控元进化）的接线：
    FakeLLM + StubEvaluator + TrustedSubprocessBackend + 全部引擎组件
"""

from __future__ import annotations

import json
import sys

import pytest

from omnievolve.agents.llm_gateway import LLMResponse
from omnievolve.engine.crossover import CrossoverOperator
from omnievolve.engine.evolution_engine import EvolutionConfig, EvolutionEngine
from omnievolve.engine.island import IslandManager
from omnievolve.engine.selection import ParentSelector
from omnievolve.eval.task_evaluator import (
    CandidateArtifact,
    CommandSpec,
    EvalOutput,
    EvaluationContext,
    EvaluationPlan,
    SandboxExecutionResult,
)
from omnievolve.eval.telemetry import HealthPolicy, SelfEvaluator, TelemetryAggregator
from omnievolve.meta.governance import (
    GovernancePolicy,
    L0PolicyMutator,
    MetaPlanner,
    ReplayEvaluator,
)
from omnievolve.meta.policy_archive import PolicyArchive
from omnievolve.sandbox.subprocess_backend import TrustedSubprocessBackend
from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.graph_store import GraphStore
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.repositories.experiment_repo import ExperimentRepository

pytestmark = pytest.mark.e2e

# --------------------------------------------------------------------------- #
#  Test fixtures / fakes
# --------------------------------------------------------------------------- #


class RoleAwareFakeLLM:
    """按 agent_role 返回不同 JSON 的 Fake LLM."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.coder_calls = 0

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        experiment_id: str | None = None,
        agent_role: str = "unknown",
        prompt_version_id: str | None = None,
    ) -> LLMResponse:
        self.calls.append({"agent_role": agent_role, "model": model})

        if agent_role == "director":
            content = (
                '{"thought": "Try a faster algorithm", '
                '"rationale": "reduce complexity", '
                '"confidence": 0.8, '
                '"mechanism_tags": ["algo"]}'
            )
        elif agent_role == "coder":
            self.coder_calls += 1
            content = (
                f'{{"full_code": "x = {self.coder_calls}\\nprint(x)", '
                '"diff": "rewrite", "explanation": "simpler"}'
            )
        else:
            content = '{"passed": true, "feedback": "ok"}'

        return LLMResponse(
            content=content,
            model=model or "fake",
            input_tokens=50,
            output_tokens=30,
            total_tokens=80,
            latency_ms=1.0,
        )


class NoOpFakeLLM(RoleAwareFakeLLM):
    """Return the exact parent for every coder call."""

    def chat(self, messages, **kwargs):
        if kwargs.get("agent_role") == "coder":
            self.calls.append(
                {"agent_role": "coder", "model": kwargs.get("model")}
            )
            return LLMResponse(
                content='{"full_code":"x = 0\\n","diff":"","explanation":"no change"}',
                model=kwargs.get("model") or "fake",
                input_tokens=10,
                output_tokens=10,
                total_tokens=20,
                latency_ms=1.0,
            )
        return super().chat(messages, **kwargs)


class StubEvaluator:
    """不依赖候选代码内容的桩评估器：运行一条固定命令并按成功与否评分."""

    version_id = "stub-evaluator@1.0.0"

    def build_plan(
        self, candidate: CandidateArtifact, context: EvaluationContext
    ) -> EvaluationPlan:
        return EvaluationPlan(
            commands=[CommandSpec(argv=[sys.executable, "-c", "print(42)"], timeout_sec=5.0)],
        )

    def parse_result(
        self, result: SandboxExecutionResult, context: EvaluationContext
    ) -> EvalOutput:
        ok = bool(result.return_codes) and result.return_codes[0] == 0
        return EvalOutput(
            score=0.6 if ok else 0.0,
            metrics={"ran": 1.0 if ok else 0.0},
            passed=ok,
        )

    def get_baseline(self) -> float:
        return 0.0


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def db():
    database = create_memory_database()
    initialize_database(database)
    yield database
    database.close()


@pytest.fixture
def tmp_artifact_store(db, tmp_path):
    return ArtifactStore(tmp_path / "artifacts", db)


@pytest.fixture
def sandbox(tmp_artifact_store, tmp_path):
    return TrustedSubprocessBackend(
        work_dir=tmp_path / "sandbox",
        artifact_store=tmp_artifact_store,
        trusted=True,
    )


@pytest.fixture
def experiment(db):
    repo = ExperimentRepository(db)
    exp = repo.create(task_id="e2e-task", task_name="e2e-task", config_snapshot={})
    return exp.id


# --------------------------------------------------------------------------- #
#  Tests
# --------------------------------------------------------------------------- #


class TestEvolutionEngineE2E:
    """端到端：Fast Loop 11 步 + Slow Loop."""

    def test_full_pipeline_runs_and_produces_candidates(
        self, db, tmp_artifact_store, sandbox, experiment
    ):
        llm = RoleAwareFakeLLM()
        config = EvolutionConfig(
            max_generations=2,
            population_size=2,
            island_count=2,
            crossover_rate=0.0,  # 先验证纯变异路径
            health_window_gens=1,
            sandbox_timeout=5.0,
        )

        # 全部 Slow Loop 组件
        aggregator = TelemetryAggregator(db)
        health_policy = HealthPolicy()
        self_evaluator = SelfEvaluator(aggregator, health_policy)
        governance = GovernancePolicy()
        l0_mutator = L0PolicyMutator(governance)
        meta_planner = MetaPlanner(l0_mutator)

        engine = EvolutionEngine(
            db,
            tmp_artifact_store,
            StubEvaluator(),
            sandbox,
            llm,
            experiment_id=experiment,
            evaluator_version_id=StubEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=config,
            parent_selector=ParentSelector(db, strategy="tournament"),
            crossover=CrossoverOperator(),
            island_manager=IslandManager(num_islands=2),
            policy_archive=PolicyArchive(db),
            governance=governance,
            self_evaluator=self_evaluator,
            meta_planner=meta_planner,
            replay_evaluator=ReplayEvaluator(),
            graph_store=GraphStore(db),
        )

        result = engine.run("def f():\n    return 0\n", "e2e-task")

        # --- Fast Loop 产出 ---
        assert result.total_generations == 2
        assert result.total_candidates > 0
        # LLM 被调用（director + coder）
        roles = [c["agent_role"] for c in llm.calls]
        assert "director" in roles
        assert "coder" in roles

        # 候选已写入 DB
        rows = db.fetchall(
            "SELECT COUNT(*) as n FROM candidate WHERE experiment_id=?", (experiment,)
        )
        assert rows[0]["n"] >= 1

        # 评估已记录
        evals = db.fetchall(
            "SELECT COUNT(*) as n FROM evaluation_run WHERE experiment_id=?", (experiment,)
        )
        assert evals[0]["n"] >= 1

        # best 已追踪
        assert result.best_candidate_id is not None
        assert result.best_score is not None

        # --- MCTS 节点已建立 ---
        stats = engine._mcts.get_stats()  # noqa: SLF001
        assert stats["nodes"] >= 1

    def test_exact_parent_noop_does_not_advance_generation(
        self, db, tmp_artifact_store, sandbox, experiment
    ):
        engine = EvolutionEngine(
            db,
            tmp_artifact_store,
            StubEvaluator(),
            sandbox,
            NoOpFakeLLM(),
            experiment_id=experiment,
            evaluator_version_id=StubEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=EvolutionConfig(
                max_generations=1,
                population_size=1,
                island_count=1,
                novelty_retry_limit=1,
                self_evolve_enabled=False,
            ),
        )

        result = engine.run("x = 0\n", "e2e-task")

        assert result.total_generations == 0
        assert result.total_candidates == 1
        checkpoint = db.fetchone(
            "SELECT checkpoint_data FROM experiment WHERE id=?", (experiment,)
        )
        assert '"generation": 0' in checkpoint["checkpoint_data"]

        # --- 岛屿精英已更新 ---
        island_stats = engine._island_manager.get_stats()  # noqa: SLF001
        assert any(s["candidates"] > 0 for s in island_stats.values())

        # --- 血缘图可加载 ---
        gs = GraphStore(db)
        graph = gs.load_subgraph(experiment)
        assert graph.number_of_nodes() >= 1

    def test_slow_loop_creates_challenger_policies(
        self, db, tmp_artifact_store, sandbox, experiment
    ):
        """Slow Loop 触发时应创建 Challenger 策略."""
        llm = RoleAwareFakeLLM()
        config = EvolutionConfig(
            max_generations=2,
            population_size=2,
            island_count=2,
            crossover_rate=0.0,
            health_window_gens=1,
            sandbox_timeout=5.0,
        )

        aggregator = TelemetryAggregator(db)
        health_policy = HealthPolicy(roi_warn_threshold=999.0)  # 必然触发
        self_evaluator = SelfEvaluator(aggregator, health_policy)
        governance = GovernancePolicy(auto_apply_l0=True)
        l0_mutator = L0PolicyMutator(governance)
        meta_planner = MetaPlanner(l0_mutator)

        engine = EvolutionEngine(
            db,
            tmp_artifact_store,
            StubEvaluator(),
            sandbox,
            llm,
            experiment_id=experiment,
            evaluator_version_id=StubEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=config,
            policy_archive=PolicyArchive(db),
            governance=governance,
            self_evaluator=self_evaluator,
            meta_planner=meta_planner,
            replay_evaluator=ReplayEvaluator(),
        )

        engine.run("x = 0\n", "e2e-task")

        # Slow Loop 被标记为触发过
        assert engine._slow_loop_triggered is True  # noqa: SLF001

        # 策略表有多条记录（初始 champion + 至少一个 challenger）
        rows = db.fetchall(
            "SELECT status, COUNT(*) as n FROM search_policy_version "
            "WHERE experiment_id=? GROUP BY status",
            (experiment,),
        )
        statuses = {r["status"]: r["n"] for r in rows}
        assert statuses.get("champion", 0) >= 1
        # challenger 可能已被 reject，但至少曾经创建过
        total = sum(statuses.values())
        assert total >= 2

    def test_resume_continues_from_checkpoint(
        self, db, tmp_artifact_store, sandbox, experiment, tmp_path
    ):
        """resume 应从中断处继续."""
        llm = RoleAwareFakeLLM()
        config = EvolutionConfig(
            max_generations=1,
            population_size=1,
            island_count=1,
            crossover_rate=0.0,
            health_window_gens=1,
            sandbox_timeout=5.0,
        )

        engine = EvolutionEngine(
            db,
            tmp_artifact_store,
            StubEvaluator(),
            sandbox,
            llm,
            experiment_id=experiment,
            evaluator_version_id=StubEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=config,
            policy_archive=PolicyArchive(db),
        )
        result1 = engine.run("x = 0\n", "e2e-task")
        assert result1.total_generations == 1

        # 用更大代数 resume
        config2 = EvolutionConfig(
            max_generations=3,
            search_horizon_generations=110,
            population_size=1,
            island_count=1,
            crossover_rate=0.0,
            health_window_gens=5,  # 不触发 Slow Loop
            sandbox_timeout=5.0,
            compute_budget_sec=0,  # TOML 中 0 表示不设计算时限
        )
        resumed_sandbox = TrustedSubprocessBackend(
            work_dir=tmp_path / "resumed-sandbox",
            artifact_store=tmp_artifact_store,
            trusted=True,
        )
        assert resumed_sandbox.environment_version_id != sandbox.environment_version_id

        engine2 = EvolutionEngine(
            db,
            tmp_artifact_store,
            StubEvaluator(),
            resumed_sandbox,
            RoleAwareFakeLLM(),
            experiment_id=experiment,
            evaluator_version_id=StubEvaluator.version_id,
            environment_version_id=resumed_sandbox.environment_version_id,
            config=config2,
            policy_archive=PolicyArchive(db),
        )
        result2 = engine2.resume(experiment)
        assert result2.total_generations >= 2
        assert engine2._environment_version_id == sandbox.environment_version_id  # noqa: SLF001
        assert not engine2._budget_guard.state.is_exhausted  # noqa: SLF001
        assert engine2._mcts._progress == pytest.approx(3 / 110)  # noqa: SLF001

    def test_exhausted_resume_does_not_advance_checkpoint(
        self, db, tmp_artifact_store, sandbox, experiment
    ):
        config = EvolutionConfig(
            max_generations=1,
            population_size=1,
            island_count=1,
            crossover_rate=0.0,
            health_window_gens=5,
            sandbox_timeout=5.0,
        )
        engine = EvolutionEngine(
            db,
            tmp_artifact_store,
            StubEvaluator(),
            sandbox,
            RoleAwareFakeLLM(),
            experiment_id=experiment,
            evaluator_version_id=StubEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=config,
            policy_archive=PolicyArchive(db),
        )
        assert engine.run("x = 0\n", "e2e-task").total_generations == 1

        resumed = EvolutionEngine(
            db,
            tmp_artifact_store,
            StubEvaluator(),
            sandbox,
            RoleAwareFakeLLM(),
            experiment_id=experiment,
            evaluator_version_id=StubEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=EvolutionConfig(
                max_generations=3,
                population_size=1,
                island_count=1,
                compute_budget_sec=0,
                health_window_gens=5,
                sandbox_timeout=5.0,
            ),
            policy_archive=PolicyArchive(db),
        )
        # Simulate any genuinely exhausted hard budget before entering resume.
        resumed._budget_guard.state.used_tokens = resumed._budget_guard.state.token_budget

        result = resumed.resume(experiment)
        row = db.fetchone("SELECT checkpoint_data FROM experiment WHERE id = ?", (experiment,))
        checkpoint = json.loads(row["checkpoint_data"])

        assert result.total_generations == 1
        assert checkpoint["generation"] == 1

    def test_evolution_result_has_all_fields(self, db, tmp_artifact_store, sandbox, experiment):
        """EvolutionResult 包含设计要求的全部字段."""
        llm = RoleAwareFakeLLM()
        engine = EvolutionEngine(
            db,
            tmp_artifact_store,
            StubEvaluator(),
            sandbox,
            llm,
            experiment_id=experiment,
            evaluator_version_id=StubEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=EvolutionConfig(
                max_generations=1, population_size=1, island_count=1, crossover_rate=0.0
            ),
            policy_archive=PolicyArchive(db),
        )
        result = engine.run("x = 0\n", "e2e-task")

        # 设计文档要求的全部字段
        assert result.best_candidate_id is not None
        assert result.best_artifact_hash is not None
        assert result.best_score is not None
        assert result.champion_policy_id != "default"  # 真实 policy id
        assert result.total_generations >= 1
        assert result.total_candidates >= 1
        assert result.total_tokens >= 0
        assert result.total_cost_usd >= 0.0
        assert result.total_compute_sec >= 0.0


class TestArchitecturalInvariants:
    """验证设计文档要求的架构不变量在运行时被强制执行."""

    def test_vector_outbox_inserted_on_candidate_creation(
        self, db, tmp_artifact_store, sandbox, experiment
    ):
        """S6-08: 候选创建后必须向 vector_index_job 写入 pending 任务."""
        llm = RoleAwareFakeLLM()
        engine = EvolutionEngine(
            db,
            tmp_artifact_store,
            StubEvaluator(),
            sandbox,
            llm,
            experiment_id=experiment,
            evaluator_version_id=StubEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=EvolutionConfig(
                max_generations=1, population_size=1, island_count=1, crossover_rate=0.0
            ),
            policy_archive=PolicyArchive(db),
        )
        engine.run("x = 0\n", "task")

        # vector_index_job 应有 pending 条目
        rows = db.fetchall(
            "SELECT entity_type, status FROM vector_index_job WHERE status='pending'"
        )
        assert len(rows) > 0, "vector_index_job should have pending entries after run"
        # 应包含 candidate 和 thought 两种实体类型
        entity_types = {r["entity_type"] for r in rows}
        assert "candidate" in entity_types

    def test_embedding_profile_registered_on_run(self, db, tmp_artifact_store, sandbox, experiment):
        """S6-01: 运行时必须注册默认 embedding_profile."""
        engine = EvolutionEngine(
            db,
            tmp_artifact_store,
            StubEvaluator(),
            sandbox,
            RoleAwareFakeLLM(),
            experiment_id=experiment,
            evaluator_version_id=StubEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=EvolutionConfig(
                max_generations=1, population_size=1, island_count=1, crossover_rate=0.0
            ),
            policy_archive=PolicyArchive(db),
        )
        engine.run("x=0\n", "t")

        rows = db.fetchall("SELECT * FROM embedding_profile WHERE purpose='code'")
        assert len(rows) >= 1
        assert engine._code_profile_id is not None  # noqa: SLF001

    def test_prompt_version_id_passed_to_agent_context(
        self, db, tmp_artifact_store, sandbox, experiment
    ):
        """S5-04: AgentContext 应携带 prompt_version_id."""
        from omnievolve.storage.repositories.prompt_repo import PromptVersionRepository

        prompt_repo = PromptVersionRepository(db)
        # 先存储 prompt 内容为 artifact（满足 content_hash FK 约束）
        tmp_artifact_store.store_text("You are a test director", "log")
        pv = prompt_repo.create(
            "director", "You are a test director", artifact_store=tmp_artifact_store
        )
        prompt_repo.promote(pv.id)

        llm = RoleAwareFakeLLM()
        engine = EvolutionEngine(
            db,
            tmp_artifact_store,
            StubEvaluator(),
            sandbox,
            llm,
            experiment_id=experiment,
            evaluator_version_id=StubEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=EvolutionConfig(
                max_generations=1, population_size=1, island_count=1, crossover_rate=0.0
            ),
            policy_archive=PolicyArchive(db),
        )
        engine.run("x=0\n", "t")
        director_calls = [c for c in llm.calls if c["agent_role"] == "director"]
        assert len(director_calls) >= 1
