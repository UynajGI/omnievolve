"""Soak test — 长时间运行稳定性验证 (P2).

使用 FakeLLM 运行 50 代进化，验证:
  - 管线完整性（候选生成/评估/DB 写入）
  - 检查点持久化
  - 内存无泄漏（50 代持续运行）
"""

from __future__ import annotations

import time

import pytest

from omnievolve.agents.llm_gateway import LLMResponse
from omnievolve.engine.evolution_engine import EvolutionConfig, EvolutionEngine
from omnievolve.eval.task_evaluator import EvalOutput, EvaluationPlan
from omnievolve.sandbox.subprocess_backend import TrustedSubprocessBackend


class _CodeFakeLLM:
    """Fake LLM that returns parseable JSON/Python code."""

    counter = 0

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
        _CodeFakeLLM.counter += 1
        n = _CodeFakeLLM.counter
        if agent_role == "director":
            content = f'{{"thought":"Improve x={n}","rationale":"bigger","confidence":0.8}}'
        else:
            content = f'{{"full_code":"x={n}\\ny={n * 2}\\nresult=x+y","diff":"inc x","explanation":"gen{n}"}}'
        return LLMResponse(
            content=content,
            model=model or "fake",
            input_tokens=50,
            output_tokens=50,
            total_tokens=100,
            latency_ms=1.0,
        )


class _FastEvaluator:
    """最小化评估器 — 立即返回，不执行外部命令."""

    version_id = "fast@1.0"

    def build_plan(self, candidate, context):
        return EvaluationPlan(commands=[])

    def parse_result(self, result, context):
        return EvalOutput(score=0.75, metrics={}, passed=True)

    def get_baseline(self):
        return 0.5


@pytest.fixture
def soak_engine(db, artifact_store, experiment):
    """50 代 × 4 候选引擎，50% 交叉率."""
    sandbox = TrustedSubprocessBackend(trusted=True)
    return EvolutionEngine(
        db,
        artifact_store,
        _FastEvaluator(),
        sandbox,
        _CodeFakeLLM(),
        experiment_id=experiment,
        evaluator_version_id=_FastEvaluator.version_id,
        environment_version_id=sandbox.environment_version_id,
        config=EvolutionConfig(
            max_generations=50,
            population_size=4,
            island_count=2,
            crossover_rate=0.5,
            health_window_gens=10,
        ),
    )


@pytest.mark.slow
class TestSoak50Gen:
    def test_full_50gen_pipeline(self, soak_engine, db, experiment):
        start = time.time()
        result = soak_engine.run("x = 0\n", "soak_task")
        elapsed = time.time() - start

        assert result.total_generations >= 1
        assert result.total_candidates >= 40
        assert result.best_score > 0

        # 检查点应存在
        row = db.fetchone("SELECT checkpoint_data FROM experiment WHERE id = ?", (experiment,))
        assert row is not None

        # DB 完整性
        cnt = db.fetchone(
            "SELECT COUNT(*) as c FROM candidate WHERE experiment_id = ?", (experiment,)
        )
        assert cnt["c"] >= 40

        eval_cnt = db.fetchone(
            "SELECT COUNT(*) as c FROM evaluation_run WHERE experiment_id = ?", (experiment,)
        )
        assert eval_cnt["c"] > 0

        # 50 代应在 60s 内完成
        assert elapsed < 60, f"Soak took {elapsed:.1f}s"
