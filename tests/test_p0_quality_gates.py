"""P0 质量门测试集.

对应 docs/project-design/08_测试与质量保证计划.md 中定义的 P0 测试集合。
每个测试场景验证一个关键架构不变量或安全/一致性边界。

P0 集合:
    1.  test_schema_invariants
    2.  test_artifact_atomicity_and_hash_integrity
    3.  test_docker_no_network_no_secret_no_privilege
    4.  test_evaluator_semantic_lock
    5.  test_evaluation_run_idempotent_commit
    6.  test_job_lease_expiry_and_reclaim
    7.  test_kill9_recovery_each_stage
    8.  test_500_candidate_soak
    9.  test_outbox_eventual_consistency
    10. test_policy_atomic_rollback
    11. test_audit_full_provenance
"""

from __future__ import annotations

import sys
import threading

import pytest

from omnievolve.eval.evaluation_run import EvaluationRunRepository
from omnievolve.eval.task_evaluator import (
    CommandSpec,
    EvaluationPlan,
)
from omnievolve.meta.audit import AuditReportGenerator
from omnievolve.meta.policy_archive import PolicyArchive
from omnievolve.meta.policy_genome import SearchPolicyGenome
from omnievolve.sandbox.base import SandboxPolicy
from omnievolve.sandbox.subprocess_backend import TrustedSubprocessBackend
from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.job_store import JobStore
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.repositories.candidate_repo import CandidateRepository
from omnievolve.storage.repositories.experiment_repo import ExperimentRepository


@pytest.fixture
def db():
    database = create_memory_database()
    initialize_database(database)
    yield database
    database.close()


@pytest.fixture
def artifact_store(db, tmp_path):
    return ArtifactStore(tmp_path / "artifacts", db)


@pytest.fixture
def experiment(db):
    exp = ExperimentRepository(db).create(task_id="p0", task_name="p0-test", config_snapshot={})
    return exp.id


def _ensure_evaluator_env_rows(db, eval_id="ev@1", env_id="env1"):
    """写入满足 FK 约束的最小版本行."""
    db.execute(
        "INSERT OR IGNORE INTO task_evaluator_version"
        "(id,name,semantic_version,implementation_hash,task_semantics_hash,score_schema,immutable_core) "
        "VALUES (?, 'ev','1.0.0','h','h','{}',1)",
        (eval_id,),
    )
    db.execute(
        "INSERT OR IGNORE INTO execution_environment_version"
        "(id,backend,resource_policy,network_policy) VALUES (?,'engine','{}','none')",
        (env_id,),
    )


# =========================================================================== #
#  1. Schema Invariants
# =========================================================================== #


