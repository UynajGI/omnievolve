"""Artifact Store 测试.

S1-15: 实现 Artifact 去重、损坏检测与恢复测试
- 损坏 hash 可发现
- 部分写入不被当成有效对象
"""

from pathlib import Path

import pytest

from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database
from omnievolve.utils.hashing import (
    ArtifactManifest,
    ManifestEntry,
    compute_sha256,
    compute_sha256_str,
)


@pytest.fixture
def db():
    """创建已初始化的内存数据库."""
    database = create_memory_database()
    initialize_database(database)
    yield database
    database.close()


@pytest.fixture
def store(tmp_path: Path, db):
    """创建 ArtifactStore."""
    return ArtifactStore(tmp_path / "artifacts", db)


class TestArtifactStore:
    """ArtifactStore 基本功能测试."""

    def test_store_and_load(self, store: ArtifactStore):
        """存储和加载 artifact."""
        data = b"Hello, OmniEvolve!"
        artifact_hash = store.store(data, "source")

        assert len(artifact_hash) == 64  # SHA-256 hex
        assert store.load(artifact_hash) == data

    def test_store_text(self, store: ArtifactStore):
        """存储文本 artifact."""
        text = "print('hello world')"
        artifact_hash = store.store_text(text, "source")

        assert store.load_text(artifact_hash) == text

    def test_deduplication(self, store: ArtifactStore):
        """相同内容只存储一次."""
        data = b"duplicate content"
        hash1 = store.store(data, "source")
        hash2 = store.store(data, "source")

        assert hash1 == hash2
        # 文件系统中只有一个文件
        assert store.exists(hash1)

    def test_different_content_different_hash(self, store: ArtifactStore):
        """不同内容产生不同哈希."""
        hash1 = store.store(b"content A", "source")
        hash2 = store.store(b"content B", "source")

        assert hash1 != hash2

    def test_exists(self, store: ArtifactStore):
        """检查 artifact 是否存在."""
        data = b"test data"
        artifact_hash = store.store(data, "source")

        assert store.exists(artifact_hash)
        assert not store.exists("nonexistent_hash")

    def test_get_info(self, store: ArtifactStore):
        """获取 artifact 元数据."""
        data = b"test data"
        artifact_hash = store.store(
            data, "source", media_type="text/x-python", meta={"key": "value"}
        )

        info = store.get_info(artifact_hash)
        assert info is not None
        assert info.hash == artifact_hash
        assert info.artifact_type == "source"
        assert info.byte_size == len(data)
        assert info.media_type == "text/x-python"
        assert info.meta == {"key": "value"}

    def test_load_nonexistent(self, store: ArtifactStore):
        """加载不存在的 artifact 应抛出异常."""
        with pytest.raises(FileNotFoundError):
            store.load("nonexistent_hash")


class TestArtifactIntegrity:
    """Artifact 完整性测试."""

    def test_verify_valid(self, store: ArtifactStore):
        """验证有效的 artifact."""
        data = b"valid content"
        artifact_hash = store.store(data, "source")

        assert store.verify(artifact_hash)

    def test_verify_corrupted(self, store: ArtifactStore, tmp_path: Path):
        """检测损坏的 artifact."""
        data = b"original content"
        artifact_hash = store.store(data, "source")

        # 手动损坏文件
        artifact_path = store._artifact_path(artifact_hash)
        artifact_path.write_bytes(b"corrupted content")

        assert not store.verify(artifact_hash)

    def test_load_corrupted_raises(self, store: ArtifactStore):
        """加载损坏的 artifact 应抛出异常."""
        data = b"original content"
        artifact_hash = store.store(data, "source")

        # 手动损坏文件
        artifact_path = store._artifact_path(artifact_hash)
        artifact_path.write_bytes(b"corrupted content")

        with pytest.raises(ValueError, match="corrupted"):
            store.load(artifact_hash)

    def test_verify_nonexistent(self, store: ArtifactStore):
        """验证不存在的 artifact 返回 False."""
        assert not store.verify("nonexistent_hash")


class TestManifest:
    """Manifest 测试."""

    def test_manifest_roundtrip(self, store: ArtifactStore):
        """Manifest 序列化和反序列化."""
        # 先存储一些 artifact
        hash1 = store.store(b"file1 content", "source")
        hash2 = store.store(b"file2 content", "source")

        manifest = ArtifactManifest(
            entries=[
                ManifestEntry(
                    path="src/main.py",
                    artifact_hash=hash1,
                    artifact_type="source",
                    byte_size=13,
                    media_type="text/x-python",
                ),
                ManifestEntry(
                    path="src/utils.py",
                    artifact_hash=hash2,
                    artifact_type="source",
                    byte_size=13,
                    media_type="text/x-python",
                ),
            ],
            metadata={"version": "1.0"},
        )

        manifest_hash = store.store_manifest(manifest)
        loaded = store.load_manifest(manifest_hash)

        assert len(loaded.entries) == 2
        assert loaded.entries[0].path == "src/main.py"
        assert loaded.metadata == {"version": "1.0"}

    def test_manifest_hash_stable(self):
        """Manifest 哈希应稳定."""
        manifest = ArtifactManifest(
            entries=[
                ManifestEntry(
                    path="test.py",
                    artifact_hash="abc123",
                    artifact_type="source",
                    byte_size=100,
                )
            ]
        )

        hash1 = manifest.compute_hash()
        hash2 = manifest.compute_hash()
        assert hash1 == hash2


class TestHashing:
    """哈希工具测试."""

    def test_sha256_deterministic(self):
        """SHA-256 应确定性."""
        data = b"test data"
        assert compute_sha256(data) == compute_sha256(data)

    def test_sha256_str(self):
        """字符串哈希."""
        text = "hello world"
        expected = compute_sha256(text.encode("utf-8"))
        assert compute_sha256_str(text) == expected

    def test_different_data_different_hash(self):
        """不同数据产生不同哈希."""
        assert compute_sha256(b"data1") != compute_sha256(b"data2")


class TestArtifactStats:
    """Artifact 统计测试."""

    def test_get_stats(self, store: ArtifactStore):
        """获取存储统计."""
        store.store(b"source1", "source")
        store.store(b"source2", "source")
        store.store(b"log1", "log")

        stats = store.get_stats()
        assert stats["total_count"] == 3
        assert stats["by_type"]["source"] == 2
        assert stats["by_type"]["log"] == 1

    def test_list_artifacts(self, store: ArtifactStore):
        """列出 artifact."""
        store.store(b"source1", "source")
        store.store(b"log1", "log")

        all_artifacts = store.list_artifacts()
        assert len(all_artifacts) == 2

        sources = store.list_artifacts(artifact_type="source")
        assert len(sources) == 1
        assert sources[0].artifact_type == "source"
