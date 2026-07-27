"""VectorStore facade 测试 — 47% → 80%+."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.vector_backend import VectorHit
from omnievolve.storage.vector_store import VectorStore


@pytest.fixture
def mock_backend():
    backend = MagicMock()
    backend.create_or_open = MagicMock()
    backend.upsert = MagicMock()
    backend.query = MagicMock(return_value=[])
    backend.delete = MagicMock()
    backend.healthcheck = MagicMock(return_value={"status": "healthy"})
    return backend


@pytest.fixture
def mock_embedder():
    embedder = MagicMock()
    embedder.dimension = 128
    embedder.embed = MagicMock(return_value=[[0.1] * 128])
    return embedder


@pytest.fixture
def db():
    database = create_memory_database()
    initialize_database(database)
    yield database
    database.close()


@pytest.fixture
def store(mock_backend, mock_embedder, db):
    return VectorStore(mock_backend, mock_embedder, db)


class TestSemanticCandidates:
    """semantic_candidates 测试."""

    def test_basic_query(self, store, mock_backend, mock_embedder):
        mock_backend.query.return_value = [
            VectorHit(id="c1", similarity=0.9, metadata={"gen": 1}),
            VectorHit(id="c2", similarity=0.8, metadata={"gen": 2}),
        ]
        results = store.semantic_candidates("test query")
        assert len(results) == 2
        assert results[0].id == "c1"
        mock_embedder.embed.assert_called_once()

    def test_with_scope_filter(self, store, mock_backend):
        mock_backend.query.return_value = []
        store.semantic_candidates("test", scope={"island": "island_0"})
        # 确保 filters 被传递
        call_args = mock_backend.query.call_args
        assert call_args.kwargs.get("filters") == {"island": "island_0"}

    def test_embedder_failure_returns_empty(self, store, mock_embedder):
        mock_embedder.embed.side_effect = RuntimeError("model down")
        results = store.semantic_candidates("test")
        assert results == []


class TestFindDiverseHighScorers:
    """find_diverse_high_scorers 测试."""

    def test_no_db_returns_empty(self, mock_backend, mock_embedder):
        store = VectorStore(mock_backend, mock_embedder, None)
        result = store.find_diverse_high_scorers("exp1")
        assert result == []

    def test_db_query_returns_candidates(self, store, db):
        # 准备 FK 约束 + 测试数据
        db.execute(
            "INSERT OR IGNORE INTO task_evaluator_version "
            "(id, name, semantic_version, implementation_hash, task_semantics_hash, score_schema) "
            "VALUES ('eval@1', 'test', '1.0', 'h', 'h', '{}')"
        )
        db.execute(
            "INSERT OR IGNORE INTO execution_environment_version "
            "(id, backend, resource_policy, network_policy) "
            "VALUES ('env@1', 'subprocess', '{}', '{}')"
        )
        db.execute(
            "INSERT OR IGNORE INTO embedding_profile "
            "(id, purpose, provider, model, dimension, collection_path) "
            "VALUES ('profile-code-default', 'code', 'local', 'test', 128, '/tmp/test')"
        )
        db.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES ('e1', 't', 't', '{}')"
        )
        db.execute(
            "INSERT OR IGNORE INTO artifact (hash, artifact_type, byte_size, relative_path) "
            "VALUES ('h0', 'source', 10, 'a/h/0')"
        )
        db.execute(
            "INSERT OR IGNORE INTO search_policy_version "
            "(id, experiment_id, version, genome, risk_level, status, artifact_hash) "
            "VALUES ('p1', 'e1', 1, '{}', 'L0', 'champion', 'h0')"
        )
        for i in range(3):
            db.execute(
                "INSERT OR IGNORE INTO artifact (hash, artifact_type, byte_size, relative_path) "
                f"VALUES ('h{i}', 'source', 10, 'a/h/{i}')"
            )
            db.execute(
                "INSERT INTO candidate (id, experiment_id, task_id, generation, artifact_hash, "
                "thought_id, diff_artifact_hash, manifest_hash, status, search_policy_id, meta) "
                f"VALUES ('c{i}', 'e1', 't', 1, 'h{i}', NULL, NULL, NULL, 'evaluated', 'p1', '{{}}')"
            )
            db.execute(
                "INSERT INTO evaluation_run (id, experiment_id, candidate_id, "
                "evaluator_version_id, environment_version_id, status, passed, primary_score) "
                f"VALUES ('er{i}', 'e1', 'c{i}', 'eval@1', 'env@1', 'completed', 1, {0.5 + i * 0.1})"
            )

        result = store.find_diverse_high_scorers("e1", top_k=2)
        assert len(result) <= 2
        # 最高分应被包含
        assert "c2" in result


class TestRagRetrieve:
    """rag_retrieve 测试."""

    def test_basic_vector_search(self, store, mock_backend):
        mock_backend.query.return_value = [
            VectorHit(id="t1", similarity=0.9, metadata={"scope": "experiment"}),
        ]
        results = store.rag_retrieve("test query")
        assert isinstance(results, list)
        # 应返回 vector 结果
        assert len(results) > 0
        assert results[0]["source"] in ("vector", "fts")

    def test_dedup(self, store, mock_backend):
        """同一 id 在多个集合出现时去重."""
        mock_backend.query.return_value = [
            VectorHit(id="x1", similarity=0.9, metadata={}),
        ]
        results = store.rag_retrieve("test", top_k=5)
        # x1 在 thought_default 和 candidate_default 两个集合查到，去重后只出现一次
        ids = [r["id"] for r in results]
        assert ids.count("x1") <= 1

    def test_scope_weights_applied(self, store, mock_backend):
        mock_backend.query.return_value = [
            VectorHit(id="t1", similarity=1.0, metadata={"scope": "experiment"}),
        ]
        results = store.rag_retrieve("test", scope_weights={"experiment": 0.5})
        # 权重应影响最终分数
        assert any(r["score"] <= 0.5 for r in results if r["source"] == "vector")

    def test_embedder_failure_returns_empty_or_fts(self, store, mock_embedder):
        mock_embedder.embed.side_effect = RuntimeError("down")
        results = store.rag_retrieve("test")
        # vector 失败后不崩溃，返回空或 FTS 结果
        assert isinstance(results, list)


class TestCheckNovelty:
    """check_novelty 测试."""

    def test_novel_no_hits(self, store, mock_backend):
        mock_backend.query.return_value = []
        is_novel, max_sim = store.check_novelty("test text")
        assert is_novel is True
        assert max_sim == 0.0

    def test_not_novel_high_similarity(self, store, mock_backend):
        mock_backend.query.return_value = [
            VectorHit(id="x1", similarity=0.99, metadata={}),
        ]
        is_novel, max_sim = store.check_novelty("duplicate text", threshold=0.9)
        assert is_novel is False
        assert max_sim >= 0.9

    def test_novel_below_threshold(self, store, mock_backend):
        mock_backend.query.return_value = [
            VectorHit(id="x1", similarity=0.5, metadata={}),
        ]
        is_novel, max_sim = store.check_novelty("unique text", threshold=0.92)
        assert is_novel is True
        assert max_sim == 0.5

    def test_backend_failure_defaults_novel(self, store, mock_backend):
        mock_backend.query.side_effect = RuntimeError("zvec down")
        is_novel, max_sim = store.check_novelty("test")
        assert is_novel is True
        assert max_sim == 0.0
