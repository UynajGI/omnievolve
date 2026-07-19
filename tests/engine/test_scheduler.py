"""Sprint 4 测试: Candidate图 + Scheduler + Job Lease."""

import pytest

from omnievolve.engine.scheduler import Scheduler
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.graph_store import GraphStore
from omnievolve.storage.job_store import JobStore
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.repositories.candidate_repo import CandidateRepository


@pytest.fixture
def db():
    """创建已初始化的内存数据库."""
    database = create_memory_database()
    initialize_database(database)
    yield database
    database.close()


@pytest.fixture
def setup_experiment(db):
    """创建实验基础数据."""
    db.execute(
        "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
        ("exp1", "task1", "Test Task", "{}"),
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
    return "exp1"


@pytest.fixture
def candidate_repo(db):
    return CandidateRepository(db)


@pytest.fixture
def job_store(db):
    return JobStore(db, lease_sec=5)


class TestCandidateRepository:
    """CandidateRepository 测试."""

    def test_create_candidate(self, db, candidate_repo, setup_experiment):
        """创建候选."""
        candidate = candidate_repo.create_candidate(
            experiment_id="exp1",
            task_id="task1",
            generation=1,
            artifact_hash="art1",
            search_policy_id="policy1",
        )

        assert candidate.id is not None
        assert candidate.generation == 1
        assert candidate.status == "pending"

    def test_create_with_parents(self, db, candidate_repo, setup_experiment):
        """创建有父代的候选."""
        # 创建父代
        parent = candidate_repo.create_candidate(
            experiment_id="exp1",
            task_id="task1",
            generation=1,
            artifact_hash="art1",
            search_policy_id="policy1",
        )

        # 创建子代
        child = candidate_repo.create_candidate(
            experiment_id="exp1",
            task_id="task1",
            generation=2,
            artifact_hash="art1",
            search_policy_id="policy1",
            parents=[(parent.id, "mutate")],
        )

        # 验证血缘
        parents = candidate_repo.get_parents(child.id)
        assert len(parents) == 1
        assert parents[0][0] == parent.id
        assert parents[0][1] == "mutate"

    def test_create_thought(self, db, candidate_repo, setup_experiment):
        """创建思想记录."""
        thought = candidate_repo.create_thought(
            experiment_id="exp1",
            task_id="task1",
            content="Try using dynamic programming",
            mechanism_tags=["dp", "optimization"],
            confidence=0.8,
        )

        assert thought.id is not None
        assert thought.mechanism_tags == ["dp", "optimization"]

    def test_search_state(self, db, candidate_repo, setup_experiment):
        """搜索状态更新."""
        candidate = candidate_repo.create_candidate(
            experiment_id="exp1",
            task_id="task1",
            generation=1,
            artifact_hash="art1",
            search_policy_id="policy1",
        )

        # 更新搜索状态
        candidate_repo.update_search_state(
            candidate.id,
            visit_delta=1,
            value_delta=0.5,
            selection_delta=1,
        )

        state = candidate_repo.get_search_state(candidate.id)
        assert state is not None
        assert state.visit_count == 1
        assert state.value_sum == 0.5

    def test_reference_edge(self, db, candidate_repo, setup_experiment):
        """引用边."""
        c1 = candidate_repo.create_candidate(
            experiment_id="exp1",
            task_id="task1",
            generation=1,
            artifact_hash="art1",
            search_policy_id="policy1",
        )
        c2 = candidate_repo.create_candidate(
            experiment_id="exp1",
            task_id="task1",
            generation=1,
            artifact_hash="art1",
            search_policy_id="policy1",
        )

        candidate_repo.add_reference_edge(c1.id, c2.id, "memory", {"reason": "similar"})

        # 验证（通过数据库直接查询）
        row = db.fetchone(
            "SELECT * FROM candidate_reference_edge WHERE src_candidate_id = ?",
            (c1.id,),
        )
        assert row is not None
        assert row["reference_type"] == "memory"


class TestJobStore:
    """JobStore 测试."""

    def test_create_and_claim(self, db, job_store, setup_experiment):
        """创建和认领任务."""
        job = job_store.create_job(
            experiment_id="exp1",
            job_type="evaluate",
            payload={"candidate_id": "cand1"},
        )

        assert job.status == "queued"

        # 认领
        claimed = job_store.claim_job()
        assert claimed is not None
        assert claimed.id == job.id
        assert claimed.status == "running"
        assert claimed.lease_owner == job_store.worker_id

    def test_heartbeat(self, db, job_store, setup_experiment):
        """心跳续租."""
        job_store.create_job("exp1", "evaluate", {})
        claimed = job_store.claim_job()

        assert job_store.heartbeat(claimed.id)

    def test_complete_job(self, db, job_store, setup_experiment):
        """完成任务."""
        job_store.create_job("exp1", "evaluate", {})
        claimed = job_store.claim_job()

        assert job_store.complete_job(claimed.id, "result_ref_123")

        completed = job_store.get_job(claimed.id)
        assert completed.status == "completed"
        assert completed.result_ref == "result_ref_123"

    def test_fail_and_retry(self, db, job_store, setup_experiment):
        """失败重试."""
        job_store.create_job("exp1", "evaluate", {}, max_attempts=2)

        # 第一次失败
        claimed = job_store.claim_job()
        job_store.fail_job(claimed.id, "Error 1")

        # 应该回到 queued
        failed = job_store.get_job(claimed.id)
        assert failed.status == "queued"
        assert failed.attempt == 1

        # 第二次失败
        claimed = job_store.claim_job()
        job_store.fail_job(claimed.id, "Error 2")

        # 应该变成 failed（达到最大重试次数）
        failed = job_store.get_job(claimed.id)
        assert failed.status == "failed"

    def test_recover_orphan_jobs(self, db, job_store, setup_experiment):
        """恢复孤儿任务."""
        job_store.create_job("exp1", "evaluate", {})
        claimed = job_store.claim_job()

        # 模拟租约过期（手动设置过期时间）
        db.execute(
            "UPDATE job SET lease_expires_at = '2020-01-01T00:00:00' WHERE id = ?",
            (claimed.id,),
        )

        # 恢复
        recovered = job_store.recover_orphan_jobs()
        assert recovered == 1

        # 任务应该回到 queued
        recovered_job = job_store.get_job(claimed.id)
        assert recovered_job.status == "queued"


class TestScheduler:
    """Scheduler 测试."""

    def test_create_experiment(self, db, setup_experiment):
        """创建实验."""
        scheduler = Scheduler(
            db,
            experiment_id="exp1",
            evaluator_version_id="eval1",
            environment_version_id="env1",
        )

        stats = scheduler.get_stats()
        assert stats["experiment_id"] == "exp1"

    def test_submit_candidate(self, db, setup_experiment):
        """提交候选."""
        scheduler = Scheduler(
            db,
            experiment_id="exp1",
            evaluator_version_id="eval1",
            environment_version_id="env1",
        )

        candidate_id = scheduler.submit_candidate(
            task_id="task1",
            artifact_hash="art1",
            generation=1,
        )

        assert candidate_id is not None

        # 应该创建评估任务
        stats = scheduler.get_stats()
        assert stats["candidates"] == 1

    def test_elite_archive(self, db, setup_experiment):
        """精英档案."""
        scheduler = Scheduler(
            db,
            experiment_id="exp1",
            evaluator_version_id="eval1",
            environment_version_id="env1",
        )

        # 提交候选
        cand_id = scheduler.submit_candidate("task1", "art1", generation=1)

        # 创建并完成评估
        run_id = scheduler.create_evaluation_run(cand_id)
        scheduler._eval_repo.start(run_id)
        scheduler.complete_evaluation(
            run_id,
            passed=True,
            primary_score=0.95,
        )

        # 检查精英档案
        best_id, best_score = scheduler.get_best_candidate()
        assert best_id == cand_id
        assert best_score == 0.95


class TestGraphStore:
    """GraphStore 测试."""

    def test_load_subgraph(self, db, setup_experiment):
        """加载子图."""
        repo = CandidateRepository(db)
        graph_store = GraphStore(db)

        # 创建候选
        c1 = repo.create_candidate("exp1", "task1", 1, "art1", "policy1")
        c2 = repo.create_candidate(
            "exp1",
            "task1",
            2,
            "art1",
            "policy1",
            parents=[(c1.id, "mutate")],
        )

        # 加载图
        G = graph_store.load_subgraph("exp1")

        assert len(G.nodes()) == 2
        assert len(G.edges()) == 1
        assert G.has_edge(c1.id, c2.id)
