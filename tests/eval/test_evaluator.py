"""TaskEvaluator 和 EvaluationRun 测试.

S3-13: 实现 evaluator 不可越权测试
S3-14: 实现 EvaluationRun 复现测试
"""

import pytest

from omnievolve.eval.demo_evaluator import PythonUnitTestEvaluator, SimpleScoreEvaluator
from omnievolve.eval.evaluation_run import (
    EvaluationRunRepository,
    EvaluationRunStatus,
)
from omnievolve.eval.evaluator_registry import (
    EvaluatorRegistry,
    check_evaluator_immutability,
)
from omnievolve.eval.task_evaluator import (
    CandidateArtifact,
    EvalOutput,
    EvaluationContext,
    EvaluationPlan,
    SandboxExecutionResult,
    TaskEvaluator,
)
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database

pytestmark = pytest.mark.unit


@pytest.fixture
def db():
    """创建已初始化的内存数据库."""
    database = create_memory_database()
    initialize_database(database)
    yield database
    database.close()


@pytest.fixture
def registry(db):
    """创建 EvaluatorRegistry."""
    return EvaluatorRegistry(db)


@pytest.fixture
def run_repo(db):
    """创建 EvaluationRunRepository."""
    return EvaluationRunRepository(db)


class TestTaskEvaluatorProtocol:
    """TaskEvaluator Protocol 测试."""

    def test_demo_evaluator_implements_protocol(self):
        """Demo evaluator 应实现 TaskEvaluator 协议."""
        evaluator = PythonUnitTestEvaluator()
        assert isinstance(evaluator, TaskEvaluator)

    def test_simple_score_evaluator_implements_protocol(self):
        """SimpleScoreEvaluator 应实现 TaskEvaluator 协议."""
        evaluator = SimpleScoreEvaluator()
        assert isinstance(evaluator, TaskEvaluator)

    def test_build_plan_returns_evaluation_plan(self):
        """build_plan 应返回 EvaluationPlan."""
        evaluator = PythonUnitTestEvaluator()
        candidate = CandidateArtifact(
            candidate_id="cand1",
            source_hash="abc123",
            manifest_hash=None,
            language="python",
        )
        context = EvaluationContext(
            experiment_id="exp1",
            evaluator_version_id="eval1",
            environment_version_id="env1",
        )

        plan = evaluator.build_plan(candidate, context)

        assert isinstance(plan, EvaluationPlan)
        assert len(plan.commands) > 0
        assert not plan.network_access

    def test_parse_result_returns_eval_output(self):
        """parse_result 应返回 EvalOutput."""
        evaluator = PythonUnitTestEvaluator()
        result = SandboxExecutionResult(
            return_codes=[0],
            stdout="===== 5 passed in 0.1s =====",
            stderr="",
            output_artifacts={},
            execution_time_ms=100.0,
            cpu_time_ms=90.0,
            memory_peak_kb=1024,
        )
        context = EvaluationContext(
            experiment_id="exp1",
            evaluator_version_id="eval1",
            environment_version_id="env1",
        )

        output = evaluator.parse_result(result, context)

        assert isinstance(output, EvalOutput)
        assert output.passed
        assert output.score == 1.0


class TestEvaluatorRegistry:
    """EvaluatorRegistry 测试."""

    def test_register_evaluator(self, registry: EvaluatorRegistry):
        """注册评估器."""
        evaluator = PythonUnitTestEvaluator()
        version_id = registry.register(evaluator)

        assert version_id is not None
        assert len(version_id) == 16

    def test_register_idempotent(self, registry: EvaluatorRegistry):
        """重复注册应返回相同 ID."""
        evaluator = PythonUnitTestEvaluator()
        id1 = registry.register(evaluator)
        id2 = registry.register(evaluator)

        assert id1 == id2

    def test_get_evaluator_info(self, registry: EvaluatorRegistry):
        """获取评估器信息."""
        evaluator = PythonUnitTestEvaluator()
        version_id = registry.register(evaluator)

        info = registry.get(version_id)

        assert info is not None
        assert info.name == "python-unittest"
        assert info.semantic_version == "1.0.0"
        assert info.immutable_core

    def test_verify_immutability(self, registry: EvaluatorRegistry):
        """验证不可变性."""
        evaluator = PythonUnitTestEvaluator()
        version_id = registry.register(evaluator)

        # 相同实现应通过验证
        assert registry.verify_immutability(version_id, evaluator)

    def test_check_immutability_passes(self, registry: EvaluatorRegistry):
        """不可变性检查通过."""
        evaluator = PythonUnitTestEvaluator()
        version_id = registry.register(evaluator)

        # 不应抛出异常
        check_evaluator_immutability(registry, version_id, evaluator)


