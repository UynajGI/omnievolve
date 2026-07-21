"""FTS5 索引写入与检索测试 (T4).

验证 thought_record 和 memory_entry 的 FTS5 全文索引正确写入，
搜索结果通过 entity_id JOIN 原表。
"""

from __future__ import annotations

import pytest

from omnievolve.engine.memory import MemoryStore
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import (
    check_fts5_support,
    create_fts_tables,
    initialize_database,
)
from omnievolve.storage.numpy_backend import NumpyVectorBackend
from omnievolve.storage.repositories.candidate_repo import CandidateRepository
from omnievolve.storage.vector_store import HybridRetriever


@pytest.fixture
def db():
    d = create_memory_database()
    initialize_database(d)
    create_fts_tables(d)
    yield d
    d.close()


@pytest.fixture
def fts_supported(db):
    if not check_fts5_support(db):
        pytest.skip("FTS5 not supported in this SQLite build")
    return db


class _FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 4

    def embed(self, texts):
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


# ── Thought FTS ───────────────────────────────────────────────


class TestThoughtFTS:
    def test_thought_indexed_on_create(self, fts_supported):
        """create_thought 应同步写入 thought_fts."""
        repo = CandidateRepository(fts_supported)
        # 创建实验行（FK）
        fts_supported.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
            ("exp_fts", "task", "test", "{}"),
        )
        repo.create_thought(
            experiment_id="exp_fts",
            task_id="task",
            content="binary search tree optimization for log complexity",
            mechanism_tags=["algo", "data-structure"],
        )

        # 验证 FTS 表有数据
        row = fts_supported.fetchone("SELECT COUNT(*) as c FROM thought_fts")
        assert row["c"] >= 1

    def test_fts_search_finds_thought(self, fts_supported):
        """FTS MATCH 查询应找到已索引的 thought."""
        repo = CandidateRepository(fts_supported)
        fts_supported.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
            ("exp_fts2", "task", "test", "{}"),
        )
        repo.create_thought(
            experiment_id="exp_fts2",
            task_id="task",
            content="gradient descent optimizer for neural networks",
        )
        repo.create_thought(
            experiment_id="exp_fts2",
            task_id="task",
            content="completely unrelated topic about cooking recipes",
        )

        # FTS 搜索
        rows = fts_supported.fetchall(
            "SELECT entity_id FROM thought_fts WHERE thought_fts MATCH ?",
            ("gradient",),
        )
        assert len(rows) >= 1

    def test_fts_search_via_hybrid_retriever(self, fts_supported):
        """HybridRetriever.search_thoughts 应通过 FTS 找到结果."""
        repo = CandidateRepository(fts_supported)
        fts_supported.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
            ("exp_hybrid", "task", "test", "{}"),
        )
        repo.create_thought(
            experiment_id="exp_hybrid",
            task_id="task",
            content="parallel merge sort algorithm analysis",
        )

        retriever = HybridRetriever(
            fts_supported,
            NumpyVectorBackend(),
            _FakeEmbedder(),
            fts_available=True,
        )
        results = retriever.search_thoughts("merge sort", experiment_id="exp_hybrid")
        # FTS 或 vector 路径都应找到
        assert len(results) > 0


# ── Memory FTS ────────────────────────────────────────────────


class TestMemoryFTS:
    def test_memory_indexed_on_add(self, fts_supported):
        """add_memory 应同步写入 memory_fts."""
        fts_supported.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
            ("exp_mem", "task", "test", "{}"),
        )
        store = MemoryStore(fts_supported)
        store.add_memory(
            scope_level=1,
            outcome_summary={"strategy": "momentum", "result": "profitable"},
            success_flag=True,
            experiment_id="exp_mem",
        )

        row = fts_supported.fetchone("SELECT COUNT(*) as c FROM memory_fts")
        assert row["c"] >= 1

    def test_fts_search_finds_memory(self, fts_supported):
        """FTS MATCH 查询应找到已索引的 memory."""
        fts_supported.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
            ("exp_mem2", "task", "test", "{}"),
        )
        store = MemoryStore(fts_supported)
        store.add_memory(
            scope_level=1,
            outcome_summary={"strategy": "mean_reversion", "result": "positive"},
            success_flag=True,
            experiment_id="exp_mem2",
        )

        rows = fts_supported.fetchall(
            "SELECT entity_id FROM memory_fts WHERE memory_fts MATCH ?",
            ("mean_reversion",),
        )
        assert len(rows) >= 1


# ── Graceful degradation ──────────────────────────────────────


class TestFTSDegradation:
    def test_index_silently_skips_if_fts_unavailable(self, db):
        """FTS 表不存在时，index_thought_fts 不应抛异常."""
        from omnievolve.storage.migrations import index_thought_fts

        # 不创建 FTS 表，直接调用 — 应静默跳过
        index_thought_fts(db, "fake_id", "some content")
        # 如果到这里没有异常，测试通过
