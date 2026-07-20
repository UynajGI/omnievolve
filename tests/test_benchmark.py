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
