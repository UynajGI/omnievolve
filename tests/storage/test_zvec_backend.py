"""ZvecBackend 测试 — 50% → 80%+."""

from __future__ import annotations

import numpy as np
import pytest

from omnievolve.storage.vector_backend import VectorHit, VectorRecord
from omnievolve.storage.zvec_backend import ZvecBackend, create_vector_backend


class TestZvecBackendFallback:
    """zvec 未安装时回退到 NumPy."""

    def test_create_prefers_zvec(self):
        backend = create_vector_backend(prefer_zvec=True)
        assert backend is not None

    def test_create_force_numpy(self):
        backend = create_vector_backend(prefer_zvec=False)
        assert backend is not None

    def test_is_using_fallback_type(self):
        backend = create_vector_backend(prefer_zvec=True)
        # 无论是否装了 zvec，is_using_fallback 返回 bool
        assert isinstance(backend.is_using_fallback(), bool)


class TestZvecBackendCRUD:
    """CRUD 全链路."""

    def _make_backend(self):
        return create_vector_backend(prefer_zvec=True)

    def test_create_or_open(self):
        b = self._make_backend()
        b.create_or_open("test_crud", dimension=8)

    def test_upsert_and_query(self):
        b = self._make_backend()
        b.create_or_open("test_uq", dimension=8)
        vecs = [np.random.randn(8).tolist() for _ in range(5)]
        records = [
            VectorRecord(id=f"v{i}", vector=v, metadata={"idx": i})
            for i, v in enumerate(vecs)
        ]
        b.upsert("test_uq", records)
        hits = b.query("test_uq", vecs[0], top_k=3)
        assert len(hits) > 0
        assert isinstance(hits[0], VectorHit)

    def test_query_with_filter(self):
        b = self._make_backend()
        b.create_or_open("test_filter", dimension=8)
        vecs = [np.random.randn(8).tolist() for _ in range(5)]
        records = [
            VectorRecord(id=f"f{i}", vector=v, metadata={"group": "a" if i < 2 else "b"})
            for i, v in enumerate(vecs)
        ]
        b.upsert("test_filter", records)
        hits = b.query("test_filter", vecs[0], top_k=5, filters={"group": "a"})
        assert len(hits) > 0
        for h in hits:
            assert h.metadata.get("group") == "a"

    def test_delete(self):
        b = self._make_backend()
        b.create_or_open("test_del", dimension=8)
        vecs = [np.random.randn(8).tolist() for _ in range(3)]
        records = [VectorRecord(id=f"d{i}", vector=v, metadata={}) for i, v in enumerate(vecs)]
        b.upsert("test_del", records)
        b.delete("test_del", ["d0", "d1"])
        hits = b.query("test_del", vecs[0], top_k=5)
        ids = [h.id for h in hits]
        assert "d0" not in ids
        assert "d1" not in ids

    def test_healthcheck(self):
        b = self._make_backend()
        b.create_or_open("test_hc", dimension=4)
        result = b.healthcheck("test_hc")
        assert isinstance(result, dict)
        assert "status" in result

    def test_healthcheck_nonexistent_collection(self):
        b = self._make_backend()
        result = b.healthcheck("nonexistent")
        assert isinstance(result, dict)

    def test_query_nonexistent_collection(self):
        b = self._make_backend()
        hits = b.query("nonexistent", [0.1] * 4, top_k=3)
        assert isinstance(hits, list)

    def test_delete_nonexistent_collection(self):
        b = self._make_backend()
        b.delete("nonexistent", ["x"])

    def test_upsert_empty(self):
        b = self._make_backend()
        b.create_or_open("test_empty", dimension=4)
        b.upsert("test_empty", [])
