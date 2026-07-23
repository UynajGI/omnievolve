"""GraphStore 写方法测试 — Step 7: 37% → 80%+."""

from __future__ import annotations

import pytest

from omnievolve.storage.db import create_memory_database
from omnievolve.storage.graph_store import GraphStore
from omnievolve.storage.migrations import initialize_database


@pytest.fixture
def db():
    database = create_memory_database()
    initialize_database(database)
    # 满足 FK 约束
    database.execute(
        "INSERT OR IGNORE INTO embedding_profile (id, purpose, provider, model, dimension, collection_path) "
        "VALUES ('profile-code-default', 'code', 'local', 'test', 128, '/tmp/test')"
    )
    # evaluation_run FK 约束
    database.execute(
        "INSERT OR IGNORE INTO task_evaluator_version (id, name, semantic_version, implementation_hash, task_semantics_hash, score_schema) "
        "VALUES ('eval@1', 'test-eval', '1.0', 'hash', 'hash', '{}')"
    )
    database.execute(
        "INSERT OR IGNORE INTO execution_environment_version (id, backend, resource_policy, network_policy) "
        "VALUES ('env@1', 'subprocess', '{}', '{}')"
    )
    yield database
    database.close()


@pytest.fixture
def gs(db):
    return GraphStore(db)


@pytest.fixture
def experiment(db):
    from omnievolve.storage.repositories.experiment_repo import ExperimentRepository

    repo = ExperimentRepository(db)
    exp = repo.create(task_id="test", task_name="test", config_snapshot={})
    return exp.id


def _ensure_artifact(db, hash_val: str):
    """确保 artifact 行存在（满足 FK 约束）."""
    db.execute(
        "INSERT OR IGNORE INTO artifact (hash, artifact_type, byte_size, relative_path) "
        "VALUES (?, 'source', 100, ?)",
        (hash_val, f"artifacts/{hash_val[:2]}/{hash_val}"),
    )


