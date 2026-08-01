"""CAS 代码存储后端适配器 — 基于 manifest 的多文件快照.

入口源码仍以独立 artifact 存储；快照 ref 指向包含完整文件树的 manifest。
旧的单源码 artifact ref 仍可读取和物化。
"""

from __future__ import annotations

import difflib
import logging
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from omnievolve.storage.code_store import WorktreeHandle
from omnievolve.utils.hashing import ArtifactManifest, ManifestEntry

if TYPE_CHECKING:
    from omnievolve.storage.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)


class CASCodeStore:
    """CAS 后端适配器 — 包装 ArtifactStore。

    所有操作委托给底层 ArtifactStore (SHA-256 CAS)。
    ancestry 存在 manifest metadata 中；merge/checkpoint 仍提供降级实现。
    """

    def __init__(self, store: ArtifactStore, work_root: Path) -> None:
        """初始化.

        Args:
            store: ArtifactStore 实例
            work_root: 临时工作目录根
        """
        self._store = store
        self._work_root = Path(work_root)

    @property
    def backend_name(self) -> str:
        """后端名称."""
        return "cas"

    def store_snapshot(
        self,
        code: str | Mapping[str, str],
        *,
        parents: list[str] | None = None,
        message: str = "",
        meta: dict[str, Any] | None = None,
    ) -> str:
        """存储单文件或多文件代码快照，返回 manifest hash.

        当 ``code`` 是字符串且父代为 manifest 时，仅替换父代入口文件，
        其余文件保持不变。这让现有单文件 Coder 可以安全演化多文件项目。
        """
        metadata = dict(meta or {})
        parent_refs = list(parents or [])

        if isinstance(code, str):
            files: dict[str, str] = {}
            entrypoint = str(metadata.get("entrypoint") or "main.py")
            if parent_refs and self.is_snapshot_manifest(parent_refs[0]):
                parent_manifest = self._store.load_manifest(parent_refs[0])
                files = self.load_snapshot_files(parent_refs[0])
                entrypoint = str(parent_manifest.metadata.get("entrypoint") or entrypoint)
            files[entrypoint] = code
        else:
            files = dict(code)
            if not files:
                raise ValueError("A code snapshot must contain at least one file")
            requested_entrypoint = metadata.get("entrypoint")
            if requested_entrypoint:
                entrypoint = str(requested_entrypoint)
            elif "main.py" in files:
                entrypoint = "main.py"
            else:
                python_files = sorted(path for path in files if path.endswith(".py"))
                entrypoint = python_files[0] if python_files else sorted(files)[0]

        normalized = {
            self._validate_snapshot_path(path): content for path, content in files.items()
        }
        entrypoint = self._validate_snapshot_path(entrypoint)
        if entrypoint not in normalized:
            raise ValueError(f"Snapshot entrypoint is missing: {entrypoint}")
        if any(not isinstance(content, str) for content in normalized.values()):
            raise TypeError("Code snapshot files must contain text")

        entries = []
        for path, content in sorted(normalized.items()):
            encoded = content.encode("utf-8")
            artifact_hash = self._store.store(encoded, "source", media_type="text/x-source")
            entries.append(
                ManifestEntry(
                    path=path,
                    artifact_hash=artifact_hash,
                    artifact_type="source",
                    byte_size=len(encoded),
                    media_type="text/x-source",
                )
            )

        manifest = ArtifactManifest(
            entries=entries,
            metadata={
                "schema": "omnievolve.code_snapshot.v1",
                "entrypoint": entrypoint,
                "parents": parent_refs,
                "message": message,
                "meta": metadata,
            },
        )
        return self._store.store_manifest(manifest)

    @staticmethod
    def _validate_snapshot_path(path: str) -> str:
        """验证并规范化 manifest 内的 POSIX 相对路径."""
        if not isinstance(path, str) or not path or "\x00" in path or "\\" in path:
            raise ValueError(f"Invalid snapshot path: {path!r}")
        pure = PurePosixPath(path)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise ValueError(f"Unsafe snapshot path: {path!r}")
        normalized = pure.as_posix()
        if normalized != path:
            raise ValueError(f"Snapshot path must be normalized: {path!r}")
        return normalized

    def is_snapshot_manifest(self, ref: str) -> bool:
        """判断 ref 是否为本后端的代码快照 manifest."""
        try:
            manifest = self._store.load_manifest(ref)
        except (FileNotFoundError, UnicodeDecodeError, ValueError, TypeError):
            return False
        return manifest.metadata.get("schema") == "omnievolve.code_snapshot.v1"

    def get_snapshot_entrypoint_ref(self, ref: str) -> str:
        """返回快照入口源码的 artifact hash；兼容旧单文件 ref."""
        if not self.is_snapshot_manifest(ref):
            return ref
        manifest = self._store.load_manifest(ref)
        entrypoint = manifest.metadata.get("entrypoint", "main.py")
        for entry in manifest.entries:
            if entry.path == entrypoint:
                return entry.artifact_hash
        raise ValueError(f"Snapshot manifest has no entrypoint: {entrypoint}")

    def load_snapshot_files(self, ref: str) -> dict[str, str]:
        """加载完整快照文件树；旧 ref 映射为 ``main.py``."""
        if not self.is_snapshot_manifest(ref):
            return {"main.py": self._store.load_text(ref)}
        manifest = self._store.load_manifest(ref)
        files: dict[str, str] = {}
        for entry in manifest.entries:
            path = self._validate_snapshot_path(entry.path)
            files[path] = self._store.load_text(entry.artifact_hash)
        return files

    def store_text(self, text: str, artifact_type: str = "source", **kwargs) -> str:
        """ArtifactStore 兼容: 存储文本 → 返回 SHA-256 hash."""
        return self._store.store_text(text, artifact_type)

    def store(self, data: bytes, artifact_type: str = "report", **kwargs) -> str:
        """ArtifactStore 兼容: 存储字节 → 返回 SHA-256 hash."""
        return self._store.store(data, artifact_type, **kwargs)

    def load(self, ref: str) -> bytes:
        """ArtifactStore 兼容: 加载字节."""
        if self.is_snapshot_manifest(ref):
            return self._store.load(self.get_snapshot_entrypoint_ref(ref))
        return self._store.load(ref)

    def load_text(self, ref: str) -> str:
        """ArtifactStore 兼容: 加载文本."""
        if self.is_snapshot_manifest(ref):
            return self._store.load_text(self.get_snapshot_entrypoint_ref(ref))
        return self._store.load_text(ref)

    def load_manifest(self, ref: str):
        """ArtifactStore 兼容: 加载 Manifest."""
        return self._store.load_manifest(ref)

    def load_snapshot(self, ref: str) -> str:
        """加载入口代码文本."""
        return self._store.load_text(self.get_snapshot_entrypoint_ref(ref))

    def exists(self, ref: str) -> bool:
        """检查 ref 是否存在."""
        try:
            self._store.load(ref)
            return True
        except Exception:
            return False

    def materialize(self, ref: str) -> WorktreeHandle:
        """物化工作区 — 安全写出 manifest 中的完整文件树."""
        wt_path = self._work_root / f"exec_{uuid.uuid4().hex[:8]}"
        wt_path.mkdir(parents=True, exist_ok=True)
        try:
            for relative_path, content in self.load_snapshot_files(ref).items():
                destination = wt_path.joinpath(*PurePosixPath(relative_path).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")
        except Exception:
            shutil.rmtree(wt_path, ignore_errors=True)
            raise
        return WorktreeHandle(
            path=wt_path,
            backend_id="cas",
            needs_cleanup=True,
        )

    def release(self, handle: WorktreeHandle) -> None:
        """释放物化的工作区."""
        if handle.needs_cleanup:
            shutil.rmtree(handle.path, ignore_errors=True)

    def diff(self, parent_ref: str, child_ref: str) -> str:
        """返回逐文件 unified diff."""
        parent_files = self.load_snapshot_files(parent_ref)
        child_files = self.load_snapshot_files(child_ref)
        chunks: list[str] = []
        for path in sorted(parent_files.keys() | child_files.keys()):
            parent = parent_files.get(path, "").splitlines(keepends=True)
            child = child_files.get(path, "").splitlines(keepends=True)
            chunks.extend(difflib.unified_diff(parent, child, f"a/{path}", f"b/{path}"))
        return "".join(chunks)

    def get_parents(self, ref: str) -> list[str]:
        """从快照 manifest 读取父代；旧 ref 无 ancestry."""
        if not self.is_snapshot_manifest(ref):
            return []
        manifest = self._store.load_manifest(ref)
        parents = manifest.metadata.get("parents", [])
        return [str(parent) for parent in parents] if isinstance(parents, list) else []

    def merge(self, parent_refs: list[str]) -> str | None:
        """CAS 不支持原生 merge — 返回 None（触发 fallback 到文本 crossover）."""
        return None

    def checkpoint(self, name: str, ref: str) -> None:
        """CAS 无 reflog — 无操作."""

    def list_checkpoints(self) -> list[tuple[str, str]]:
        """CAS 无 reflog — 返回空列表."""
        return []
