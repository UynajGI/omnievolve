"""内容哈希与 Manifest 工具.

S1-06: SHA-256 内容寻址
S1-07: Artifact Manifest 与 MIME/类型登记
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def compute_sha256(data: bytes) -> str:
    """计算字节数据的 SHA-256 哈希."""
    return hashlib.sha256(data).hexdigest()


def compute_sha256_file(path: str | Path) -> str:
    """计算文件的 SHA-256 哈希（流式读取）."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def compute_sha256_str(text: str) -> str:
    """计算字符串的 SHA-256 哈希."""
    return compute_sha256(text.encode("utf-8"))


# Artifact 类型常量
ARTIFACT_SOURCE = "source"
ARTIFACT_DIFF = "diff"
ARTIFACT_MANIFEST = "manifest"
ARTIFACT_LOG = "log"
ARTIFACT_REPORT = "report"
ARTIFACT_BINARY = "binary"
ARTIFACT_STDOUT = "stdout"
ARTIFACT_STDERR = "stderr"

# MIME 类型映射
MIME_TYPES = {
    "source": "text/x-source",
    "diff": "text/x-diff",
    "manifest": "application/json",
    "log": "text/plain",
    "report": "application/json",
    "binary": "application/octet-stream",
    "stdout": "text/plain",
    "stderr": "text/plain",
}


@dataclass(frozen=True)
class ArtifactManifest:
    """Artifact Manifest - 描述一组相关 Artifact 的元数据.

    S1-07: 实现 Artifact Manifest 与 MIME/类型登记
    """

    entries: list[ManifestEntry] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """序列化为 JSON."""
        return json.dumps(
            {
                "entries": [e.to_dict() for e in self.entries],
                "metadata": self.metadata,
            },
            indent=2,
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, data: str) -> ArtifactManifest:
        """从 JSON 反序列化."""
        obj = json.loads(data)
        entries = [ManifestEntry.from_dict(e) for e in obj.get("entries", [])]
        return cls(entries=entries, metadata=obj.get("metadata", {}))

    def compute_hash(self) -> str:
        """计算 Manifest 的内容哈希."""
        return compute_sha256_str(self.to_json())


@dataclass(frozen=True)
class ManifestEntry:
    """Manifest 中的单个条目."""

    path: str
    artifact_hash: str
    artifact_type: str
    byte_size: int
    media_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "artifact_hash": self.artifact_hash,
            "artifact_type": self.artifact_type,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManifestEntry:
        return cls(
            path=data["path"],
            artifact_hash=data["artifact_hash"],
            artifact_type=data["artifact_type"],
            byte_size=data["byte_size"],
            media_type=data.get("media_type"),
        )


def get_media_type(artifact_type: str, file_ext: str | None = None) -> str:
    """根据 artifact 类型和文件扩展名获取 MIME 类型."""
    if file_ext:
        ext_map = {
            ".py": "text/x-python",
            ".js": "text/javascript",
            ".ts": "text/typescript",
            ".json": "application/json",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".diff": "text/x-diff",
            ".patch": "text/x-diff",
        }
        if file_ext in ext_map:
            return ext_map[file_ext]

    return MIME_TYPES.get(artifact_type, "application/octet-stream")


def artifact_path_from_hash(artifact_hash: str) -> str:
    """根据哈希生成相对存储路径.

    使用两级目录避免单目录文件过多：
    sha256/ab/cd/<full_hash>
    """
    return f"sha256/{artifact_hash[:2]}/{artifact_hash[2:4]}/{artifact_hash}"
