"""属性基测试 (Property-Based Testing).

Gap P2: 使用 hypothesis 验证核心不变量。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database
from omnievolve.utils.hashing import compute_sha256

pytestmark = [pytest.mark.unit]


def _make_store() -> tuple[ArtifactStore, Path]:
    """创建临时 ArtifactStore（含 schema 初始化）."""
    tmp = Path(tempfile.mkdtemp(prefix="omnievolve_props_"))
    db = create_memory_database()
    initialize_database(db)
    store = ArtifactStore(tmp, db)
    return store, tmp


class TestArtifactStoreProperties:
    """ArtifactStore 不变量."""

    @given(data=st.binary(min_size=1, max_size=10_000))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_store_then_load_roundtrip(self, data):
        """存储后立即加载应返回相同内容."""
        store, _ = _make_store()
        h = store.store(data, "source")
        assert store.load(h) == data

    @given(data=st.binary(min_size=1, max_size=10_000))
    @settings(max_examples=100)
    def test_hash_is_deterministic(self, data):
        """同一内容多次哈希结果应一致."""
        h1 = compute_sha256(data)
        h2 = compute_sha256(data)
        assert h1 == h2

    @given(
        a=st.binary(min_size=1, max_size=5000),
        b=st.binary(min_size=1, max_size=5000),
    )
    @settings(max_examples=100)
    def test_different_data_different_hash(self, a, b):
        """不同内容应有不同哈希."""
        assume(a != b)
        assert compute_sha256(a) != compute_sha256(b)

    @given(data=st.binary(min_size=1, max_size=10_000))
    @settings(max_examples=100)
    def test_hash_length_is_constant(self, data):
        """SHA-256 始终返回 64 个十六进制字符."""
        h = compute_sha256(data)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    @given(data=st.binary(min_size=1, max_size=5000))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_store_is_idempotent(self, data):
        """同一内容存储两次返回相同哈希."""
        store, _ = _make_store()
        h1 = store.store(data, "source")
        h2 = store.store(data, "source")
        assert h1 == h2


class TestMCTSProperties:
    """MCTS 不变量."""

    @given(
        rewards=st.lists(st.floats(0.0, 1.0), min_size=1, max_size=50),
    )
    @settings(max_examples=50)
    def test_beta_mean_in_zero_one_range(self, rewards):
        """Beta 后验均值始终在 [0, 1] 范围内."""
        from omnievolve.engine.mcts import MCTSNode

        node = MCTSNode(candidate_id="test", prior=0.1)
        for r in rewards:
            node.update_beta(r)
        assert 0.0 <= node.mean_value <= 1.0

    @given(
        rewards=st.lists(st.floats(0.0, 1.0), min_size=10, max_size=100),
    )
    @settings(max_examples=30)
    def test_more_samples_reduces_variance(self, rewards):
        """更多样本应降低 Beta 方差."""
        from omnievolve.engine.mcts import MCTSNode

        node = MCTSNode(candidate_id="test")
        node.update_beta(rewards[0])
        var_after_1 = node.beta_variance

        for r in rewards[1:]:
            node.update_beta(r)
        var_after_all = node.beta_variance

        assert var_after_all < var_after_1, (
            f"Variance should decrease: {var_after_all:.6f} >= {var_after_1:.6f}"
        )