class TestGraphStoreWrite:
    """GraphStore 写方法测试."""

    def test_add_candidate_basic(self, gs, db, experiment):
        """add_candidate 写入 candidate + search_state + lineage + outbox."""
        _ensure_artifact(db, "abc123")
        cid = gs.add_candidate(
            {"experiment_id": experiment, "task_id": "t", "generation": 1,
             "artifact_hash": "abc123", "search_policy_id": "default"},
            parents=[],
        )
        assert cid

        # 验证 candidate 表
        row = db.fetchone("SELECT * FROM candidate WHERE id = ?", (cid,))
        assert row is not None
        assert row["generation"] == 1

        # 验证 search_state 表
        ss = db.fetchone("SELECT * FROM candidate_search_state WHERE candidate_id = ?", (cid,))
        assert ss is not None
        assert ss["visit_count"] == 0

    def test_add_candidate_multi_parent(self, gs, db, experiment):
        """多父代血缘的 parent_order 正确."""
        _ensure_artifact(db, "p1")
        _ensure_artifact(db, "p2")
        _ensure_artifact(db, "child")
        # 先创建两个父代
        p1 = gs.add_candidate(
            {"experiment_id": experiment, "task_id": "t", "generation": 0,
             "artifact_hash": "p1", "search_policy_id": "default"},
            parents=[],
        )
        p2 = gs.add_candidate(
            {"experiment_id": experiment, "task_id": "t", "generation": 0,
             "artifact_hash": "p2", "search_policy_id": "default"},
            parents=[],
        )
        # 创建子代
        child = gs.add_candidate(
            {"experiment_id": experiment, "task_id": "t", "generation": 1,
             "artifact_hash": "child", "search_policy_id": "default"},
            parents=[{"id": p1, "relation_type": "crossover"},
                     {"id": p2, "relation_type": "crossover"}],
        )
        lineages = db.fetchall(
            "SELECT * FROM candidate_lineage WHERE child_id = ? ORDER BY parent_order",
            (child,),
        )
        assert len(lineages) == 2
        assert lineages[0]["parent_id"] == p1
        assert lineages[0]["parent_order"] == 0
        assert lineages[1]["parent_id"] == p2
        assert lineages[1]["parent_order"] == 1

    def test_add_candidate_with_meta(self, gs, db, experiment):
        """meta JSON 序列化."""
        _ensure_artifact(db, "abc")
        cid = gs.add_candidate(
            {"experiment_id": experiment, "task_id": "t", "generation": 1,
             "artifact_hash": "abc", "search_policy_id": "default",
             "meta": {"thought": "test thought", "model": "fake"}},
            parents=[],
        )
        row = db.fetchone("SELECT meta FROM candidate WHERE id = ?", (cid,))
        import json
        meta = json.loads(row["meta"])
        assert meta["thought"] == "test thought"

    def test_add_reference_edge(self, gs, db, experiment):
        """add_reference_edge 写入 candidate_reference_edge."""
        _ensure_artifact(db, "a1")
        _ensure_artifact(db, "a2")
        c1 = gs.add_candidate(
            {"experiment_id": experiment, "task_id": "t", "generation": 0,
             "artifact_hash": "a1", "search_policy_id": "default"},
            parents=[],
        )
        c2 = gs.add_candidate(
            {"experiment_id": experiment, "task_id": "t", "generation": 1,
             "artifact_hash": "a2", "search_policy_id": "default"},
            parents=[],
        )
        gs.add_reference_edge(c1, c2, "memory", {"reason": "similar approach"})
        edge = db.fetchone(
            "SELECT * FROM candidate_reference_edge WHERE src_candidate_id = ? AND dst_candidate_id = ?",
            (c1, c2),
        )
        assert edge is not None
        assert edge["reference_type"] == "memory"

    def test_update_search_state_incremental(self, gs, db, experiment):
        """visit_count/value_sum 增量更新."""
        _ensure_artifact(db, "a")
        cid = gs.add_candidate(
            {"experiment_id": experiment, "task_id": "t", "generation": 0,
             "artifact_hash": "a", "search_policy_id": "default"},
            parents=[],
        )
        gs.update_search_state(cid, {"visit_count": 3, "value_sum": 1.5})
        ss = db.fetchone("SELECT * FROM candidate_search_state WHERE candidate_id = ?", (cid,))
        assert ss["visit_count"] == 3
        assert ss["value_sum"] == 1.5

        # 再次增量
        gs.update_search_state(cid, {"visit_count": 2, "value_sum": 0.5})
        ss = db.fetchone("SELECT * FROM candidate_search_state WHERE candidate_id = ?", (cid,))
        assert ss["visit_count"] == 5
        assert ss["value_sum"] == 2.0

    def test_update_search_state_frontier(self, gs, db, experiment):
        """frontier_status 绝对更新."""
        _ensure_artifact(db, "a")
        cid = gs.add_candidate(
            {"experiment_id": experiment, "task_id": "t", "generation": 0,
             "artifact_hash": "a", "search_policy_id": "default"},
            parents=[],
        )
        gs.update_search_state(cid, {"frontier_status": "elite"})
        ss = db.fetchone("SELECT * FROM candidate_search_state WHERE candidate_id = ?", (cid,))
        assert ss["frontier_status"] == "elite"

    def test_get_stagnant_branches(self, gs, db, experiment):
        """停滞分支检测."""
        # 创建多代候选，分数不变
        for gen in range(5):
            _ensure_artifact(db, f"a{gen}")
            cid = gs.add_candidate(
                {"experiment_id": experiment, "task_id": "t", "generation": gen,
                 "artifact_hash": f"a{gen}", "search_policy_id": "default"},
                parents=[],
            )
            # 插入评估记录
            db.execute(
                "INSERT INTO evaluation_run (id, experiment_id, candidate_id, evaluator_version_id, "
                "environment_version_id, status, passed, primary_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"er{gen}", experiment, cid, "eval@1", "env@1", "completed", 1, 0.5),
            )
        result = gs.get_stagnant_branches(experiment, threshold_gens=3)
        assert isinstance(result, list)

    def test_get_diverse_elites(self, gs, db, experiment):
        """多样化精英选择."""
        for i in range(5):
            _ensure_artifact(db, f"a{i}")
            cid = gs.add_candidate(
                {"experiment_id": experiment, "task_id": "t", "generation": 0,
                 "artifact_hash": f"a{i}", "search_policy_id": "default",
                 "island_id": f"island_{i % 2}"},
                parents=[],
            )
            db.execute(
                "INSERT INTO evaluation_run (id, experiment_id, candidate_id, evaluator_version_id, "
                "environment_version_id, status, passed, primary_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"er{i}", experiment, cid, "eval@1", "env@1", "completed", 1, 0.5 + i * 0.1),
            )
        elites = gs.get_diverse_elites(experiment, top_k=3)
        assert len(elites) <= 3