class TestEvaluationRun:
    """EvaluationRun 测试."""

    @pytest.fixture(autouse=True)
    def setup_fk_data(self, db):
        """创建外键依赖数据."""
        db.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
            ("exp1", "task1", "Test", "{}"),
        )
        db.execute(
            """
            INSERT INTO task_evaluator_version
                (id, name, semantic_version, implementation_hash, task_semantics_hash, score_schema)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("eval1", "test", "1.0", "hash1", "sem1", "{}"),
        )
        db.execute(
            """
            INSERT INTO execution_environment_version (id, backend, resource_policy, network_policy)
            VALUES (?, ?, ?, ?)
            """,
            ("env1", "docker", "{}", "none"),
        )
        db.execute(
            """
            INSERT INTO artifact (hash, artifact_type, byte_size, relative_path)
            VALUES (?, ?, ?, ?)
            """,
            ("art1", "source", 100, "sha256/ar/t1/art1"),
        )
        db.execute(
            """
            INSERT INTO candidate (id, experiment_id, task_id, generation, artifact_hash, search_policy_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("cand1", "exp1", "task1", 1, "art1", "policy1"),
        )
        db.execute(
            """
            INSERT INTO candidate (id, experiment_id, task_id, generation, artifact_hash, search_policy_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("cand2", "exp1", "task1", 1, "art1", "policy1"),
        )

    def test_create_run(self, run_repo: EvaluationRunRepository):
        """创建评估运行."""
        run = run_repo.create(
            experiment_id="exp1",
            candidate_id="cand1",
            evaluator_version_id="eval1",
            environment_version_id="env1",
            seed=42,
        )

        assert run.id is not None
        assert run.status == EvaluationRunStatus.QUEUED
        assert run.seed == 42

    def test_idempotent_create(self, run_repo: EvaluationRunRepository):
        """幂等创建."""
        run1 = run_repo.create(
            experiment_id="exp1",
            candidate_id="cand1",
            evaluator_version_id="eval1",
            environment_version_id="env1",
            seed=42,
            split_name="default",
            attempt=1,
        )

        run2 = run_repo.create(
            experiment_id="exp1",
            candidate_id="cand1",
            evaluator_version_id="eval1",
            environment_version_id="env1",
            seed=42,
            split_name="default",
            attempt=1,
        )

        assert run1.id == run2.id

    def test_run_lifecycle(self, run_repo: EvaluationRunRepository):
        """运行生命周期."""
        run = run_repo.create(
            experiment_id="exp1",
            candidate_id="cand1",
            evaluator_version_id="eval1",
            environment_version_id="env1",
        )

        # queued -> running
        assert run_repo.start(run.id)
        run = run_repo.get(run.id)
        assert run.status == EvaluationRunStatus.RUNNING
        assert run.started_at is not None

        # running -> completed
        assert run_repo.complete(
            run.id,
            passed=True,
            primary_score=0.95,
            metrics={"accuracy": 0.95},
            execution_time_ms=100.0,
        )
        run = run_repo.get(run.id)
        assert run.status == EvaluationRunStatus.COMPLETED
        assert run.passed
        assert run.primary_score == 0.95
        assert run.finished_at is not None

    def test_run_failure(self, run_repo: EvaluationRunRepository):
        """运行失败."""
        run = run_repo.create(
            experiment_id="exp1",
            candidate_id="cand2",
            evaluator_version_id="eval1",
            environment_version_id="env1",
        )

        run_repo.start(run.id)
        assert run_repo.fail(run.id)

        run = run_repo.get(run.id)
        assert run.status == EvaluationRunStatus.FAILED

    def test_list_by_candidate(self, run_repo: EvaluationRunRepository):
        """按候选列出."""
        for i in range(3):
            run_repo.create(
                experiment_id="exp1",
                candidate_id="cand1",
                evaluator_version_id="eval1",
                environment_version_id="env1",
                seed=i,
            )

        runs = run_repo.list_by_candidate("cand1")
        assert len(runs) == 3

    def test_get_best_score(self, run_repo: EvaluationRunRepository):
        """获取最佳分数."""
        # 创建完成的运行
        run = run_repo.create(
            experiment_id="exp1",
            candidate_id="cand1",
            evaluator_version_id="eval1",
            environment_version_id="env1",
        )
        run_repo.start(run.id)
        run_repo.complete(run.id, passed=True, primary_score=0.85)

        best = run_repo.get_best_score("exp1", "eval1", "env1")
        assert best == 0.85


class TestDemoEvaluators:
    """Demo Evaluators 测试."""

    def test_pytest_output_parsing(self):
        """pytest 输出解析."""
        evaluator = PythonUnitTestEvaluator()

        result = SandboxExecutionResult(
            return_codes=[0],
            stdout="===== 10 passed, 2 failed in 1.5s =====",
            stderr="",
            output_artifacts={},
            execution_time_ms=1500.0,
            cpu_time_ms=1400.0,
            memory_peak_kb=2048,
        )
        context = EvaluationContext(
            experiment_id="exp1",
            evaluator_version_id="eval1",
            environment_version_id="env1",
        )

        output = evaluator.parse_result(result, context)

        assert output.metrics["tests_passed"] == 10
        assert output.metrics["tests_total"] == 12
        assert output.score == pytest.approx(10 / 12)
        assert not output.passed  # 有失败

    def test_timeout_handling(self):
        """超时处理."""
        evaluator = PythonUnitTestEvaluator()

        result = SandboxExecutionResult(
            return_codes=[-1],
            stdout="",
            stderr="",
            output_artifacts={},
            execution_time_ms=30000.0,
            cpu_time_ms=0,
            memory_peak_kb=0,
            timed_out=True,
        )
        context = EvaluationContext(
            experiment_id="exp1",
            evaluator_version_id="eval1",
            environment_version_id="env1",
        )

        output = evaluator.parse_result(result, context)

        assert not output.passed
        assert output.score == 0.0
        assert "timed out" in output.failure_reason.lower()
