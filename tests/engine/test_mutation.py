"""mutation.py 单元测试 — ArtifactMaterializer + MutationRegistry."""

from __future__ import annotations

import pytest

from omnievolve.engine.mutation import (
    ArtifactMaterializer,
    MutationRegistry,
    get_global_registry,
)
from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database

pytestmark = pytest.mark.unit


@pytest.fixture
def db():
    database = create_memory_database()
    initialize_database(database)
    yield database
    database.close()


@pytest.fixture
def store(db, tmp_path):
    return ArtifactStore(tmp_path / "artifacts", db)


@pytest.fixture
def materializer(store):
    return ArtifactMaterializer(store)


class TestArtifactMaterializer:
    """ArtifactMaterializer — 候选代码物化."""

    def test_materialize_writes_code_to_target(self, materializer, store, tmp_path):
        """物化候选代码到目标目录."""
        code = "def solve():\n    return 42\n"
        h = store.store_text(code, "source")
        target = tmp_path / "work"

        path = materializer.materialize(h, target)

        assert path == target / "main.py"
        assert path.read_text() == code

    def test_materialize_custom_filename(self, materializer, store, tmp_path):
        """支持自定义文件名."""
        code = "x = 1\n"
        h = store.store_text(code, "source")
        target = tmp_path / "custom"

        path = materializer.materialize(h, target, filename="solver.py")

        assert path == target / "solver.py"
        assert path.read_text() == code

    def test_materialize_creates_target_dir(self, materializer, store, tmp_path):
        """目标目录不存在时自动创建."""
        code = "pass\n"
        h = store.store_text(code, "source")
        target = tmp_path / "nonexistent" / "subdir"

        path = materializer.materialize(h, target)

        assert path.exists()
        assert path.read_text() == code

    def test_materialize_with_manifest(self, materializer, store, tmp_path):
        """通过 Manifest 物化多个文件."""
        h1 = store.store_text("a = 1\n", "source")
        h2 = store.store_text("b = 2\n", "source")

        from omnievolve.utils.hashing import ArtifactManifest, ManifestEntry

        manifest = ArtifactManifest(
            entries=[
                ManifestEntry(path="a.py", artifact_hash=h1, artifact_type="source", byte_size=6),
                ManifestEntry(path="b.py", artifact_hash=h2, artifact_type="source", byte_size=6),
            ]
        )
        mh = store.store_manifest(manifest)
        target = tmp_path / "manifest_target"

        paths = materializer.materialize_with_manifest(mh, target)

        assert len(paths) == 2
        assert (target / "a.py").read_text() == "a = 1\n"
        assert (target / "b.py").read_text() == "b = 2\n"

    def test_apply_diff_fallback_full_code(self, materializer, store, tmp_path):
        """patch 命令不可用时 fallback 到完整代码."""
        base = "original code\n"
        h = store.store_text(base, "source")
        target = tmp_path / "diff_target"
        new_code = "new code\n"

        path = materializer.apply_diff(h, new_code, target)

        assert path.read_text() == new_code

    def test_apply_diff_preserves_base_when_diff_starts_with_header(
        self, materializer, store, tmp_path
    ):
        """diff 以 --- 开头时保留基础代码."""
        base = "original code\n"
        h = store.store_text(base, "source")
        target = tmp_path / "diff2"
        diff = "--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-original\n+modified\n"

        path = materializer.apply_diff(h, diff, target)

        assert path.read_text() == base  # fallback：patch 不可用时保留原样


class TestMutationRegistry:
    """MutationRegistry — 变异算子注册表."""

    def test_register_and_get(self):
        registry = MutationRegistry()
        registry.register("flip_sign", lambda x: -x)
        assert registry.get("flip_sign") is not None
        assert registry.get("nonexistent") is None

    def test_list_operators(self):
        registry = MutationRegistry()
        registry.register("op_a", 1)
        registry.register("op_b", 2)
        assert set(registry.list_operators()) == {"op_a", "op_b"}

    def test_select_weighted(self):
        registry = MutationRegistry()
        registry.register("point", 1)
        registry.register("crossover", 2)
        registry.register("rewrite", 3)

        # 1000 次加权采样，验证所有算子都有机会被选中
        counts = {"point": 0, "crossover": 0, "rewrite": 0}
        for _ in range(1000):
            name = registry.select({"point": 1.0, "crossover": 1.0, "rewrite": 1.0})
            counts[name] += 1

        # 等权重，每个都应该 > 200
        assert all(c > 200 for c in counts.values())

    def test_select_single_operator(self):
        registry = MutationRegistry()
        registry.register("only", "value")
        for _ in range(10):
            assert registry.select({"only": 1.0}) == "only"

    def test_global_registry_is_singleton(self):
        r1 = get_global_registry()
        r2 = get_global_registry()
        assert r1 is r2

    def test_filter_empty_registry_returns_empty(self):
        registry = MutationRegistry()
        assert registry.list_operators() == []
        assert registry.get("anything") is None
