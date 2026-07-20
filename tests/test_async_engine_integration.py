"""AsyncEvolutionEngine 集成测试 — 生命周期管理.

AsyncEngine 主循环需要通过基于文件的 DB 进行测试（:memory: 在线程间不共享）。
此处测试生命周期和组件初始化。
"""

from __future__ import annotations

import pytest

from omnievolve.agents.llm_gateway import FakeLLM
from omnievolve.engine.async_engine import AsyncEvolutionEngine
from omnievolve.engine.evolution_engine import EvolutionConfig, EvolutionEngine
from omnievolve.eval.task_evaluator import (
    EvalOutput,
    EvaluationPlan,
)
from omnievolve.sandbox.subprocess_backend import TrustedSubprocessBackend


class _NilEvaluator:
    version_id = "nil@1.0"

    def build_plan(self, c, ctx):
        return EvaluationPlan(commands=[])

    def parse_result(self, r, ctx):
        return EvalOutput(score=1.0, metrics={}, passed=True)

    def get_baseline(self):
        return 0.5


@pytest.fixture
def sandbox():
    return TrustedSubprocessBackend(trusted=True)


class TestAsyncEngineInit:
    def test_concurrency_from_config(self, db, artifact_store, experiment, sandbox):
        engine = EvolutionEngine(
            db,
            artifact_store,
            _NilEvaluator(),
            sandbox,
            FakeLLM(),
            experiment_id=experiment,
            evaluator_version_id=_NilEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=EvolutionConfig(max_generations=1, population_size=6),
        )
        ae = AsyncEvolutionEngine(engine)
        assert ae._concurrency == 8

    def test_shutdown_flag_works(self, db, artifact_store, experiment, sandbox):
        engine = EvolutionEngine(
            db,
            artifact_store,
            _NilEvaluator(),
            sandbox,
            FakeLLM(),
            experiment_id=experiment,
            evaluator_version_id=_NilEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=EvolutionConfig(max_generations=1),
        )
        ae = AsyncEvolutionEngine(engine)
        ae._request_shutdown()
        assert ae._shutdown_event.is_set()