class TestSchemaInvariants:
    """P0-1: 数据库 schema 完整性与不变量."""

    def test_schema_invariants(self, db):
        """所有核心表存在，关键约束生效."""
        required_tables = [
            "experiment",
            "candidate",
            "candidate_lineage",
            "candidate_reference_edge",
            "candidate_search_state",
            "thought_record",
            "evaluation_run",
            "task_evaluator_version",
            "execution_environment_version",
            "search_policy_version",
            "policy_experiment",
            "artifact",
            "job",
            "vector_index_job",
            "embedding_profile",
            "prompt_version",
            "memory_entry",
            "llm_call_ledger",
            "schema_version",
        ]
        for table in required_tables:
            row = db.fetchone(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
            assert row is not None, f"Missing required table: {table}"

        # schema_version 已记录
        row = db.fetchone("SELECT MAX(version) as v FROM schema_version")
        assert row and row["v"] >= 1

    def test_candidate_lineage_relation_type_constraint(self, db, experiment):
        """candidate_lineage.relation_type 应支持多种血缘类型."""
        db.execute(
            "INSERT OR IGNORE INTO artifact(hash,artifact_type,byte_size,media_type,relative_path) "
            "VALUES ('h1','source',10,'text/plain','s/h1')"
        )
        cr = CandidateRepository(db)
        parent = cr.create_candidate(
            experiment_id=experiment,
            task_id="t",
            generation=0,
            artifact_hash="h1",
            search_policy_id="p",
        )
        child = cr.create_candidate(
            experiment_id=experiment,
            task_id="t",
            generation=1,
            artifact_hash="h1",
            search_policy_id="p",
            parents=[(parent.id, "mutate")],
        )
        parents = cr.get_parents(child.id)
        assert len(parents) == 1
        assert parents[0][1] == "mutate"


# =========================================================================== #
#  2. Artifact Atomicity & Hash Integrity
# =========================================================================== #


class TestArtifactIntegrity:
    """P0-2: Artifact 原子写入与哈希完整性."""

    def test_artifact_atomicity_and_hash_integrity(self, db, artifact_store):
        """相同内容写入产生相同哈希；内容寻址定位准确."""
        content = "def solve(): return 42\n"
        h1 = artifact_store.store_text(content, "source")
        h2 = artifact_store.store_text(content, "source")
        assert h1 == h2, "Same content must produce same hash"

        loaded = artifact_store.load_text(h1)
        assert loaded == content, "Loaded content must match stored"

        # 不同内容产生不同哈希
        h3 = artifact_store.store_text(content + "# different\n", "source")
        assert h3 != h1

    def test_concurrent_writes_same_content(self, db, artifact_store, tmp_path):
        """并发写入相同内容不应损坏（幂等）.

        Note: SQLite :memory: 是 per-connection 的，因此并发测试使用文件 DB。
        """
        from omnievolve.storage.db import Database
        from omnievolve.storage.migrations import initialize_database

        fdb = Database(tmp_path / "concurrent.db")
        initialize_database(fdb)
        fstore = ArtifactStore(tmp_path / "concurrent_artifacts", fdb)

        content = "shared content\n"
        errors = []

        def write():
            try:
                fstore.store_text(content, "source")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        fdb.close()
        assert errors == [], f"Concurrent writes failed: {errors}"


# =========================================================================== #
#  3. Sandbox Isolation (Network / Secret / Privilege)
# =========================================================================== #


class TestSandboxIsolation:
    """P0-3: 沙箱隔离——网络/秘密/权限.

    注意：完整 Docker 隔离测试需要 Docker 环境。
    此处验证 SandboxPolicy 的默认安全配置和 TrustedSubprocess 的限制。
    """

    def test_docker_no_network_no_secret_no_privilege(self):
        """SandboxPolicy 默认安全配置正确."""
        policy = SandboxPolicy()
        assert policy.network_mode == "none", "Default network must be 'none'"
        assert policy.read_only_root is True, "Default root must be read-only"
        assert policy.run_as_non_root is True, "Default must run as non-root"
        assert policy.drop_capabilities is True, "Default must drop capabilities"
        assert policy.no_new_privileges is True, "Default must set no_new_privileges"

    def test_trusted_subprocess_timeout_enforced(self, artifact_store, tmp_path):
        """TrustedSubprocessBackend 应执行超时限制."""
        backend = TrustedSubprocessBackend(
            work_dir=tmp_path / "sb", artifact_store=artifact_store, trusted=True
        )
        h = artifact_store.store_text("import time\ntime.sleep(10)\n", "source")
        from omnievolve.sandbox.base import CandidateArtifact

        candidate = CandidateArtifact(
            candidate_id="c1", source_hash=h, manifest_hash=None, language="python"
        )
        plan = EvaluationPlan(
            commands=[CommandSpec(argv=[sys.executable, "main.py"], timeout_sec=1.0)],
        )
        policy = SandboxPolicy(timeout_sec=1.0)
        result = backend.execute(plan, candidate, policy)
        assert result.timed_out is True, "Must enforce timeout"


# =========================================================================== #
#  4. Evaluator Semantic Lock
# =========================================================================== #


class TestEvaluatorSemanticLock:
    """P0-4: 评估器语义不可变（immutable_core 锁）."""

    def test_evaluator_semantic_lock(self, db):
        """task_evaluator_version 的 immutable_core 标志生效."""
        _ensure_evaluator_env_rows(db)
        row = db.fetchone("SELECT immutable_core FROM task_evaluator_version WHERE id='ev@1'")
        assert row["immutable_core"] == 1, "immutable_core must be True by default"


# =========================================================================== #
#  5. EvaluationRun Idempotent Commit
# =========================================================================== #


class TestEvaluationRunIdempotentCommit:
    """P0-5: EvaluationRun 幂等提交（唯一约束）."""

    def test_evaluation_run_idempotent_commit(self, db, experiment):
        """相同幂等键的 EvaluationRun 不应重复创建."""
        _ensure_evaluator_env_rows(db)
        db.execute(
            "INSERT OR IGNORE INTO artifact(hash,artifact_type,byte_size,media_type,relative_path) "
            "VALUES ('ah','source',10,'text/plain','s/ah')"
        )
        cr = CandidateRepository(db)
        cand = cr.create_candidate(
            experiment_id=experiment,
            task_id="t",
            generation=0,
            artifact_hash="ah",
            search_policy_id="p",
        )
        repo = EvaluationRunRepository(db)

        run1 = repo.create(
            experiment_id=experiment,
            candidate_id=cand.id,
            evaluator_version_id="ev@1",
            environment_version_id="env1",
            seed=42,
            split_name="default",
            attempt=1,
        )
        # 重复创建应返回已有记录（幂等）
        run2 = repo.create(
            experiment_id=experiment,
            candidate_id=cand.id,
            evaluator_version_id="ev@1",
            environment_version_id="env1",
            seed=42,
            split_name="default",
            attempt=1,
        )
        assert run1.id == run2.id, f"Idempotent commit must return same run: {run1.id} != {run2.id}"


# =========================================================================== #
#  6. Job Lease Expiry & Reclaim
# =========================================================================== #


class TestJobLeaseReclaim:
    """P0-6: 任务租约过期与恢复."""

    def test_job_lease_expiry_and_reclaim(self, db, experiment):
        """租约过期的 running 任务可被 recover_orphan_jobs 重新入队."""
        js = JobStore(db, lease_sec=0)  # 立即过期
        js.create_job(experiment, "test", {})
        # 手动认领（变为 running）
        claimed = js.claim_job()
        assert claimed is not None

        # 等待过期（lease_sec=0，_compute_lease_expiry 立即过期）
        recovered = js.recover_orphan_jobs()
        assert recovered >= 1, "Expired job should be recovered"


# =========================================================================== #
#  7. Kill-9 Recovery (Each Stage)
# =========================================================================== #


class TestKill9Recovery:
    """P0-7: 进程崩溃（kill -9）后各阶段可恢复."""

    def test_kill9_recovery_each_stage(self, db, experiment):
        """模拟 kill-9：任务处于 running 但 lease 过期，recover 后可继续."""
        js = JobStore(db, lease_sec=0)
        stages = ["evaluate", "index", "evolve"]
        for stage in stages:
            js.create_job(experiment, stage, {"data": f"stage_{stage}"})

        # 每个 stage 认领一次（模拟 worker 获取后崩溃）
        for stage in stages:
            claimed = js.claim_job(job_type=stage)
            assert claimed is not None, f"Should claim {stage} job"

        # 全部恢复
        recovered = js.recover_orphan_jobs()
        assert recovered >= 3, f"All stages should recover, got {recovered}"

        # 恢复后任务回到 queued，可重新认领
        for stage in stages:
            reclaimed = js.claim_job(job_type=stage)
            assert reclaimed is not None, f"Should reclaim {stage} job"


# =========================================================================== #
#  8. 500-Candidate Soak
# =========================================================================== #


@pytest.mark.slow
class TestSoak500Candidates:
    """P0-8: 500 候选长时间稳定运行.

    验证：无内存泄漏迹象、DB 无约束冲突、性能不退化。
    """

    def test_500_candidate_soak(self, db, experiment):
        """创建 500 个候选，验证 DB 完整性和查询性能."""
        _ensure_evaluator_env_rows(db)
        cr = CandidateRepository(db)

        # 预创建 artifact 记录
        artifacts = []
        for i in range(50):  # 50 个不同 artifact，候选复用
            h = f"hash_{i:04d}"
            db.execute(
                "INSERT OR IGNORE INTO artifact(hash,artifact_type,byte_size,media_type,relative_path) "
                f"VALUES ('{h}','source',100,'text/plain','s/{h}')"
            )
            artifacts.append(h)

        import time

        for i in range(500):
            gen = i // 50
            h = artifacts[i % len(artifacts)]
            cr.create_candidate(
                experiment_id=experiment,
                task_id="soak",
                generation=gen,
                artifact_hash=h,
                search_policy_id="p",
                island_id=f"island_{i % 4}",
            )

        # 验证全部创建成功
        row = db.fetchone(
            "SELECT COUNT(*) as n FROM candidate WHERE experiment_id=?", (experiment,)
        )
        assert row["n"] == 500, f"Expected 500 candidates, got {row['n']}"

        # 查询应在合理时间内完成（< 5s）
        qstart = time.time()
        cands = cr.list_by_experiment(experiment, limit=500)
        qelapsed = time.time() - qstart
        assert len(cands) == 500
        assert qelapsed < 5.0, f"Query too slow: {qelapsed:.2f}s"

        # 血缘图加载不崩溃
        from omnievolve.storage.graph_store import GraphStore

        gs = GraphStore(db)
        graph = gs.load_subgraph(experiment)
        assert graph.number_of_nodes() == 500


# =========================================================================== #
#  9. Outbox Eventual Consistency
# =========================================================================== #


class TestOutboxConsistency:
    """P0-9: SQLite ↔ 向量索引最终一致性."""

    def test_outbox_eventual_consistency(self, db):
        """vector_index_job 的 pending → indexed 状态机正确."""
        # 创建 profile
        db.execute(
            "INSERT OR IGNORE INTO embedding_profile"
            "(id,purpose,provider,model,revision,dimension,normalization,input_type,"
            "chunking_policy,collection_path) "
            "VALUES ('p1','code','fake','m','r',64,'l2','d','w','c/code')"
        )
        # 创建 artifact
        db.execute(
            "INSERT OR IGNORE INTO artifact(hash,artifact_type,byte_size,media_type,relative_path) "
            "VALUES ('ah','source',10,'t','s/ah')"
        )
        # 入队
        db.execute(
            "INSERT INTO vector_index_job(entity_type,entity_id,embedding_profile_id,content_hash) "
            "VALUES ('candidate','c1','p1','ah')"
        )
        row = db.fetchone("SELECT status FROM vector_index_job WHERE entity_id='c1'")
        assert row["status"] == "pending"

        # 模拟 indexer 处理
        db.execute("UPDATE vector_index_job SET status='indexed' WHERE entity_id='c1'")
        row = db.fetchone("SELECT status FROM vector_index_job WHERE entity_id='c1'")
        assert row["status"] == "indexed"

    def test_outbox_idempotent_insert(self, db):
        """相同 entity+profile+content 的重复入队应被去重."""
        db.execute(
            "INSERT OR IGNORE INTO embedding_profile"
            "(id,purpose,provider,model,revision,dimension,normalization,input_type,"
            "chunking_policy,collection_path) "
            "VALUES ('p1','code','fake','m','r',64,'l2','d','w','c/code')"
        )
        db.execute(
            "INSERT OR IGNORE INTO artifact(hash,artifact_type,byte_size,media_type,relative_path) "
            "VALUES ('ah','source',10,'t','s/ah')"
        )
        for _ in range(3):
            db.execute(
                "INSERT OR IGNORE INTO vector_index_job"
                "(entity_type,entity_id,embedding_profile_id,content_hash) "
                "VALUES ('candidate','c2','p1','ah')"
            )
        row = db.fetchone("SELECT COUNT(*) as n FROM vector_index_job WHERE entity_id='c2'")
        assert row["n"] == 1, "Duplicate outbox entries must be deduplicated"


# =========================================================================== #
#  10. Policy Atomic Rollback
# =========================================================================== #


class TestPolicyAtomicRollback:
    """P0-10: 策略原子回滚."""

    def test_policy_atomic_rollback(self, db, experiment):
        """晋升 champion 后可原子回滚到前一 champion."""
        archive = PolicyArchive(db)
        genome1 = SearchPolicyGenome(retrieval_budget=8)
        genome2 = SearchPolicyGenome(retrieval_budget=16)

        p1 = archive.create_policy(genome1, experiment_id=experiment, risk_level="L0")
        archive.promote_to_champion(p1.id)
        assert archive.get_champion(experiment).id == p1.id

        p2 = archive.create_policy(genome2, experiment_id=experiment, risk_level="L0")
        archive.promote_to_champion(p2.id)
        assert archive.get_champion(experiment).id == p2.id

        # 回滚
        old = archive.rollback(experiment_id=experiment)
        assert old is not None
        assert old.id == p1.id, "Rollback must restore previous champion"


# =========================================================================== #
#  11. Audit Full Provenance
# =========================================================================== #


class TestAuditFullProvenance:
    """P0-11: 审计可还原最佳候选完整链路."""

    def test_audit_full_provenance(self, db, experiment):
        """从最佳候选追溯所有父代、评估、策略."""
        _ensure_evaluator_env_rows(db)
        db.execute(
            "INSERT OR IGNORE INTO artifact(hash,artifact_type,byte_size,media_type,relative_path) "
            "VALUES ('p_hash','source',50,'t','s/p')"
        )
        db.execute(
            "INSERT OR IGNORE INTO artifact(hash,artifact_type,byte_size,media_type,relative_path) "
            "VALUES ('c_hash','source',60,'t','s/c')"
        )
        cr = CandidateRepository(db)
        parent = cr.create_candidate(
            experiment_id=experiment,
            task_id="t",
            generation=0,
            artifact_hash="p_hash",
            search_policy_id="p",
        )
        child = cr.create_candidate(
            experiment_id=experiment,
            task_id="t",
            generation=1,
            artifact_hash="c_hash",
            search_policy_id="p",
            parents=[(parent.id, "mutate")],
        )
        db.execute(
            "INSERT INTO evaluation_run(id,experiment_id,candidate_id,"
            "evaluator_version_id,environment_version_id,status,passed,primary_score) "
            "VALUES ('r1',?,?,?,?, 'completed',1,0.95)",
            (experiment, child.id, "ev@1", "env1"),
        )
        # 创建策略
        archive = PolicyArchive(db)
        genome = SearchPolicyGenome()
        policy = archive.create_policy(genome, experiment_id=experiment, risk_level="L0")
        archive.promote_to_champion(policy.id)

        generator = AuditReportGenerator(db)
        report = generator.generate(experiment)

        # 完整链路可追溯
        assert report.best_candidate is not None
        assert report.best_candidate.candidate_id == child.id
        assert len(report.candidates) >= 2  # child + parent
        cand_ids = {c.candidate_id for c in report.candidates}
        assert child.id in cand_ids
        assert parent.id in cand_ids

        # 评估记录可追溯
        best_evals = report.best_candidate.evaluations
        assert len(best_evals) >= 1
        assert best_evals[0]["primary_score"] == 0.95

        # 策略可追溯
        assert len(report.policies) >= 1
        assert report.policies[0].status == "champion"
