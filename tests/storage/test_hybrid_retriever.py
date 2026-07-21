"""HybridRetriever + NumpyVectorBackend 测试 (H5 + C3).

HybridRetriever 之前 0% 覆盖 — 验证 RRF 融合、FTS 回退、新颖性检查。
NumpyVectorBackend — 验证矩阵化查询和 filter。
"""

from __future__ import annotations

import pytest

from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.numpy_backend import NumpyVectorBackend
from omnievolve.storage.vector_backend import VectorRecord
from omnievolve.storage.vector_store import HybridRetriever


class _FakeEmbedder:
    """确定性 embedder — 文本 hash 映射到固定维度向量."""

    def __init__(self, dim: int = 8) -> None:
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib

        results = []
        for text in texts:
            h = hashlib.md5(text.encode()).digest()
            vec = [(h[i % len(h)] / 255.0 - 0.5) * 2 for i in range(self._dim)]
            norm = sum(v * v for v in vec) ** 0.5
            if norm > 0:
                vec = [v / norm for v in vec]
            results.append(vec)
        return results


@pytest.fixture
def db():
    d = create_memory_database()
    initialize_database(d)
    yield d
    d.close()


@pytest.fixture
def backend():
    return NumpyVectorBackend()


@pytest.fixture
def embedder():
    return _FakeEmbedder(dim=8)


# ── NumpyVectorBackend 测试 ─────────────────────────────────


class TestNumpyBackend:
    def test_create_and_query(self, backend):
        backend.create_or_open("test", 4)
        backend.upsert(
            "test",
            [
                VectorRecord(id="a", vector=[1.0, 0.0, 0.0, 0.0], metadata={}),
                VectorRecord(id="b", vector=[0.0, 1.0, 0.0, 0.0], metadata={}),
                VectorRecord(id="c", vector=[0.9, 0.1, 0.0, 0.0], metadata={}),
            ],
        )

        hits = backend.query("test", [1.0, 0.0, 0.0, 0.0], top_k=2)
        assert len(hits) == 2
        assert hits[0].id == "a"
        assert hits[0].similarity > 0.99

    def test_filter(self, backend):
        backend.create_or_open("test", 4)
        backend.upsert(
            "test",
            [
                VectorRecord(id="a", vector=[1, 0, 0, 0], metadata={"type": "x"}),
                VectorRecord(id="b", vector=[1, 0, 0, 0], metadata={"type": "y"}),
            ],
        )

        hits = backend.query("test", [1, 0, 0, 0], top_k=5, filters={"type": "x"})
        assert len(hits) == 1
        assert hits[0].id == "a"

    def test_filter_no_match(self, backend):
        backend.create_or_open("test", 4)
        backend.upsert(
            "test",
            [
                VectorRecord(id="a", vector=[1, 0, 0, 0], metadata={"type": "x"}),
            ],
        )
        hits = backend.query("test", [1, 0, 0, 0], top_k=5, filters={"type": "z"})
        assert hits == []

    def test_zero_norm_vector(self, backend):
        """零向量不崩溃，similarity=0."""
        backend.create_or_open("test", 4)
        backend.upsert(
            "test",
            [
                VectorRecord(id="z", vector=[0, 0, 0, 0], metadata={}),
                VectorRecord(id="a", vector=[1, 0, 0, 0], metadata={}),
            ],
        )
        hits = backend.query("test", [1, 0, 0, 0], top_k=2)
        assert len(hits) == 2
        # 零向量的 similarity 应为 0
        zero_hit = next(h for h in hits if h.id == "z")
        assert zero_hit.similarity == 0.0

    def test_empty_collection(self, backend):
        backend.create_or_open("empty", 4)
        hits = backend.query("empty", [1, 0, 0, 0], top_k=5)
        assert hits == []

    def test_nonexistent_collection(self, backend):
        hits = backend.query("nonexistent", [1, 0, 0, 0], top_k=5)
        assert hits == []

    def test_delete(self, backend):
        backend.create_or_open("test", 4)
        backend.upsert("test", [VectorRecord(id="a", vector=[1, 0, 0, 0], metadata={})])
        backend.delete("test", ["a"])
        hits = backend.query("test", [1, 0, 0, 0], top_k=5)
        assert hits == []

    def test_count(self, backend):
        backend.create_or_open("test", 4)
        backend.upsert(
            "test",
            [
                VectorRecord(id="a", vector=[1, 0, 0, 0], metadata={}),
                VectorRecord(id="b", vector=[0, 1, 0, 0], metadata={}),
            ],
        )
        assert backend.count("test") == 2

    def test_healthcheck(self, backend):
        backend.create_or_open("test", 4)
        result = backend.healthcheck("test")
        assert result["status"] == "healthy"
        assert result["count"] == 0


# ── HybridRetriever 测试 ─────────────────────────────────────


class TestRRFFusion:
    """RRF 融合算法正确性."""

    def test_rrf_basic(self, db, backend, embedder):
        retriever = HybridRetriever(db, backend, embedder, fts_available=False)

        # 两列结果，有重叠
        results_a = [{"id": "x", "content": "a"}, {"id": "y", "content": "b"}]
        results_b = [{"id": "y", "content": "b"}, {"id": "z", "content": "c"}]

        fused = retriever._rrf_fuse(results_a, results_b)

        # y 出现在两个列表中，RRF 分数应最高
        assert fused[0]["id"] == "y"
        assert fused[0]["fused_score"] > fused[1]["fused_score"]

    def test_rrf_empty(self, db, backend, embedder):
        retriever = HybridRetriever(db, backend, embedder, fts_available=False)
        fused = retriever._rrf_fuse([], [])
        assert fused == []

    def test_rrf_single_list(self, db, backend, embedder):
        retriever = HybridRetriever(db, backend, embedder, fts_available=False)
        results = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        fused = retriever._rrf_fuse(results, [])
        assert len(fused) == 3
        assert fused[0]["id"] == "a"  # rank 1 → highest RRF


class TestNoveltyCheck:
    """新颖性检查."""

    def test_novel_when_empty(self, db, backend, embedder):
        retriever = HybridRetriever(db, backend, embedder, fts_available=False)
        is_novel, sim = retriever.check_novelty("test text", threshold=0.9)
        assert is_novel is True
        assert sim == 0.0

    def test_novel_with_dissimilar(self, db, backend, embedder):
        retriever = HybridRetriever(db, backend, embedder, fts_available=False)
        backend.create_or_open("candidate_default", 8)
        backend.upsert(
            "candidate_default",
            [
                VectorRecord(id="old", vector=embedder.embed(["unique text one"])[0], metadata={}),
            ],
        )

        is_novel, sim = retriever.check_novelty("completely different text", threshold=0.5)
        assert is_novel is True
        assert sim < 0.5

    def test_not_novel_when_similar(self, db, backend, embedder):
        retriever = HybridRetriever(db, backend, embedder, fts_available=False)
        backend.create_or_open("candidate_default", 8)
        text = "hello world"
        vec = embedder.embed([text])[0]
        backend.upsert(
            "candidate_default",
            [
                VectorRecord(id="dup", vector=vec, metadata={}),
            ],
        )

        is_novel, sim = retriever.check_novelty(text, threshold=0.5)
        assert is_novel is False
        assert sim > 0.5
