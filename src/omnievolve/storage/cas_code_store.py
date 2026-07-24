"""CAS 代码存储后端适配器 — 包装 ArtifactStore，零行为变更.

Phase 1: 实现 CodeStore Protocol 的全部方法，
CAS 后端不支持的操作提供降级实现。
"""

from __future__ import annotations

import difflib
import logging
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from omnievolve.storage.code_store import WorktreeHandle

if TYPE_CHECKING:
    from omnievolve.storage.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)


class CASCodeStore:
    """CAS 后端适配器 — 包装 ArtifactStore。

    所有操作委托给底层 ArtifactStore (SHA-256 CAS)。
    CAS 不支持 ancestry/merge/checkpoint，
    这些方法提供降级实现（返回空/None）。
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
        code: str,
        *,
        parents: list[str] | None = None,
        message: str = "",
        meta: dict[str, Any] | None = None,
    ) -> str:
        """存储代码快照 → 返回 SHA-256 hash.

        CAS 后端忽略 parents/message/meta（无 ancestry 概念）。
        血缘关系由 candidate_lineage 表维护。
        """
        return self._store.store_text(code, "source")

    def load_snapshot(self, ref: str) -> str:
        """加载代码快照文本."""
        return self._store.load_text(ref)

    def exists(self, ref: str) -> bool:
        """检查 ref 是否存在."""
        try:
            self._store.load(ref)
            return True
        except Exception:
            return False

    def materialize(self, ref: str) -> WorktreeHandle:
        """物化工作区 — 创建临时目录 + 写 main.py."""
        wt_path = self._work_root / f"exec_{uuid.uuid4().hex[:8]}"
        wt_path.mkdir(parents=True, exist_ok=True)
        code = self.load_snapshot(ref)
        (wt_path / "main.py").write_text(code)
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
        """返回 unified diff（用 difflib 计算）."""
        parent = self.load_snapshot(parent_ref).splitlines(keepends=True)
        child = self.load_snapshot(child_ref).splitlines(keepends=True)
        return "".join(
            difflib.unified_diff(parent, child, "parent", "child")
        )

    def get_parents(self, ref: str) -> list[str]:
        """CAS 无 ancestry — 返回空列表."""
        return []

    def merge(self, parent_refs: list[str]) -> str | None:
        """CAS 不支持原生 merge — 返回 None（触发 fallback 到文本 crossover）."""
        return None

    def checkpoint(self, name: str, ref: str) -> None:
        """CAS 无 reflog — 无操作."""

    def list_checkpoints(self) -> list[tuple[str, str]]:
        """CAS 无 reflog — 返回空列表."""
        return []
