"""示例集成测试 — 验证真实示例通过完整进化管线.

用 FakeLLM + CirclePackingEvaluator/initial_code 端到端验证：
    LLM → 代码生成 → ArtifactStore → Sandbox 执行 → 评估 → DB 持久化
"""

from __future__ import annotations

import pytest

from omnievolve.agents.llm_gateway import LLMResponse
from omnievolve.engine.crossover import CrossoverOperator
from omnievolve.engine.evolution_engine import EvolutionConfig, EvolutionEngine
from omnievolve.engine.island import IslandManager
from omnievolve.engine.selection import ParentSelector
from omnievolve.meta.policy_archive import PolicyArchive
from omnievolve.sandbox.subprocess_backend import TrustedSubprocessBackend
from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.repositories.experiment_repo import ExperimentRepository

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
#  Fake LLM — 生成 circle packing 代码
# --------------------------------------------------------------------------- #

CIRCLE_CODE = """\
import math

def pack_circles(num_circles, positions, radii):
    min_radius = float("inf")
    for i in range(num_circles):
        x_i, y_i = positions[i]
        r_max = min(x_i, 1.0 - x_i, y_i, 1.0 - y_i)
        min_radius = min(min_radius, r_max)
        for j in range(i + 1, num_circles):
            x_j, y_j = positions[j]
            dist = math.hypot(x_i - x_j, y_i - y_j)
            min_radius = min(min_radius, dist - radii[j])
    return -min_radius

def solve():
    n = 9
    side = int(math.sqrt(n))
    radius = 0.5 / side * 0.85
    positions = [(radius + (i % side) * 2 * radius, radius + (i // side) * 2 * radius) for i in range(n)]
    radii = [radius] * n
    return pack_circles(n, positions, radii)

if __name__ == "__main__":
    print(solve())
"""


