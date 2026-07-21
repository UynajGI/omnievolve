"""AsyncEvolutionEngine.run() 集成测试 — 零覆盖核心路径填补 (C7).

使用基于文件的 SQLite DB（WAL 模式）验证并行进化主循环。
AsyncEngine.run() 之前从未被任何测试执行。
"""

from __future__ import annotations

import asyncio

import pytest

from omnievolve.agents.llm_gateway import LLMResponse
from omnievolve.engine.async_engine import AsyncEvolutionEngine
from omnievolve.engine.evolution_engine import EvolutionConfig, EvolutionEngine
from omnievolve.eval.task_evaluator import EvalOutput, EvaluationPlan
from omnievolve.sandbox.subprocess_backend import TrustedSubprocessBackend
from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import Database
from omnievolve.storage.repositories.experiment_repo import ExperimentRepository


class _CountingFakeLLM:
    """可解析的 FakeLLM，统计调用次数."""

    def __init__(self) -> None:
        self.call_count = 0

    def chat(
        self,
        messages,
        *,
        model=None,
        temperature=0.7,
        max_tokens=None,
        experiment_id=None,
        agent_role="unknown",
        prompt_version_id=None,
    ):
        self.call_count += 1
        n = self.call_count
        if agent_role == "director":
            content = f'{{"thought":"Try x={n}","rationale":"test","confidence":0.8}}'
        else:
            content = f'{{"full_code":"x={n}\\ny={n}","diff":"x","explanation":"gen{n}"}}'
        return LLMResponse(
            content=content,
            model=model or "fake",
            input_tokens=50,
            output_tokens=50,
            total_tokens=100,
            latency_ms=1.0,
        )


class _NoopEvaluator:
    """评估器 — 不执行代码，直接返回分数."""

    version_id = "noop@1.0"

    def build_plan(self, candidate, context):
        return EvaluationPlan(commands=[])

    def parse_result(self, result, context):
        return EvalOutput(score=0.5, metrics={}, passed=True)

    def get_baseline(self):
        return 0.5


@pytest.fixture
def file_db(tmp_path):
    """基于文件的 SQLite DB，WAL 模式，可跨线程共享."""
    from omnievolve.storage.migrations import initialize_database

    db_path = tmp_path / "async_test.db"
    db = Database(str(db_path), wal=True)
    initialize_database(db)
    yield db
    db.close_all()


@pytest.fixture
def file_artifact_store(file_db, tmp_path):
    return ArtifactStore(tmp_path / "artifacts", file_db)


@pytest.fixture
def file_experiment(file_db):
    repo = ExperimentRepository(file_db)
    exp = repo.create(task_id="async_e2e", task_name="async-e2e-task", config_snapshot={})
    return exp.id


class TestAsyncEngineRunE2E:
    """AsyncEngine.run() 主循环端到端 — 首次覆盖."""

    def test_run_produces_candidates(self, file_db, file_artifact_store, file_experiment):
        """run() 应完成并产生候选."""
        sandbox = TrustedSubprocessBackend(trusted=True)
        llm = _CountingFakeLLM()
        engine = EvolutionEngine(
            file_db,
            file_artifact_store,
            _NoopEvaluator(),
            sandbox,
            llm,
            experiment_id=file_experiment,
            evaluator_version_id=_NoopEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=EvolutionConfig(
                max_generations=3,
                population_size=2,
                island_count=1,
                crossover_rate=0.0,
                health_window_gens=99,
            ),
        )
        ae = AsyncEvolutionEngine(engine, concurrency=2)

        async def _run():
            return await ae.run("x = 0\n", "async_e2e")

        result = asyncio.run(_run())

        assert result.total_candidates >= 3  # 1 initial + 3 gen × at least some
        assert result.best_score > 0
        assert llm.call_count > 0

    def test_run_writes_to_db(self, file_db, file_artifact_store, file_experiment):
        """run() 的结果应持久化到文件 DB."""
        sandbox = TrustedSubprocessBackend(trusted=True)
        llm = _CountingFakeLLM()
        engine = EvolutionEngine(
            file_db,
            file_artifact_store,
            _NoopEvaluator(),
            sandbox,
            llm,
            experiment_id=file_experiment,
            evaluator_version_id=_NoopEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=EvolutionConfig(
                max_generations=2,
                population_size=3,
                island_count=1,
                crossover_rate=0.0,
                health_window_gens=99,
            ),
        )
        ae = AsyncEvolutionEngine(engine, concurrency=3)

        asyncio.run(ae.run("x = 0\n", "async_db_test"))

        # 验证 DB 中有候选和评估记录
        cand_count = file_db.fetchone(
            "SELECT COUNT(*) as c FROM candidate WHERE experiment_id = ?",
            (file_experiment,),
        )
        assert cand_count["c"] >= 2

        eval_count = file_db.fetchone(
            "SELECT COUNT(*) as c FROM evaluation_run WHERE experiment_id = ?",
            (file_experiment,),
        )
        assert eval_count["c"] > 0

    def test_shutdown_stops_gracefully(self, file_db, file_artifact_store, file_experiment):
        """SIGINT 后应优雅退出."""
        sandbox = TrustedSubprocessBackend(trusted=True)
        llm = _CountingFakeLLM()
        engine = EvolutionEngine(
            file_db,
            file_artifact_store,
            _NoopEvaluator(),
            sandbox,
            llm,
            experiment_id=file_experiment,
            evaluator_version_id=_NoopEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=EvolutionConfig(
                max_generations=10,
                population_size=2,
            ),
        )
        ae = AsyncEvolutionEngine(engine, concurrency=2)

        async def _run():
            ae._request_shutdown()
            return await ae.run("x = 0\n", "async_shutdown_test")

        result = asyncio.run(_run())
        assert result is not None
