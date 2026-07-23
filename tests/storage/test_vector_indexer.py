"""VectorIndexer 测试 — Step 8: 36% → 80%+."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.vector_indexer import VectorIndexer


@pytest.fixture
def db():
    database = create_memory_database()
    initialize_database(database)
    # 满足 FK 约束
    database.execute(
        "INSERT OR IGNORE INTO embedding_profile (id, purpose, provider, model, dimension, collection_path) "
        "VALUES ('profile-code-default', 'code', 'local', 'test', 128, '/tmp/test')"
    )
    database.execute(
        "INSERT OR IGNORE INTO artifact (hash, artifact_type, byte_size, relative_path) "
        "VALUES ('hash1', 'source', 10, 'a/ha/hash1')"
    )
    database.execute(
        "INSERT OR IGNORE INTO artifact (hash, artifact_type, byte_size, relative_path) "
        "VALUES ('hash2', 'source', 10, 'a/ha/hash2')"
    )
    database.execute(
        "INSERT OR IGNORE INTO artifact (hash, artifact_type, byte_size, relative_path) "
        "VALUES ('hash3', 'source', 10, 'a/ha/hash3')"
    )
    database.execute(
        "INSERT OR IGNORE INTO artifact (hash, artifact_type, byte_size, relative_path) "
        "VALUES ('hash4', 'source', 10, 'a/ha/hash4')"
    )
    yield database
    database.close()


@pytest.fixture
def mock_backend():
    backend = MagicMock()
    backend.create_or_open = MagicMock()
    backend.upsert = MagicMock()
    backend.delete = MagicMock()
    return backend


@pytest.fixture
def mock_embedder():
    embedder = MagicMock()
    embedder.dimension = 128
    embedder.embed = MagicMock(return_value=[[0.1] * 128])
    return embedder


@pytest.fixture
def indexer(db, mock_backend, mock_embedder):
    return VectorIndexer(db, mock_backend, mock_embedder)


class TestVectorIndexer:
    """VectorIndexer 测试."""

    def test_enqueue_and_process(self, indexer, db):
        """入队 → 处理 → 标记完成."""
        # 手动插入 pending job
        db.execute(
            "INSERT INTO vector_index_job (entity_type, entity_id, embedding_profile_id, "
            "content_hash, operation, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("candidate", "c1", "profile-code-default", "hash1", "upsert", "pending"),
        )
        # 设置 artifact_store
        mock_store = MagicMock()
        mock_store.load_text = MagicMock(return_value="def foo(): pass")
        indexer.set_artifact_store(mock_store)

        processed = indexer.process_batch()
        assert processed >= 1

        # 验证状态变为 indexed
        row = db.fetchone("SELECT status FROM vector_index_job WHERE entity_id = 'c1'")
        assert row["status"] == "indexed"

    def test_process_batch_empty(self, indexer):
        """空队列 → 返回 0."""
        processed = indexer.process_batch()
        assert processed == 0

    def test_process_batch_delete_operation(self, indexer, db):
        """delete 操作调用 backend.delete."""
        db.execute(
            "INSERT INTO vector_index_job (entity_type, entity_id, embedding_profile_id, "
            "content_hash, operation, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("candidate", "c2", "profile-code-default", "hash2", "delete", "pending"),
        )
        mock_store = MagicMock()
        indexer.set_artifact_store(mock_store)

        indexer.process_batch()
        indexer._backend.delete.assert_called()

    def test_process_batch_embedding_fallback(self, indexer, db, mock_embedder):
        """embedding 失败 → 标记 failed."""
        mock_embedder.embed.side_effect = RuntimeError("embedding failed")
        db.execute(
            "INSERT INTO vector_index_job (entity_type, entity_id, embedding_profile_id, "
            "content_hash, operation, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("candidate", "c3", "profile-code-default", "hash3", "upsert", "pending"),
        )
        mock_store = MagicMock()
        mock_store.load_text = MagicMock(return_value="code")
        indexer.set_artifact_store(mock_store)

        indexer.process_batch()
        row = db.fetchone("SELECT status FROM vector_index_job WHERE entity_id = 'c3'")
        assert row["status"] == "failed"

    def test_recover_stale_jobs(self, indexer, db):
        """过期 lease 的 indexing 任务恢复为 pending."""
        db.execute(
            "INSERT INTO vector_index_job (entity_type, entity_id, embedding_profile_id, "
            "content_hash, operation, status, lease_expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("candidate", "c4", "profile-code-default", "hash4", "upsert", "indexing", "2020-01-01T00:00:00"),
        )
        recovered = indexer.recover_stale_jobs()
        assert recovered >= 1
        row = db.fetchone("SELECT status FROM vector_index_job WHERE entity_id = 'c4'")
        assert row["status"] == "pending"

    def test_get_stats(self, indexer, db):
        """统计各状态数量."""
        for i, status in enumerate(["pending", "indexed", "failed"]):
            db.execute(
                "INSERT OR IGNORE INTO artifact (hash, artifact_type, byte_size, relative_path) "
                "VALUES (?, 'source', 10, ?)",
                (f"h{i}", f"a/h/{i}"),
            )
            db.execute(
                "INSERT INTO vector_index_job (entity_type, entity_id, embedding_profile_id, "
                "content_hash, operation, status) VALUES (?, ?, ?, ?, ?, ?)",
                ("candidate", f"s{i}", "profile-code-default", f"h{i}", "upsert", status),
            )
        stats = indexer.get_stats()
        assert stats["pending"] == 1
        assert stats["indexed"] == 1
        assert stats["failed"] == 1