class CircleFakeLLM:
    """Fake LLM — 生成 circle packing 代码并评分."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

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
                '{"thought": "Try a denser grid layout", '
                '"rationale": "increase packing density by adjusting spacing", '
                '"confidence": 0.75, '
                '"mechanism_tags": ["geometry"]}'
            )
        elif agent_role == "coder":
            content = (
                '{"full_code": ' + repr(CIRCLE_CODE) + ", "
                '"diff": "rewrite", "explanation": "adjusted spacing factor"}'
            )
        else:
            content = '{"passed": true, "feedback": "good packing"}'

        return LLMResponse(
            content=content,
            model=model or "fake",
            input_tokens=50,
            output_tokens=30,
            total_tokens=80,
            latency_ms=1.0,
        )


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
    exp = repo.create(task_id="circle-packing", task_name="circle-packing", config_snapshot={})
    return exp.id


# --------------------------------------------------------------------------- #
#  Tests
# --------------------------------------------------------------------------- #


class TestCirclePackingIntegration:
    """Circle Packing 示例集成测试."""

    def test_full_pipeline_with_circle_packing_example(
        self, db, tmp_artifact_store, sandbox, experiment
    ):
        """使用 circle_packing 示例跑通完整进化管线."""
        from examples.circle_packing.evaluator import CirclePackingEvaluator

        llm = CircleFakeLLM()
        config = EvolutionConfig(
            max_generations=2,
            population_size=2,
            island_count=1,
            crossover_rate=0.0,
            health_window_gens=10,  # 不触发 Slow Loop
            sandbox_timeout=5.0,
        )

        engine = EvolutionEngine(
            db,
            tmp_artifact_store,
            CirclePackingEvaluator(),
            sandbox,
            llm,
            experiment_id=experiment,
            evaluator_version_id=CirclePackingEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=config,
            parent_selector=ParentSelector(db, strategy="tournament"),
            crossover=CrossoverOperator(),
            island_manager=IslandManager(num_islands=1),
            policy_archive=PolicyArchive(db),
        )

        # 读取 circle_packing 初始代码
        from pathlib import Path

        initial_code = (
            Path(__file__).parent.parent / "examples" / "circle_packing" / "initial_code.py"
        ).read_text()

        result = engine.run(initial_code, "circle-packing")

        # --- 基础产出 ---
        assert result.total_generations == 2
        assert result.total_candidates > 0
        assert result.best_candidate_id is not None
        assert result.best_score is not None

        # LLM 调用过 director + coder
        roles = {c["agent_role"] for c in llm.calls}
        assert "director" in roles
        assert "coder" in roles

        # --- 候选已写入 DB ---
        rows = db.fetchall(
            "SELECT COUNT(*) as n FROM candidate WHERE experiment_id=?", (experiment,)
        )
        assert rows[0]["n"] >= 1

        # --- 评估已记录（真实沙箱执行） ---
        evals = db.fetchall(
            """
            SELECT er.primary_score, er.passed, er.status
            FROM evaluation_run er
            JOIN candidate c ON er.candidate_id = c.id
            WHERE c.experiment_id = ?
            """,
            (experiment,),
        )
        assert len(evals) >= 1
        # 至少有一条评估完成
        completed = [e for e in evals if e["status"] == "completed"]
        assert len(completed) >= 1, f"Expected completed evaluations, got: {evals}"

        # --- Fitness 分数应该有值（circle packing 返回负 fitness，越大越好） ---
        scores = [e["primary_score"] for e in completed]
        assert len(scores) >= 1
        # 负分是正常的（fitness = -min_radius），只要不是 0.0 就行
        assert any(s != 0.0 for s in scores), f"Expected non-zero scores, got: {scores}"

        # --- Artifact 已存储（内容寻址） ---
        artifacts = db.fetchall("SELECT COUNT(*) as n FROM artifact")
        assert artifacts[0]["n"] >= 2  # 初始代码 + 至少一个候选

        # --- Vector outbox ---
        pending = db.fetchall("SELECT COUNT(*) as n FROM vector_index_job WHERE status='pending'")
        assert pending[0]["n"] > 0

    def test_circle_packing_evaluator_runs_candidate_code(
        self, db, tmp_artifact_store, sandbox, experiment
    ):
        """验证 circle_packing evaluator 真实执行了 LLM 生成的候选代码."""
        from examples.circle_packing.evaluator import CirclePackingEvaluator

        # 使用会生成不同代码的 FakeLLM
        llm = CircleFakeLLM()
        config = EvolutionConfig(
            max_generations=1,
            population_size=1,
            island_count=1,
            crossover_rate=0.0,
            health_window_gens=100,
            sandbox_timeout=5.0,
        )

        engine = EvolutionEngine(
            db,
            tmp_artifact_store,
            CirclePackingEvaluator(),
            sandbox,
            llm,
            experiment_id=experiment,
            evaluator_version_id=CirclePackingEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
            config=config,
            policy_archive=PolicyArchive(db),
        )

        result = engine.run("print(0.0)\n", "cp-test")

        # 候选应已评估完成
        evals = db.fetchall(
            """
            SELECT er.primary_score, er.passed, er.status, er.metrics
            FROM evaluation_run er
            JOIN candidate c ON er.candidate_id = c.id
            WHERE c.experiment_id = ?
            """,
            (experiment,),
        )
        assert len(evals) >= 1
        # fitness 指标应存在
        for e in evals:
            if e["metrics"]:
                import json

                metrics = (
                    json.loads(e["metrics"]) if isinstance(e["metrics"], str) else e["metrics"]
                )
                assert "fitness" in metrics, f"Expected 'fitness' in metrics, got: {metrics}"

        assert result.best_score is not None


class TestSortExampleEvaluator:
    """验证 SortEvaluator 能被 EvolutionEngine 加载和调用."""

    def test_sort_evaluator_build_plan(self):
        """SortEvaluator.build_plan 返回合法的 EvaluationPlan."""
        from examples.python_optimization.evaluator import SortEvaluator
        from omnievolve.eval.task_evaluator import CandidateArtifact, EvaluationContext
        from omnievolve.sandbox.base import EvaluationPlan

        evaluator = SortEvaluator()
        candidate = CandidateArtifact(
            candidate_id="test-1",
            source_hash="abc123",
            manifest_hash=None,
            language="python",
        )
        context = EvaluationContext(
            experiment_id="exp-1",
            evaluator_version_id="v1",
            environment_version_id="env-1",
        )

        plan = evaluator.build_plan(candidate, context)
        assert isinstance(plan, EvaluationPlan)
        assert len(plan.commands) == 2
        assert "benchmark_result.json" in plan.expected_outputs

    def test_sort_evaluator_parse_result_success(self):
        """SortEvaluator 正确解析成功结果."""
        from examples.python_optimization.evaluator import SortEvaluator
        from omnievolve.eval.task_evaluator import EvaluationContext
        from omnievolve.sandbox.base import SandboxExecutionResult

        evaluator = SortEvaluator()
        context = EvaluationContext(
            experiment_id="exp-1",
            evaluator_version_id="v1",
            environment_version_id="env-1",
        )

        # 模拟成功执行 + speedup 输出
        result = SandboxExecutionResult(
            return_codes=[0, 0],
            stdout='{"speedup": 5.0, "time_ms": 2.0}',
            stderr="",
            output_artifacts={},
            execution_time_ms=100.0,
            cpu_time_ms=50.0,
            memory_peak_kb=1024,
        )

        output = evaluator.parse_result(result, context)
        assert output.passed is True
        assert output.score > 0.5  # baseline 0.5 + speedup bonus
        assert output.metrics["speedup"] == 5.0

    def test_sort_evaluator_parse_result_failure(self):
        """SortEvaluator 正确处理测试失败."""
        from examples.python_optimization.evaluator import SortEvaluator
        from omnievolve.eval.task_evaluator import EvaluationContext
        from omnievolve.sandbox.base import SandboxExecutionResult

        evaluator = SortEvaluator()
        context = EvaluationContext(
            experiment_id="exp-1",
            evaluator_version_id="v1",
            environment_version_id="env-1",
        )

        result = SandboxExecutionResult(
            return_codes=[1],  # pytest 失败
            stdout="",
            stderr="FAILED test_sort.py::test_reverse",
            output_artifacts={},
            execution_time_ms=50.0,
            cpu_time_ms=30.0,
            memory_peak_kb=512,
        )

        output = evaluator.parse_result(result, context)
        assert output.passed is False
        assert output.score == 0.0


class TestCirclePackingEvaluatorUnit:
    """CirclePackingEvaluator 单元测试（无需 Sandbox）."""

    def test_build_plan_runs_main_py(self):
        """修复后 build_plan 应运行 main.py 而非硬编码字符串."""
        from examples.circle_packing.evaluator import CirclePackingEvaluator
        from omnievolve.eval.task_evaluator import CandidateArtifact, EvaluationContext

        evaluator = CirclePackingEvaluator()
        candidate = CandidateArtifact(
            candidate_id="cp-1",
            source_hash="def456",
            manifest_hash=None,
            language="python",
        )
        context = EvaluationContext(
            experiment_id="exp-1",
            evaluator_version_id="v1",
            environment_version_id="env-1",
        )

        plan = evaluator.build_plan(candidate, context)
        assert len(plan.commands) == 1
        # 应该是运行 main.py，不是硬编码字符串
        assert plan.commands[0].argv[-1] == "main.py"
        assert "-c" not in plan.commands[0].argv

    def test_parse_result_positive_fitness(self):
        """parse_result 正确解析正 fitness 值."""
        from examples.circle_packing.evaluator import CirclePackingEvaluator
        from omnievolve.eval.task_evaluator import EvaluationContext
        from omnievolve.sandbox.base import SandboxExecutionResult

        evaluator = CirclePackingEvaluator()
        context = EvaluationContext(
            experiment_id="exp-1",
            evaluator_version_id="v1",
            environment_version_id="env-1",
        )

        result = SandboxExecutionResult(
            return_codes=[0],
            stdout="-0.12\n",
            stderr="",
            output_artifacts={},
            execution_time_ms=10.0,
            cpu_time_ms=5.0,
            memory_peak_kb=256,
        )

        output = evaluator.parse_result(result, context)
        assert output.passed is True  # 执行成功即为通过
        assert output.metrics["fitness"] == pytest.approx(-0.12)
        assert output.score == pytest.approx(-0.12)

    def test_parse_result_execution_failure(self):
        """parse_result 处理执行失败."""
        from examples.circle_packing.evaluator import CirclePackingEvaluator
        from omnievolve.eval.task_evaluator import EvaluationContext
        from omnievolve.sandbox.base import SandboxExecutionResult

        evaluator = CirclePackingEvaluator()
        context = EvaluationContext(
            experiment_id="exp-1",
            evaluator_version_id="v1",
            environment_version_id="env-1",
        )

        result = SandboxExecutionResult(
            return_codes=[1],
            stdout="",
            stderr="NameError: name 'x' is not defined",
            output_artifacts={},
            execution_time_ms=5.0,
            cpu_time_ms=2.0,
            memory_peak_kb=128,
        )

        output = evaluator.parse_result(result, context)
        assert output.passed is False
        assert output.score == 0.0
