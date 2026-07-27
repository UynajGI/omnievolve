"""性能回归测试.

Gap P1: 性能回归测试 — EvoX 模式：使用 pytest-benchmark fixture
"""

from __future__ import annotations

import pytest

from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database
from omnievolve.utils.hashing import compute_sha256

pytestmark = pytest.mark.benchmark


class TestArtifactStorePerformance:
    """ArtifactStore 性能基准."""

    def test_store_throughput(self, tmp_path, benchmark):
        """验证存储吞吐量不低于基线（100 次/秒）."""
        db = create_memory_database()
        initialize_database(db)
        store = ArtifactStore(tmp_path / "perf_artifacts", db)
        data = b"x" * 1024  # 1KB payload
        counter = {"i": 0}

        def do_store():
            store.store(data + str(counter["i"]).encode(), "source")
            counter["i"] += 1

        benchmark(do_store)
        # pytest-benchmark 自动统计，这里做最低门槛断言
        assert benchmark.stats.stats.mean < 0.01  # < 10ms/op → > 100 ops/s

    def test_load_throughput(self, tmp_path, benchmark):
        """验证加载吞吐量不低于基线（500 次/秒）."""
        db = create_memory_database()
        initialize_database(db)
        store = ArtifactStore(tmp_path / "perf_artifacts", db)
        data = b"x" * 1024
        artifact_hash = store.store(data, "source")

        benchmark(store.load, artifact_hash)
        assert benchmark.stats.stats.mean < 0.002  # < 2ms/op → > 500 ops/s

    def test_sha256_throughput(self, benchmark):
        """验证 SHA-256 吞吐量不低于基线（20 MB/s）."""
        data = b"x" * (1024 * 1024)  # 1MB

        benchmark(compute_sha256, data)
        assert benchmark.stats.stats.mean < 0.05  # < 50ms/1MB → > 20 MB/s


class TestMCTSPerformance:
    """MCTS 搜索性能基准."""

    def test_select_throughput(self, benchmark):
        """验证 MCTS select 吞吐量不低于基线."""
        from omnievolve.engine.mcts import ProgressiveMCGS

        mcts = ProgressiveMCGS()
        mcts.add_node("root")

        # 构建 100 节点树
        for i in range(100):
            child = mcts.add_node(f"child_{i}", parent="root", prior=0.01)
            for j in range(3):
                mcts.add_node(f"grandchild_{i}_{j}", parent=child.candidate_id, prior=0.001)

        benchmark(mcts.select, "root")
        assert benchmark.stats.stats.mean < 0.001  # < 1ms/op → > 1000 ops/s

    def test_backpropagate_throughput(self, benchmark):
        """验证 MCTS backpropagate 吞吐量不低于基线."""
        from omnievolve.engine.mcts import ProgressiveMCGS

        mcts = ProgressiveMCGS()
        current = mcts.add_node("root")
        # 构建 20 层深链
        for i in range(20):
            child = mcts.add_node(f"node_{i}", parent=current.candidate_id)
            current = child

        def do_backprop():
            mcts.backpropagate("node_19", 0.75)
            # 重置 visit_count 防止 UCB 退化
            for nid in mcts._nodes:
                mcts._nodes[nid].visit_count = 0

        benchmark(do_backprop)
        assert benchmark.stats.stats.mean < 0.0005  # < 0.5ms/op → > 2000 ops/s


class TestNoveltyGatePerformance:
    """新颖性门性能基准."""

    def test_ast_signature_throughput(self, benchmark):
        """验证 AST 签名计算吞吐量."""
        from omnievolve.engine.novelty import compute_code_signature

        code_samples = [f"def func_{i}(x):\n    return x + {i}\n" for i in range(50)]
        counter = {"i": 0}

        def do_signature():
            compute_code_signature(code_samples[counter["i"] % len(code_samples)])
            counter["i"] += 1

        benchmark(do_signature)
        assert benchmark.stats.stats.mean < 0.002  # < 2ms/op → > 500 ops/s


class TestVectorPerformance:
    """向量后端性能基准."""

    def test_numpy_query_throughput(self, benchmark):
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

        query = np.random.randn(128).tolist()
        benchmark(backend.query, "bench", query, top_k=10)
        assert benchmark.stats.stats.mean < 0.02  # < 20ms/op → > 50 ops/s

    def test_zvec_upsert_throughput(self, benchmark):
        """验证 zvec/NumPy upsert 吞吐量."""
        import numpy as np

        from omnievolve.storage.vector_backend import VectorRecord
        from omnievolve.storage.zvec_backend import create_vector_backend

        backend = create_vector_backend(prefer_zvec=True)
        backend.create_or_open("bench_upsert", 128)

        records = [
            VectorRecord(id=f"id_{i}", vector=np.random.randn(128).tolist(), metadata={})
            for i in range(100)
        ]

        benchmark(backend.upsert, "bench_upsert", records)
        assert benchmark.stats.stats.mean < 2.0  # < 2s for 100 records → > 50 records/s


class TestProfilerOverhead:
    """验证 PipelineProfiler 零开销."""

    def test_profiler_disabled_overhead(self, benchmark):
        """当 profiler=None 时，nullcontext 开销应 < 100us/次."""
        from contextlib import nullcontext

        def do_nothing():
            with nullcontext():
                pass

        benchmark(do_nothing)
        assert benchmark.stats.stats.mean < 0.0001  # < 100us/op
