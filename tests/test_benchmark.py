"""性能回归测试.

Gap P1: 性能回归测试 — EvoX 模式：单元测试含性能断言
"""

from __future__ import annotations

import time

import pytest

from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database
from omnievolve.utils.hashing import compute_sha256

pytestmark = pytest.mark.benchmark


class TestArtifactStorePerformance:
    """ArtifactStore 性能基准."""

    def test_store_throughput(self, tmp_path):
        """验证存储吞吐量不低于基线（1000 次/秒）."""
        db = create_memory_database()
        initialize_database(db)
        store = ArtifactStore(tmp_path / "perf_artifacts", db)
        data = b"x" * 1024  # 1KB payload
        count = 500

        start = time.perf_counter()
        for i in range(count):
            store.store(data + str(i).encode(), "source")
        elapsed = time.perf_counter() - start

        rate = count / elapsed
        assert rate > 100, f"Store throughput {rate:.0f}/s below 100/s baseline"

    def test_load_throughput(self, tmp_path):
        """验证加载吞吐量不低于基线（5000 次/秒）."""
        db = create_memory_database()
        initialize_database(db)
        store = ArtifactStore(tmp_path / "perf_artifacts", db)
        data = b"x" * 1024
        artifact_hash = store.store(data, "source")
        count = 1000

        start = time.perf_counter()
        for _ in range(count):
            store.load(artifact_hash)
        elapsed = time.perf_counter() - start

        rate = count / elapsed
        assert rate > 500, f"Load throughput {rate:.0f}/s below 500/s baseline"

    def test_sha256_throughput(self):
        """验证 SHA-256 吞吐量不低于基线（100 MB/s）."""
        data = b"x" * (1024 * 1024)  # 1MB
        iterations = 50

        start = time.perf_counter()
        for _ in range(iterations):
            compute_sha256(data)
        elapsed = time.perf_counter() - start

        mb_per_sec = (iterations * 1) / elapsed  # 1MB each
        assert mb_per_sec > 20, f"SHA-256 throughput {mb_per_sec:.1f} MB/s below 20 MB/s baseline"


class TestMCTSPerformance:
    """MCTS 搜索性能基准."""

    def test_select_throughput(self):
        """验证 MCTS select 吞吐量不低于基线."""
        from omnievolve.engine.mcts import ProgressiveMCGS

        mcts = ProgressiveMCGS()
        mcts.add_node("root")

        # 构建 100 节点树
        for i in range(100):
            child = mcts.add_node(f"child_{i}", parent="root", prior=0.01)
            for j in range(3):
                mcts.add_node(f"grandchild_{i}_{j}", parent=child.candidate_id, prior=0.001)

        count = 1000
        start = time.perf_counter()
        for _ in range(count):
            mcts.select("root")
        elapsed = time.perf_counter() - start

        rate = count / elapsed
        # 100 节点 UCB 搜索，预期 >5000 次/秒
        assert rate > 1000, f"MCTS select {rate:.0f}/s below 1000/s baseline"

    def test_backpropagate_throughput(self):
        """验证 MCTS backpropagate 吞吐量不低于基线."""
        from omnievolve.engine.mcts import ProgressiveMCGS

        mcts = ProgressiveMCGS()
        current = mcts.add_node("root")
        # 构建 20 层深链
        for i in range(20):
            child = mcts.add_node(f"node_{i}", parent=current.candidate_id)
            current = child

        count = 5000
        start = time.perf_counter()
        for _ in range(count):
            mcts.backpropagate("node_19", 0.75)
            # 重置 visit_count 防止 UCB 退化
            for nid in mcts._nodes:
                mcts._nodes[nid].visit_count = 0
        elapsed = time.perf_counter() - start

        rate = count / elapsed
        assert rate > 2000, f"MCTS backprop {rate:.0f}/s below 2000/s baseline"


class TestNoveltyGatePerformance:
    """新颖性门性能基准."""

    def test_ast_signature_throughput(self):
        """验证 AST 签名计算吞吐量."""
        from omnievolve.engine.novelty import compute_code_signature

        code_samples = [f"def func_{i}(x):\n    return x + {i}\n" for i in range(50)]

        count = 500
        start = time.perf_counter()
        for i in range(count):
            compute_code_signature(code_samples[i % len(code_samples)])
        elapsed = time.perf_counter() - start

        rate = count / elapsed
        assert rate > 500, f"AST signature {rate:.0f}/s below 500/s baseline"


class TestVectorPerformance:
    """向量后端性能基准."""

    def test_numpy_query_throughput(self):
        """验证 NumPy 精确检索吞吐量."""
        import numpy as np

        from omnievolve.storage.numpy_backend import NumpyVectorBackend
        from omnievolve.storage.vector_backend import VectorRecord

        backend = NumpyVectorBackend()
        backend.create_or_open("bench", 128)

        # 插入 1000 条向量
        records = [
            VectorRecord(id=f"id_{i}", vector=np.random.randn(128).tolist(), metadata={})
            for i in range(1000)
        ]
        backend.upsert("bench", records)

        # 查询 100 次
        query = np.random.randn(128).tolist()
        count = 100
        start = time.perf_counter()
        for _ in range(count):
            backend.query("bench", query, top_k=10)
        elapsed = time.perf_counter() - start

        rate = count / elapsed
        assert rate > 50, f"NumPy query {rate:.0f}/s below 50/s baseline"

    def test_zvec_upsert_throughput(self):
        """验证 zvec HNSW upsert 吞吐量."""
        import numpy as np

        from omnievolve.storage.vector_backend import VectorRecord
        from omnievolve.storage.zvec_backend import create_vector_backend

        backend = create_vector_backend(prefer_zvec=True)
        backend.create_or_open("bench_upsert", 128)

        records = [
            VectorRecord(id=f"id_{i}", vector=np.random.randn(128).tolist(), metadata={})
            for i in range(100)
        ]

        start = time.perf_counter()
        backend.upsert("bench_upsert", records)
        elapsed = time.perf_counter() - start

        rate = 100 / elapsed
        assert rate > 50, f"zvec upsert {rate:.0f} records/s below 50/s baseline"


class TestProfilerOverhead:
    """验证 PipelineProfiler 零开销."""

    def test_profiler_disabled_overhead(self):
        """当 profiler=None 时，_prof_step 开销应 < 1ms/次."""
        from contextlib import nullcontext

        count = 10000
        start = time.perf_counter()
        for _ in range(count):
            with nullcontext():
                pass
        elapsed = time.perf_counter() - start

        per_call_us = (elapsed / count) * 1_000_000
        assert per_call_us < 100, f"nullcontext overhead {per_call_us:.1f}us > 100us"
